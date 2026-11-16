"""Render a ROM on GBCore under Lua 5.1 and compare the frame with a reference image.

    py tools/test_ppu.py testroms/acid2/dmg-acid2.gb testroms/acid2/reference-dmg.png

Writes <out>/<rom>.png: our frame next to the reference (and a diff, red = mismatch),
scaled 3x. Reference greys map to shades by brightness (lightest = 0). Also reports the
emulation speed with the PPU running.
"""
import argparse
import pathlib
import sys
import tempfile
import time

from lupa import lua51
from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import rom2lua  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
CORE = ROOT / "ForeverGBPlayer" / "core" / "Core.lua"
GREYS = [(224, 248, 208), (136, 192, 112), (52, 104, 86), (8, 24, 32)]  # same as the addon


def boot(rom_path):
    with tempfile.TemporaryDirectory() as tmp:
        out, name, _, _ = rom2lua.convert(rom_path, "testrom", pathlib.Path(tmp))
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
    core, err = lua.eval("function(n) local c, e = GBCore.New(GBRomLibrary[n]); return c, e end")(name)
    if core is None:
        raise SystemExit(err)
    return lua, core


def frame_shades(lua, core):
    """The core's framebuffer: shades 0..3 (DMG) or RGB555 ints (CGB)."""
    dump = lua.eval("function(fb) local t = {} for i = 1, 23040 do t[i] = fb[i] end "
                    "return table.concat(t, ',') end")
    return [int(c) for c in dump(core.fb).split(",")]


def rgb555_to_rgb(v):
    return tuple(round(((v >> s) & 31) * 255 / 31) for s in (0, 5, 10))


def reference_rgb555(path):
    """Colour reference -> RGB555 ints (references store 5-bit channels as round(c*255/31))."""
    im = Image.open(path).convert("RGB")
    if im.size != (160, 144):
        raise SystemExit(f"reference must be 160x144, got {im.size}")
    b = im.tobytes()
    out = []
    for i in range(0, len(b), 3):
        r, g, bl = (round(c * 31 / 255) for c in b[i:i + 3])
        out.append(r | (g << 5) | (bl << 10))
    return out


def reference_shades(path):
    im = Image.open(path).convert("L")
    if im.size != (160, 144):
        raise SystemExit(f"reference must be 160x144, got {im.size}")
    pixels = list(im.tobytes())
    levels = sorted(set(pixels), reverse=True)
    if len(levels) > 4:
        raise SystemExit(f"reference has {len(levels)} grey levels, expected <= 4")
    # map brightness rank to shade; a reference with fewer than 4 greys uses the
    # standard 255/170/85/0 spacing so the ranks still line up
    std = {255: 0, 170: 1, 85: 2, 0: 3}
    return [std.get(p, levels.index(p)) for p in pixels]


def to_image(values, cgb=False):
    im = Image.new("RGB", (160, 144))
    im.putdata([rgb555_to_rgb(v) for v in values] if cgb else [GREYS[s] for s in values])
    return im


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rom", type=pathlib.Path)
    ap.add_argument("reference", type=pathlib.Path, nargs="?")
    ap.add_argument("--frames", type=int, default=60)
    ap.add_argument("--out", type=pathlib.Path, default=ROOT / "testroms" / "out")
    args = ap.parse_args()

    lua, core = boot(args.rom)
    run = lua.eval("function(core, n) for i = 1, n do core.RunFrame() end end")
    t0 = time.perf_counter()
    run(core, args.frames)
    wall = time.perf_counter() - t0
    ours = frame_shades(lua, core)
    emu_s = args.frames * 70224 / 4194304
    print(f"{args.rom.name}: {args.frames} frames in {wall:.2f}s wall "
          f"({emu_s / wall:.2f}x real time, {wall / args.frames * 1000:.2f} ms/frame)")

    cgb = bool(core.cgb)
    print(f"  mode: {'CGB (colour)' if cgb else 'DMG'}")
    panels = [to_image(ours, cgb)]
    ok = True
    if args.reference:
        ref = reference_rgb555(args.reference) if cgb else reference_shades(args.reference)
        bad = [i for i in range(23040) if ours[i] != ref[i]]
        ok = not bad
        print(f"  vs {args.reference.name}: {'MATCH' if ok else f'{len(bad)} pixels differ'}")
        if bad:
            rows = sorted({i // 160 for i in bad})
            print(f"  mismatched rows: {rows[:20]}{' ...' if len(rows) > 20 else ''}")
        diff = Image.new("RGB", (160, 144))
        bad_set = set(bad)
        ref_rgb = [rgb555_to_rgb(v) for v in ref] if cgb else [GREYS[s] for s in ref]
        diff.putdata([(255, 0, 0) if i in bad_set else ref_rgb[i] for i in range(23040)])
        panels += [to_image(ref, cgb), diff]

    sheet = Image.new("RGB", (160 * len(panels) + 8 * (len(panels) - 1), 144), (40, 40, 40))
    for i, p in enumerate(panels):
        sheet.paste(p, (i * 168, 0))
    sheet = sheet.resize((sheet.width * 3, sheet.height * 3), Image.NEAREST)
    args.out.mkdir(parents=True, exist_ok=True)
    out = args.out / (args.rom.stem + ".png")
    sheet.save(out)
    print(f"  wrote {out}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
