"""Build two tiny hand-assembled test ROMs (written here, no external assembler):

testroms/cgb/cgb-test.gbc  (CGB only)
    measures a busy loop over one frame at normal speed and after a double-speed
    switch (KEY1 + STOP), runs a general-purpose DMA (ROM 0x400 -> VRAM bank 0 0x8000)
    and an HBlank DMA (ROM 0x420 -> VRAM bank 1 0x8100), and checks WRAM banking.
    Results in WRAM:  C000/1 = normal-speed count, C002/3 = double-speed count,
    C004 = KEY1 after switch, C005 = FF55 right after starting HBlank DMA,
    C006 = FF55 a frame later, C007/C008 = D000 read back in WRAM banks 1/2,
    C009 = FF70, C00A = 0x5A done marker.

testroms/cgb/save-test.gb  (MBC1+RAM+BATTERY, 32 KB RAM)
    each boot: RAM bank 0 [A000] += 1, RAM bank 2 [A000] += 3, copies bank 0 to C000.
    Fresh RAM is 0xFF, so boot 1 leaves 0x00 / 0x02, boot 2 leaves 0x01 / 0x05.

    py tools/make_cgb_tests.py
"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "testroms" / "cgb"
LOGO = bytes.fromhex(
    "CEED6666CC0D000B03730083000C000D0008111F8889000EDCCC6EE6DDDDD999"
    "BBBB67636E0EECCCDDDC999FBBB9333E"
)
DATA = bytes((i * 7 + 3) & 0xFF for i in range(64))  # DMA source at 0x400


class Asm:
    """Minimal two-pass assembler: raw bytes + labels + JR/CALL fixups."""

    def __init__(self, org):
        self.org, self.code, self.labels, self.fix = org, bytearray(), {}, []

    def b(self, *bs):
        self.code += bytes(bs)

    def label(self, name):
        self.labels[name] = self.org + len(self.code)

    def jr(self, opcode, name):  # 0x18 JR, 0x20 NZ, 0x28 Z
        self.b(opcode, 0)
        self.fix.append(("rel", len(self.code) - 1, name))

    def call(self, name):
        self.b(0xCD, 0, 0)
        self.fix.append(("abs", len(self.code) - 2, name))

    def ldh_w(self, reg, val):  # LD A,val ; LDH (reg),A
        self.b(0x3E, val, 0xE0, reg)

    def ldh_r(self, reg):  # LDH A,(reg)
        self.b(0xF0, reg)

    def st(self, addr):  # LD (addr),A
        self.b(0xEA, addr & 0xFF, addr >> 8)

    def assemble(self):
        for kind, at, name in self.fix:
            target = self.labels[name]
            if kind == "rel":
                off = target - (self.org + at + 1)
                assert -128 <= off <= 127, name
                self.code[at] = off & 0xFF
            else:
                self.code[at:at + 2] = bytes((target & 0xFF, target >> 8))
        return bytes(self.code)


def rom_image(code, title, cgb_flag, cart, ram_code, extra=None):
    rom = bytearray(0x8000)
    rom[0x100:0x104] = bytes([0x00, 0xC3, 0x50, 0x01])
    rom[0x104:0x134] = LOGO
    rom[0x134:0x134 + len(title)] = title
    rom[0x143] = cgb_flag
    rom[0x147], rom[0x148], rom[0x149] = cart, 0x00, ram_code
    rom[0x150:0x150 + len(code)] = code
    for addr, blob in (extra or {}).items():
        rom[addr:addr + len(blob)] = blob
    hdr = 0
    for b in rom[0x134:0x14D]:
        hdr = (hdr - b - 1) & 0xFF
    rom[0x14D] = hdr
    total = (sum(rom) - rom[0x14E] - rom[0x14F]) & 0xFFFF
    rom[0x14E], rom[0x14F] = total >> 8, total & 0xFF
    return bytes(rom)


def cgb_test():
    a = Asm(0x150)
    a.b(0xF3)                                   # DI
    a.call("measure")
    a.b(0x79); a.st(0xC000); a.b(0x78); a.st(0xC001)   # LD A,C / LD A,B
    a.ldh_w(0x4D, 0x01); a.b(0x10, 0x00)        # KEY1 = 1; STOP
    a.ldh_r(0x4D); a.st(0xC004)
    a.call("measure")
    a.b(0x79); a.st(0xC002); a.b(0x78); a.st(0xC003)
    # general-purpose DMA: 0x0400 -> 0x8000 (bank 0), 2 blocks
    a.ldh_w(0x51, 0x04); a.ldh_w(0x52, 0x00); a.ldh_w(0x53, 0x00); a.ldh_w(0x54, 0x00)
    a.ldh_w(0x55, 0x01)
    # HBlank DMA: 0x0420 -> 0x8100 (bank 1), 2 blocks
    a.ldh_w(0x4F, 0x01)
    a.ldh_w(0x51, 0x04); a.ldh_w(0x52, 0x20); a.ldh_w(0x53, 0x01); a.ldh_w(0x54, 0x00)
    a.ldh_w(0x55, 0x81)
    a.ldh_r(0x55); a.st(0xC005)
    # We start in VBlank (measure returns at LY=144), so the first waitframe passes no
    # HBlanks; the second walks through all 144 visible lines.
    a.call("waitframe")
    a.call("waitframe")
    a.ldh_r(0x55); a.st(0xC006)
    a.ldh_w(0x4F, 0x00)
    # WRAM banking
    for bank, val in ((1, 0x11), (2, 0x22), (3, 0x33)):
        a.ldh_w(0x70, bank); a.b(0x3E, val); a.st(0xD000)
    a.ldh_w(0x70, 1); a.b(0xFA, 0x00, 0xD0); a.st(0xC007)
    a.ldh_w(0x70, 2); a.b(0xFA, 0x00, 0xD0); a.st(0xC008)
    a.ldh_r(0x70); a.st(0xC009)
    a.b(0x3E, 0x5A); a.st(0xC00A)
    a.label("end"); a.b(0x76); a.jr(0x18, "end")

    a.label("waitframe")                        # wait for LY=144, then LY=0
    a.label("wf1"); a.ldh_r(0x44); a.b(0xFE, 144); a.jr(0x20, "wf1")
    a.label("wf2"); a.ldh_r(0x44); a.b(0xB7); a.jr(0x20, "wf2")
    a.b(0xC9)
    a.label("measure")                          # BC = loop count from LY=0 to LY=144
    a.call("waitframe")
    a.b(0x01, 0x00, 0x00)                       # LD BC,0
    a.label("cnt"); a.b(0x03); a.ldh_r(0x44); a.b(0xFE, 144); a.jr(0x20, "cnt")
    a.b(0xC9)
    return rom_image(a.assemble(), b"CGB TEST", 0xC0, 0x00, 0x00, {0x400: DATA})


def save_test():
    a = Asm(0x150)
    a.b(0x3E, 0x0A); a.st(0x0000)               # enable cart RAM
    a.b(0x21, 0x00, 0xA0, 0x34)                 # LD HL,$A000 / INC (HL)
    a.b(0x3E, 0x01); a.st(0x6000)               # MBC1 mode 1 (RAM banking)
    a.b(0x3E, 0x02); a.st(0x4000)               # RAM bank 2
    a.b(0x7E, 0xC6, 0x03, 0x77)                 # LD A,(HL) / ADD A,3 / LD (HL),A
    a.b(0xAF); a.st(0x4000); a.st(0x6000)       # back to bank 0, mode 0
    a.b(0xFA, 0x00, 0xA0); a.st(0xC000)
    a.b(0xAF); a.st(0x0000)                     # disable cart RAM
    a.label("end"); a.b(0x76); a.jr(0x18, "end")
    return rom_image(a.assemble(), b"SAVE TEST", 0x00, 0x03, 0x03)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, data in (("cgb-test.gbc", cgb_test()), ("save-test.gb", save_test())):
        (OUT / name).write_bytes(data)
        print(f"wrote {OUT / name}")
