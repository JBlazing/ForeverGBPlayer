"""Joypad test: drive core.SetButton against testroms/joypad/joypad-test.gb and check
what the ROM itself read from FF00 and how many joypad interrupts it took.

    py tools/make_joypad_test.py && py tools/test_joypad.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from test_ppu import boot  # noqa: E402

ROM = pathlib.Path(__file__).resolve().parent.parent / "testroms" / "joypad" / "joypad-test.gb"

# (action, expected $C000 d-pad read, $C001 button read, $C002 interrupt count)
STEPS = [
    ("nothing pressed",   [],                                0xEF, 0xDF, 0),
    ("press up",          [("up", True)],                    0xEB, 0xDF, 1),
    ("press start",       [("start", True)],                 0xEB, 0xD7, 2),
    ("release both",      [("up", False), ("start", False)], 0xEB, 0xD7, 2),  # no IRQ on release
    ("press a",           [("a", True)],                     0xEF, 0xDE, 3),
    ("hold a, press a",   [("a", True)],                     0xEF, 0xDE, 3),  # no repeat IRQ
    ("press left+right",  [("left", True), ("right", True)], 0xEC, 0xDE, 4),
]


def main():
    if not ROM.exists():
        raise SystemExit("run tools/make_joypad_test.py first")
    lua, core = boot(ROM)
    failed = 0
    for label, presses, exp0, exp1, exp2 in STEPS:
        for name, down in presses:
            core.SetButton(name, down)
        core.RunFrame()
        got = (core.Read(0xC000), core.Read(0xC001), core.Read(0xC002))
        ok = got == (exp0, exp1, exp2)
        failed += not ok
        print(f"  {'ok  ' if ok else 'FAIL'} {label:18} C000={got[0]:02X} C001={got[1]:02X} C002={got[2]}"
              + ("" if ok else f"   expected {exp0:02X} {exp1:02X} {exp2}"))
    print("joypad:", "PASS" if not failed else f"{failed} step(s) failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
