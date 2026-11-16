"""Build a tiny hand-assembled DMG test ROM for joypad input.

Program (IE = joypad only, so HALT sleeps until a button is pressed):
    0x0060  joypad ISR:  LD HL,$C002 / INC (HL) / RETI        ; count presses
    0x0150  LD A,$10 / LDH ($FF),A / EI
    loop:   LD A,$20 / LDH ($00),A / LDH A,($00) / LD ($C000),A   ; d-pad state
            LD A,$10 / LDH ($00),A / LDH A,($00) / LD ($C001),A   ; button state
            HALT / JR loop

So after each press: $C000 = d-pad read, $C001 = button read (active-low, 0xC0|select|bits),
$C002 = number of joypad interrupts taken.

    py tools/make_joypad_test.py      -> testroms/joypad/joypad-test.gb
"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "testroms" / "joypad" / "joypad-test.gb"

LOGO = bytes.fromhex(
    "CEED6666CC0D000B03730083000C000D0008111F8889000EDCCC6EE6DDDDD999"
    "BBBB67636E0EECCCDDDC999FBBB9333E"
)


def build():
    rom = bytearray(0x8000)
    rom[0x60:0x65] = bytes([0x21, 0x02, 0xC0, 0x34, 0xD9])  # LD HL,$C002; INC (HL); RETI
    rom[0x100:0x104] = bytes([0x00, 0xC3, 0x50, 0x01])        # NOP; JP $0150
    rom[0x104:0x134] = LOGO
    rom[0x134:0x143] = b"JOYPAD TEST".ljust(15, b"\0")
    # 0x147 cart type 0 (ROM only), 0x148 ROM size 0 (32 KB), 0x149 RAM 0

    main = [0x3E, 0x10, 0xE0, 0xFF, 0xFB]                      # LD A,$10; LDH ($FF),A; EI
    loop = [
        0x3E, 0x20, 0xE0, 0x00, 0xF0, 0x00, 0xEA, 0x00, 0xC0,  # d-pad -> $C000
        0x3E, 0x10, 0xE0, 0x00, 0xF0, 0x00, 0xEA, 0x01, 0xC0,  # buttons -> $C001
        0x76,                                                  # HALT
    ]
    jr = -(len(loop) + 2)
    loop += [0x18, jr & 0xFF]                                  # JR loop
    code = bytes(main + loop)
    rom[0x150:0x150 + len(code)] = code

    hdr = 0
    for b in rom[0x134:0x14D]:
        hdr = (hdr - b - 1) & 0xFF
    rom[0x14D] = hdr
    total = (sum(rom) - rom[0x14E] - rom[0x14F]) & 0xFFFF
    rom[0x14E], rom[0x14F] = total >> 8, total & 0xFF
    return bytes(rom)


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(build())
    print(f"wrote {OUT}")
