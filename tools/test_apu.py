"""Run Blargg's dmg_sound test ROMs on GBCore. They report via cartridge RAM:
A001-A003 = DE B0 61 signature, A000 = status (0x80 while running, 0 = passed),
A004.. = zero-terminated result text.

    py tools/test_apu.py testroms/blargg/dmg_sound/*.gb
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from test_ppu import boot  # noqa: E402


def run(path, max_frames=60 * 40):
    lua, core = boot(path)
    for frame in range(max_frames):
        core.RunFrame()
        if frame % 30 == 0:
            sig = [core.ReadCartRAM(i) for i in (1, 2, 3)]
            status = core.ReadCartRAM(0)
            if sig == [0xDE, 0xB0, 0x61] and status != 0x80:
                break
    sig = [core.ReadCartRAM(i) for i in (1, 2, 3)]
    status = core.ReadCartRAM(0)
    text = bytearray()
    for i in range(4, 0x1000):
        b = core.ReadCartRAM(i)
        if b in (0, 0xFF):
            break
        text.append(b)
    if sig != [0xDE, 0xB0, 0x61]:
        return "NO OUTPUT", ""
    if status == 0x80:
        return "TIMEOUT", text.decode("ascii", "replace")
    return ("PASS" if status == 0 else f"FAIL({status})"), text.decode("ascii", "replace")


# These need the exact sample position inside the wave buffer, which a sample-based
# player never uses (see README). Anything else failing is a regression.
KNOWN_FAILING = {"09-wave read while on.gb", "10-wave trigger while on.gb", "12-wave write while on.gb"}


def main():
    results, unexpected = [], []
    for p in map(pathlib.Path, sys.argv[1:]):
        status, text = run(p)
        results.append(status)
        detail = " | ".join(line for line in text.strip().splitlines()[1:] if line.strip())
        known = p.name in KNOWN_FAILING
        if (status == "PASS") == known:
            unexpected.append(p.name)
        print(f"  {status:9} {p.name:30} {'(known) ' if known and status != 'PASS' else ''}{detail[:80]}")
    print(f"{results.count('PASS')}/{len(results)} passed")
    if unexpected:
        print("Unexpected results (update KNOWN_FAILING if a known failure now passes):", unexpected)
        sys.exit(1)


if __name__ == "__main__":
    main()
