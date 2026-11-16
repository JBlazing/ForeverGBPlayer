"""Run test ROMs on GBCore under real Lua 5.1 (lupa) and report pass/fail.

Blargg's test ROMs print their result over the serial port, so no PPU is needed:
we run until the serial output contains "Passed" or "Failed" (or a time limit).

    py tools/gen_core.py && py tools/test_cpu.py testroms/blargg/cpu_instrs/individual/*.gb

Also reports emulation speed (x real time). This is plain Lua 5.1 on this PC; WoW's
Lua is also 5.1 but runs alongside the game, so treat in-game numbers as the real ones.
"""
import argparse
import pathlib
import sys
import tempfile
import time

from lupa import lua51

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import rom2lua  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
CORE = ROOT / "ForeverGBPlayer" / "core" / "Core.lua"
FPS = 4194304 / 70224  # ~59.73


def run_rom(path, max_seconds, verbose):
    with tempfile.TemporaryDirectory() as tmp:
        out, name, _, _ = rom2lua.convert(path, "testrom", pathlib.Path(tmp))
        rom_src = out.read_text(encoding="ascii")

    lua = lua51.LuaRuntime(unpack_returned_tuples=True)
    loadstring = lua.eval("loadstring")
    # Core alone (no addon): a minimal stand-in for the addon's RegisterRom API.
    lua.execute("ForeverGBPlayer = { RegisterRom = function(rom) GBRomLibrary = GBRomLibrary or {}; "
                "GBRomLibrary[rom.name] = rom; return true end }")
    for src, label in ((CORE.read_text(encoding="utf-8"), "@Core.lua"), (rom_src, "@rom.lua")):
        chunk = loadstring(src, label)
        if chunk is None:
            raise SystemExit(f"Lua syntax error in {label}")
        chunk()

    new = lua.eval("function(name) local c, e = GBCore.New(GBRomLibrary[name]); return c, e end")
    core, err = new(name)
    if core is None:
        return "ERROR", err, 0, 0
    run = lua.eval("function(core, n) for i = 1, n do core.RunFrame() end end")

    status, emu_s, t0 = "TIMEOUT", 0.0, time.perf_counter()
    while emu_s < max_seconds:
        run(core, 60)
        emu_s += 60 / FPS
        serial = core.GetSerial()
        if "Passed" in serial:
            status = "PASS"
            break
        if "Failed" in serial:
            status = "FAIL"
            break
        if core.IsLocked():
            status = "LOCKED"
            break
    wall = time.perf_counter() - t0
    serial = core.GetSerial()
    if verbose or status != "PASS":
        regs = core.GetRegs()
        print(f"    serial: {serial.strip()!r}")
        print(f"    regs: PC={regs.PC:04X} SP={regs.SP:04X} A={regs.A:02X} F={regs.F:02X} "
              f"halted={regs.halted} ime={regs.ime}")
    return status, serial, emu_s, wall


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("roms", nargs="+", type=pathlib.Path)
    ap.add_argument("--max-seconds", type=float, default=120, help="emulated seconds before giving up")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    results = []
    for rom in args.roms:
        print(f"{rom.name} ...", flush=True)
        status, _, emu_s, wall = run_rom(rom, args.max_seconds, args.verbose)
        speed = emu_s / wall if wall else 0
        print(f"  {status:7} {emu_s:6.1f}s emulated in {wall:6.1f}s wall  ({speed:.2f}x real time)")
        results.append((rom.name, status, speed))

    passed = sum(1 for _, s, _ in results if s == "PASS")
    print(f"\n{passed}/{len(results)} passed")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
