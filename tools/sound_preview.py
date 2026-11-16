"""Preview what the addon's sound player will produce, without WoW.

Runs the real addon (core + SoundUpdate + frame pacing) under the harness mock at
60 fps, logs every PlaySoundFile/StopSound call, then mixes the requested OGG files
into a WAV exactly as logged (stops are abrupt unless a fade was set, like WoW).
This is a best case: WoW adds its own start latency and jitter on top.

    py tools/sound_preview.py "path/to/game.gb" --seconds 30 --start-at 2.7
"""
import argparse
import pathlib
import sys
import tempfile

import numpy as np
import soundfile as sf
from lupa import lua51

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import harness  # noqa: E402
import rom2lua  # noqa: E402

SR = 44100


def scripted_input(core, f, start_f):
    """Simple play-through: press Start, then hold right and jump every 1.5 s."""
    if f == start_f:
        core.SetButton("start", True)
    elif f == start_f + 6:
        core.SetButton("start", False)
    elif f == start_f + 120:
        core.SetButton("right", True)
    elif f > start_f + 120 and f % 90 == 0:
        core.SetButton("a", True)
    elif f > start_f + 120 and f % 90 == 20:
        core.SetButton("a", False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rom", type=pathlib.Path)
    ap.add_argument("--seconds", type=float, default=30)
    ap.add_argument("--start-at", type=float, default=2.7, help="press Start at this time (s)")
    ap.add_argument("--fade", type=int, default=0, help="StopSound fade in ms (/fgb sound fade)")
    ap.add_argument("--mode", choices=["envelope", "steps"], default="envelope")
    ap.add_argument("--channels", default="1234")
    ap.add_argument("--out", type=pathlib.Path, default=harness.ROOT / "testroms" / "out")
    args = ap.parse_args()

    lua = lua51.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(harness.MOCK)
    waves = harness.ROOT / "ForeverGBPlayer" / "sound" / "waves.lua"
    for path in (harness.CORE, harness.ADDON, waves):  # .toc order
        if path.exists():
            lua.eval("loadstring")(path.read_text(encoding="utf-8"), "@" + path.name)("ForeverGBPlayer")
    with tempfile.TemporaryDirectory() as tmp:
        out, name, _, _ = rom2lua.convert(args.rom, "preview", pathlib.Path(tmp))
        lua.eval("loadstring")(out.read_text(encoding="ascii"), "@" + out.name)()
    g = lua.globals()
    slash = g.SlashCmdList.FOREVERGB
    slash("play " + name)
    if args.fade:
        slash(f"sound fade {args.fade}")
    slash(f"sound mode {args.mode}")
    slash(f"sound channels {args.channels}")
    core = g.ForeverGBPlayer.play.core
    t0 = g.MOCK_TIME

    frames = int(args.seconds * 60)
    start_f = int(args.start_at * 60)
    for f in range(frames):
        scripted_input(core, f, start_f)
        g.MOCK_TICK(1 / 60)
    slash("stop")

    # Mix the log.
    log = [dict(e.items()) for e in g.MOCK_SOUND_LOG.values()]
    starts, stops = {}, {}
    for e in log:
        if e["op"] == "play":
            starts[e["handle"]] = (e["t"] - t0, e["path"])
        else:
            stops[e["handle"]] = (e["t"] - t0, e["fade"])
    addon_dir = harness.ROOT / "ForeverGBPlayer"
    total = np.zeros(int(SR * (args.seconds + 2.5)))
    cache, missing = {}, set()
    for handle, (start, path) in starts.items():
        rel = path.split("\\AddOns\\ForeverGBPlayer\\", 1)[1].replace("\\", "/")
        f = addon_dir / rel
        if not f.exists():
            missing.add(rel)
            continue
        if rel not in cache:
            cache[rel], _ = sf.read(f)
        data = cache[rel].copy()
        if handle in stops:
            stop, fade = stops[handle]
            n = max(0, int((stop - start) * SR))
            fade_n = int(SR * fade / 1000)
            data = data[:n + fade_n]
            if fade_n and len(data) > n:
                data[n:] *= np.linspace(1, 0, len(data) - n)
        i = int(start * SR)
        total[i:i + len(data)] += data[:len(total) - i]

    args.out.mkdir(parents=True, exist_ok=True)
    suffix = f"{args.mode}{'' if args.channels == '1234' else '-ch' + args.channels}{f'-fade{args.fade}' if args.fade else ''}"
    wav = args.out / f"{args.rom.stem}-sound-{suffix}.wav"
    sf.write(wav, np.clip(total, -1, 1).astype(np.float32), SR)
    plays = len(starts)
    kinds = {"square": 0, "square (baked fade)": 0, "wave": 0, "noise": 0}
    for _, path in starts.values():
        name = path.rsplit("\\", 1)[1]
        kinds["square (baked fade)" if name.startswith("sqd") else "square" if name.startswith("sq")
              else "wave" if name.startswith("w") else "noise"] += 1
    print(f"{plays} sounds started in {args.seconds:.0f}s ({plays / args.seconds:.1f}/s), "
          f"{len(cache)} distinct files, peak {np.abs(total).max():.2f}")
    print("  by kind:", ", ".join(f"{k} {v / args.seconds:.1f}/s" for k, v in kinds.items()))
    print("missing files:", sorted(missing) or "none")
    print("wrote", wav)


if __name__ == "__main__":
    main()
