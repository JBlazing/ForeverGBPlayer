"""Generate ForeverGBPlayer/core/Core.lua from src/Core.template.lua.

The template holds the hand-written machine (bus, MBCs, timer, interrupts, ALU
helpers); this script emits one specialised Lua function per opcode (256 base +
256 CB-prefixed) and splices them in at --@@OPS@@. Each handler runs with PC
already past the opcode byte and returns the instruction's T-cycle count.

    py tools/gen_core.py
"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "src" / "Core.template.lua"
OUTPUT = ROOT / "ForeverGBPlayer" / "core" / "Core.lua"

REGS = ["B", "C", "D", "E", "H", "L", None, "A"]  # index 6 = (HL)
HL = "H * 256 + L"
PAIRS = [("B", "C"), ("D", "E"), ("H", "L"), None]  # None = SP (or AF for push/pop)
CONDS = ["not fZ", "fZ", "not fC", "fC"]

INC_HL = "if L == 255 then L = 0; H = (H + 1) % 256 else L = L + 1 end"
DEC_HL = "if L == 0 then L = 255; H = (H + 255) % 256 else L = L - 1 end"
SIGNED = "if e >= 128 then e = e - 256 end"


def alu(y, x):
    """ALU op y (ADD ADC SUB SBC AND XOR OR CP) with operand expression x."""
    return [
        f"add8({x}, 0)",
        f"add8({x}, fC and 1 or 0)",
        f"sub8({x}, 0)",
        f"sub8({x}, fC and 1 or 0)",
        f"A = AND8[A * 256 + {x}]; fZ = A == 0; fN = false; fH = true; fC = false",
        f"A = XOR8[A * 256 + {x}]; fZ = A == 0; fN = false; fH = false; fC = false",
        f"A = OR8[A * 256 + {x}]; fZ = A == 0; fN = false; fH = false; fC = false",
        f"cp8({x})",
    ][y]


def base_ops():
    ops = {}

    def op(code, body):
        assert code not in ops, hex(code)
        ops[code] = body

    # ---- 0x00-0x3F ----
    op(0x00, "return 4")
    op(0x08, "local a = imm16(); wr(a, SP % 256); wr((a + 1) % 65536, (SP - SP % 256) / 256); return 20")
    op(0x10, "imm8(); stop(); return 4")  # STOP: CGB speed switch if armed, else a 2-byte NOP
    op(0x18, f"local e = imm8(); {SIGNED}; PC = (PC + e) % 65536; return 12")
    for i, cond in enumerate(CONDS):
        op(0x20 + i * 8, f"local e = imm8(); if {cond} then {SIGNED}; PC = (PC + e) % 65536; return 12 end; return 8")

    for p, pair in enumerate(PAIRS):
        if pair:
            hi, lo = pair
            op(0x01 + p * 16, f"{lo} = imm8(); {hi} = imm8(); return 12")
            op(0x03 + p * 16, f"if {lo} == 255 then {lo} = 0; {hi} = ({hi} + 1) % 256 else {lo} = {lo} + 1 end; return 8")
            op(0x0B + p * 16, f"if {lo} == 0 then {lo} = 255; {hi} = ({hi} + 255) % 256 else {lo} = {lo} - 1 end; return 8")
            op(0x09 + p * 16, f"addhl({hi} * 256 + {lo}); return 8")
        else:
            op(0x31, "SP = imm16(); return 12")
            op(0x33, "SP = (SP + 1) % 65536; return 8")
            op(0x3B, "SP = (SP + 65535) % 65536; return 8")
            op(0x39, "addhl(SP); return 8")

    op(0x02, "wr(B * 256 + C, A); return 8")
    op(0x12, "wr(D * 256 + E, A); return 8")
    op(0x22, f"wr({HL}, A); {INC_HL}; return 8")
    op(0x32, f"wr({HL}, A); {DEC_HL}; return 8")
    op(0x0A, "A = rd(B * 256 + C); return 8")
    op(0x1A, "A = rd(D * 256 + E); return 8")
    op(0x2A, f"A = rd({HL}); {INC_HL}; return 8")
    op(0x3A, f"A = rd({HL}); {DEC_HL}; return 8")

    for y, r in enumerate(REGS):
        if r:
            op(0x04 + y * 8, f"{r} = inc8({r}); return 4")
            op(0x05 + y * 8, f"{r} = dec8({r}); return 4")
            op(0x06 + y * 8, f"{r} = imm8(); return 8")
        else:
            op(0x34, f"local a = {HL}; wr(a, inc8(rd(a))); return 12")
            op(0x35, f"local a = {HL}; wr(a, dec8(rd(a))); return 12")
            op(0x36, f"wr({HL}, imm8()); return 12")

    op(0x07, "A = rlc(A); fZ = false; return 4")
    op(0x0F, "A = rrc(A); fZ = false; return 4")
    op(0x17, "A = rl(A); fZ = false; return 4")
    op(0x1F, "A = rr(A); fZ = false; return 4")
    op(0x27, "daa(); return 4")
    op(0x2F, "A = 255 - A; fN = true; fH = true; return 4")
    op(0x37, "fN = false; fH = false; fC = true; return 4")
    op(0x3F, "fN = false; fH = false; fC = not fC; return 4")

    # ---- 0x40-0x7F: LD r, r' ----
    for y in range(8):
        for z in range(8):
            code = 0x40 + y * 8 + z
            if code == 0x76:
                # HALT. If an interrupt is already pending with IME=0, the "halt bug" makes
                # the CPU fail to increment PC: the next opcode runs with its own byte
                # re-read as the first operand. Emulated by running it without advancing PC.
                op(code, "if ime or AND8[IE * 256 + IF] % 32 == 0 then halted = true; "
                         "nextEvent = cycles; return 4 end; "
                         "return 4 + ops[rd(PC)]()")
            elif REGS[y] and REGS[z]:
                op(code, "return 4" if y == z else f"{REGS[y]} = {REGS[z]}; return 4")
            elif REGS[y]:
                op(code, f"{REGS[y]} = rd({HL}); return 8")
            else:
                op(code, f"wr({HL}, {REGS[z]}); return 8")

    # ---- 0x80-0xBF: ALU A, r ----
    for y in range(8):
        for z in range(8):
            if REGS[z]:
                op(0x80 + y * 8 + z, f"{alu(y, REGS[z])}; return 4")
            else:
                op(0x80 + y * 8 + z, f"local v = rd({HL}); {alu(y, 'v')}; return 8")

    # ---- 0xC0-0xFF ----
    for i, cond in enumerate(CONDS):
        base = 0xC0 + i * 8
        op(base + 0x0, f"if {cond} then PC = pop16(); return 20 end; return 8")            # RET cc
        op(base + 0x2, f"local a = imm16(); if {cond} then PC = a; return 16 end; return 12")  # JP cc
        op(base + 0x4, f"local a = imm16(); if {cond} then push16(PC); PC = a; return 24 end; return 12")  # CALL cc
    for p, pair in enumerate(PAIRS):
        code = 0xC1 + p * 16
        if pair:
            hi, lo = pair
            op(code, f"{lo} = rd(SP); {hi} = rd((SP + 1) % 65536); SP = (SP + 2) % 65536; return 12")
            op(code + 4, f"push16({hi} * 256 + {lo}); return 16")
        else:
            op(0xF1, "local f = rd(SP); A = rd((SP + 1) % 65536); SP = (SP + 2) % 65536; "
                     "fZ = f >= 128; fN = f % 128 >= 64; fH = f % 64 >= 32; fC = f % 32 >= 16; return 12")
            op(0xF5, "push16(A * 256 + (fZ and 128 or 0) + (fN and 64 or 0) + (fH and 32 or 0) + (fC and 16 or 0)); return 16")
    for y in range(8):
        op(0xC6 + y * 8, f"local v = imm8(); {alu(y, 'v')}; return 8")
        op(0xC7 + y * 8, f"push16(PC); PC = {y * 8:#04x}; return 16")  # RST

    op(0xC3, "PC = imm16(); return 16")
    op(0xC9, "PC = pop16(); return 16")
    op(0xCB, "return cb[imm8()]()")
    op(0xCD, "local a = imm16(); push16(PC); PC = a; return 24")
    op(0xD9, "PC = pop16(); ime = true; eiStage = 0; nextEvent = cycles; return 16")  # RETI
    op(0xE0, "wr(0xFF00 + imm8(), A); return 12")
    op(0xF0, "A = rd(0xFF00 + imm8()); return 12")
    op(0xE2, "wr(0xFF00 + C, A); return 8")
    op(0xF2, "A = rd(0xFF00 + C); return 8")
    op(0xEA, "wr(imm16(), A); return 16")
    op(0xFA, "A = rd(imm16()); return 16")
    op(0xE8, "local u = imm8(); local e = u; if e >= 128 then e = e - 256 end; "
             "fZ = false; fN = false; fH = (SP % 16) + (u % 16) > 15; fC = (SP % 256) + u > 255; "
             "SP = (SP + e) % 65536; return 16")
    op(0xF8, "local u = imm8(); local e = u; if e >= 128 then e = e - 256 end; "
             "fZ = false; fN = false; fH = (SP % 16) + (u % 16) > 15; fC = (SP % 256) + u > 255; "
             "local r = (SP + e) % 65536; H = (r - r % 256) / 256; L = r % 256; return 12")
    op(0xE9, f"PC = {HL}; return 4")
    op(0xF9, f"SP = {HL}; return 8")
    op(0xF3, "ime = false; eiStage = 0; return 4")
    op(0xFB, "if not ime and eiStage == 0 then eiStage = 1; nextEvent = cycles end; return 4")
    for code in (0xD3, 0xDB, 0xDD, 0xE3, 0xE4, 0xEB, 0xEC, 0xED, 0xF4, 0xFC, 0xFD):
        op(code, "locked = true; halted = true; return 4")  # illegal opcode: CPU hangs

    missing = [hex(c) for c in range(256) if c not in ops]
    assert not missing, missing
    return ops


def cb_ops():
    ops = {}
    rot = ["rlc", "rrc", "rl", "rr", "sla", "sra", "swap", "srl"]
    for code in range(256):
        x, y, z = code >> 6, (code >> 3) & 7, code & 7
        r = REGS[z]
        m = 1 << y
        if x == 0:
            ops[code] = f"{r} = {rot[y]}({r}); return 8" if r else \
                f"local a = {HL}; wr(a, {rot[y]}(rd(a))); return 16"
        elif x == 1:  # BIT y, r
            src = r or "v"
            pre = "" if r else f"local v = rd({HL}); "
            ops[code] = f"{pre}fZ = (({src} - {src} % {m}) / {m}) % 2 == 0; fN = false; fH = true; return {8 if r else 12}"
        elif x == 2:  # RES y, r
            ops[code] = f"{r} = AND8[{r} * 256 + {255 - m}]; return 8" if r else \
                f"local a = {HL}; wr(a, AND8[rd(a) * 256 + {255 - m}]); return 16"
        else:  # SET y, r
            ops[code] = f"{r} = OR8[{r} * 256 + {m}]; return 8" if r else \
                f"local a = {HL}; wr(a, OR8[rd(a) * 256 + {m}]); return 16"
    return ops


def emit(table, ops):
    return "\n".join(f"    {table}[0x{c:02X}] = function() {ops[c]} end" for c in range(256))


def main():
    template = TEMPLATE.read_text(encoding="utf-8")
    code = emit("ops", base_ops()) + "\n\n" + emit("cb", cb_ops())
    out = template.replace("--@@OPS@@", code).replace(
        "--@@HEADER@@", "-- GENERATED by tools/gen_core.py from src/Core.template.lua - do not edit.")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(out, encoding="utf-8", newline="\n")
    print(f"wrote {OUTPUT} ({len(out):,} bytes)")


if __name__ == "__main__":
    main()
