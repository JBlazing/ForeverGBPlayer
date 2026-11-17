"""Link cable test: two emulators, each with its own Link.lua port, swap 16 bytes through a
simulated whisper channel (latency, FojjiCore Comm's one-message-per-0.35 s queue, lost
messages). Checks every byte arrives, in order, on both sides.

The test ROM (built here, in memory) waits until $C100 is set, then sends 16 bytes counting
up from the value in $C101, writing the value in $C102 to SC for each (0x81 = own clock,
0x80 = the other side's clock) and storing each received byte at $C200+. $C1FF = 0xAA when done.

    py tools/test_link.py
"""
import pathlib
import random
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from test_ppu import boot  # noqa: E402
from make_joypad_test import LOGO  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
LINK = ROOT / "ForeverGBPlayer" / "Link.lua"
COUNT = 16
FRAME = 70224 / 4194304
COMM_GAP = 0.35  # FojjiCore Games Base/Comm.lua: one queued message per 0.35 s


def build_rom():
    code = bytes([
        0xFA, 0x00, 0xC1, 0xA7, 0x28, 0xFA,  # wait: LD A,($C100); AND A; JR Z,wait
        0xFA, 0x01, 0xC1, 0x47,              # LD A,($C101); LD B,A   first byte to send
        0xFA, 0x02, 0xC1, 0x57,              # LD A,($C102); LD D,A   SC value
        0x21, 0x00, 0xC2, 0x0E, COUNT,       # LD HL,$C200; LD C,16
        # loop:
        0x78, 0xE0, 0x01, 0x7A, 0xE0, 0x02,  # LD A,B; LDH ($01),A; LD A,D; LDH ($02),A
        0xF0, 0x02, 0xE6, 0x80, 0x20, 0xFA,  # poll: LDH A,($02); AND $80; JR NZ,poll
        0xF0, 0x01, 0x22, 0x04, 0x0D,        # LDH A,($01); LD (HL+),A; INC B; DEC C
        0x20, 0xED,                          # JR NZ,loop
        0x3E, 0xAA, 0xEA, 0xFF, 0xC1,        # LD A,$AA; LD ($C1FF),A
        0x18, 0xFE,                          # JR $
    ])
    rom = bytearray(0x8000)
    rom[0x100:0x104] = bytes([0x00, 0xC3, 0x50, 0x01])
    rom[0x104:0x134] = LOGO
    rom[0x134:0x143] = b"LINK TEST".ljust(15, b"\0")
    rom[0x150:0x150 + len(code)] = code
    hdr = 0
    for b in rom[0x134:0x14D]:
        hdr = (hdr - b - 1) & 0xFF
    rom[0x14D] = hdr
    total = (sum(rom) - rom[0x14E] - rom[0x14F]) & 0xFFFF
    rom[0x14E], rom[0x14F] = total >> 8, total & 0xFF
    return bytes(rom)


class Side:
    def __init__(self, name, rom_path, net):
        self.name, self.net = name, net
        self.lua, self.core = boot(rom_path)
        self.lua.execute("print = function() end")
        chunk = self.lua.eval("loadstring")(LINK.read_text(encoding="utf-8"), "@Link.lua")
        chunk("ForeverGBPlayer")
        make = self.lua.eval("""function(send, now)
            return ForeverGBPlayer.NewLinkPort({
                send = function(sub, a, b) send(sub, tostring(a), tostring(b)) end,
                now = now,
            })
        end""")
        self.port = make(lambda sub, a, b: net.send(self, sub, a, b), lambda: net.now)
        self.attached = False
        self.next_free = 0.0  # this side's Comm queue

    def attach(self):
        self.port.Attach(self.core)
        self.attached = True

    def start(self, first, sc):
        self.core.Write(0xC101, first)
        self.core.Write(0xC102, sc)
        self.core.Write(0xC100, 1)

    def done(self):
        return self.core.Read(0xC1FF) == 0xAA

    def got(self):
        return [self.core.Read(0xC200 + i) for i in range(COUNT)]

    def frame(self):
        self.port.Tick()
        if not self.port.Holding():
            self.core.RunFrame()


class Net:
    def __init__(self, latency, drop, seed):
        self.now, self.latency, self.drop = 0.0, latency, drop
        self.rng = random.Random(seed)
        self.inflight = []
        self.sent = 0

    def send(self, sender, sub, a, b):
        t = max(self.now, sender.next_free)
        sender.next_free = t + COMM_GAP
        self.sent += 1
        if self.rng.random() < self.drop:
            return
        self.inflight.append((t + self.latency * (0.7 + 0.6 * self.rng.random()), sender, sub, a, b))

    def deliver(self, sides):
        due = sorted((m for m in self.inflight if m[0] <= self.now), key=lambda m: m[0])
        self.inflight = [m for m in self.inflight if m[0] > self.now]
        for _, sender, sub, a, b in due:
            other = sides[1] if sender is sides[0] else sides[0]
            other.port.Receive(sub, a, b)


def run(label, rom_path, a_cfg, b_cfg, expect_a, expect_b, latency=0.15, drop=0.0, seed=1,
        b_attached=True, b_start_at=0.0, limit=120.0):
    net = Net(latency, drop, seed)
    a, b = Side("A", rom_path, net), Side("B", rom_path, net)
    a.attach()
    if b_attached:
        b.attach()
    a.start(*a_cfg)
    b_started = False
    while net.now < limit:
        if not b_started and net.now >= b_start_at:
            b.start(*b_cfg)
            b_started = True
        net.deliver((a, b))
        a.frame()
        b.frame()
        net.now += FRAME
        if a.done() and (b.done() or not b_attached):
            break
    ok_a = a.done() and a.got() == expect_a
    ok_b = not b_attached or (b.done() and b.got() == expect_b)
    ok = ok_a and ok_b
    print(f"  {'ok  ' if ok else 'FAIL'} {label:44} {net.now:6.1f} s, {net.sent} whispers"
          + ("" if ok else f"\n       A {a.done()} {a.got()}\n       B {b.done()} {b.got()}"))
    return ok


def main():
    with tempfile.TemporaryDirectory() as tmp:
        rom_path = pathlib.Path(tmp) / "link-test.gb"
        rom_path.write_bytes(build_rom())
        lo = [0x10 + i for i in range(COUNT)]
        hi = [0x80 + i for i in range(COUNT)]
        results = [
            run("own clock <-> other's clock", rom_path, (0x10, 0x81), (0x80, 0x80), hi, lo),
            run("same, slow whispers (0.6 s)", rom_path, (0x10, 0x81), (0x80, 0x80), hi, lo, latency=0.6),
            run("same, 15% of whispers lost", rom_path, (0x10, 0x81), (0x80, 0x80), hi, lo, drop=0.15, seed=7),
            run("both on their own clock at once", rom_path, (0x10, 0x81), (0x80, 0x81), hi, lo),
            run("nobody running a game on the other end", rom_path, (0x10, 0x81), (0x80, 0x80),
                [0xFF] * COUNT, None, b_attached=False),
        ]
    failed = results.count(False)
    print("link:", "PASS" if not failed else f"{failed} case(s) failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
