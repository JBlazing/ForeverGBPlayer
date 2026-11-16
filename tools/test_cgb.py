"""Checks for CGB double speed, DMA, WRAM banking and battery-save round trips.

    py tools/make_cgb_tests.py && py tools/test_cgb.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from make_cgb_tests import DATA  # noqa: E402
from test_ppu import boot  # noqa: E402

DIR = pathlib.Path(__file__).resolve().parent.parent / "testroms" / "cgb"
failures = []


def check(label, cond, detail=""):
    print(f"  {'ok  ' if cond else 'FAIL'} {label}{('  ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


def cgb_test():
    print("cgb-test.gbc")
    lua, core = boot(DIR / "cgb-test.gbc")
    for _ in range(10):
        core.RunFrame()
    rd = core.Read
    check("ran to completion", rd(0xC00A) == 0x5A)
    check("CGB mode", bool(core.cgb))
    normal = rd(0xC000) | rd(0xC001) << 8
    double = rd(0xC002) | rd(0xC003) << 8
    ratio = double / normal if normal else 0
    check("double speed: twice the CPU work per frame", 1.95 <= ratio <= 2.05,
          f"{normal} -> {double} loops ({ratio:.3f}x)")
    check("KEY1 reads 0xFE after switch", rd(0xC004) == 0xFE, f"{rd(0xC004):02X}")
    check("core reports double speed", bool(core.IsDoubleSpeed()))
    gdma = bytes(core.ReadVRAM(0, 0x8000 + i) for i in range(32))
    check("general DMA copied 32 bytes to VRAM bank 0", gdma == DATA[:32])
    hdma = bytes(core.ReadVRAM(1, 0x8100 + i) for i in range(32))
    check("HBlank DMA copied 32 bytes to VRAM bank 1", hdma == DATA[32:])
    check("bank 0 untouched at 0x8100", core.ReadVRAM(0, 0x8100) == 0)
    check("FF55 while HBlank DMA pending", rd(0xC005) in (0x01, 0x00), f"{rd(0xC005):02X}")
    check("FF55 = 0xFF when done", rd(0xC006) == 0xFF, f"{rd(0xC006):02X}")
    check("WRAM bank 1 / 2 keep separate data", (rd(0xC007), rd(0xC008)) == (0x11, 0x22))
    check("FF70 reads back bank", rd(0xC009) == 0xFA, f"{rd(0xC009):02X}")


def save_test():
    print("save-test.gb")
    lua, core = boot(DIR / "save-test.gb")
    check("battery cart detected", bool(core.hasBattery))
    check("not dirty before running", not core.IsSaveDirty())
    for _ in range(5):
        core.RunFrame()
    check("dirty after the game writes RAM", bool(core.IsSaveDirty()))
    save1 = core.GetSaveRAM()
    check("save is 32 KB as hex", len(save1) == 65536)
    b0, b2 = int(save1[0:2], 16), int(save1[2 * 0x4000:2 * 0x4000 + 2], 16)
    check("boot 1: bank 0 = 00, bank 2 = 02", (b0, b2) == (0x00, 0x02), f"{b0:02X} {b2:02X}")

    lua, core2 = boot(DIR / "save-test.gb")  # "reload": brand new runtime
    check("LoadSaveRAM accepts it", bool(core2.LoadSaveRAM(save1)))
    check("rejects garbage", not core2.LoadSaveRAM("zz"))
    for _ in range(5):
        core2.RunFrame()
    save2 = core2.GetSaveRAM()
    b0, b2 = int(save2[0:2], 16), int(save2[2 * 0x4000:2 * 0x4000 + 2], 16)
    check("boot 2 continues from the save: 01 / 05", (b0, b2) == (0x01, 0x05), f"{b0:02X} {b2:02X}")
    check("game sees loaded value", core2.Read(0xC000) == 0x01)


if __name__ == "__main__":
    cgb_test()
    save_test()
    print("cgb/save:", "PASS" if not failures else f"{len(failures)} failed: {failures}")
    sys.exit(1 if failures else 0)
