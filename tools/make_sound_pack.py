"""Generate the sample packs the addon plays for the Game Boy's sound channels.

WoW addons can only play sound files (no synthesis, pitch or per-sound volume), so
sounds are pre-rendered. Everything goes under ForeverGBPlayer/sound/:

  sq/sq{duty}_{midi}_{L}.ogg          channels 1+2, constant volume (2 s; restarted to sustain)
  sq/sqd{duty}_{midi}_{L}_{pace}.ogg  channels 1+2, volume envelope baked in: starts at level L
                                      and steps down every pace/64 s like the hardware, so a
                                      fading note plays start-to-end with no restarts
  noise/n{nr43}_{L}.ogg               channel 4, every NR43 setting (1 s; real LFSR sequence)
  wave/wtri_{midi}_{L}.ogg            channel 3 fallback waveform (triangle); per-game wave
                                      packs come from tools/make_wave_pack.py

  duty  : 25 / 50 (12.5% and 75% are approximated by 25%; 75% is 25% inverted)
  midi  : squares 36-107 (C2-B7), wave 24-95 (C1-B6) - GB frequencies snap to semitones
  L     : squares/noise 1-4 = GB volume 3 / 7 / 11 / 15; wave 1-3 = 25% / 50% / 100%

Tones are band-limited (additive synthesis below Nyquist) and DC-free like the GB output;
2 ms attack ramp, 10 ms release ramp.

    py -m pip install numpy soundfile
    py tools/make_sound_pack.py
"""
import pathlib
import time

import numpy as np
import soundfile as sf

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "ForeverGBPlayer" / "sound"

SR = 44100
PEAK = 0.6                            # amplitude of a full-scale (volume 15) channel
DUTIES = {"25": 0.25, "50": 0.5}
SQ_MIDI = range(36, 108)
WAVE_MIDI = range(24, 96)
LEVELS = {1: 3, 2: 7, 3: 11, 4: 15}   # square/noise level -> representative GB volume
WAVE_LEVELS = {1: 0.25, 2: 0.5, 3: 1.0}
PACES = range(1, 8)
TRIANGLE = "0123456789ABCDEFFEDCBA9876543210"
NOISE_DIV = [8, 16, 32, 48, 64, 80, 96, 112]


def midi_hz(m):
    return 440 * 2 ** ((m - 69) / 12)


def ramps(x):
    a, r = int(SR * 0.002), int(SR * 0.010)
    x[:a] *= np.linspace(0, 1, a)
    x[-r:] *= np.linspace(1, 0, r)
    return x


def write(path, x):
    sf.write(path, x.astype(np.float32), SR, format="OGG", subtype="VORBIS")
    return path.stat().st_size


def pulse(freq, duty, n):
    """Band-limited DC-free pulse: sum (2/(pi k)) sin(pi k d) cos(2 pi k f t - pi k d)."""
    t = np.arange(n) / SR
    out = np.zeros(n)
    for k in range(1, int((SR / 2 - 500) // freq) + 1):
        out += (2 / (np.pi * k)) * np.sin(np.pi * k * duty) * np.cos(2 * np.pi * k * freq * t - np.pi * k * duty)
    return out


def wave_tone(pattern_hex, freq, n):
    """Band-limited tone from a 32-step 4-bit wave RAM pattern (one period = 32 steps)."""
    s = np.array([int(c, 16) for c in pattern_hex], float) / 15
    s -= s.mean()
    X = np.fft.fft(s)
    t = np.arange(n) / SR
    out = np.zeros(n)
    for k in range(1, int((SR / 2 - 500) // freq) + 1):
        # staircase (zero-order hold) spectrum: DFT bin * sinc, delayed half a step
        c = X[k % 32] * np.sinc(k / 32) * np.exp(-1j * np.pi * k / 32) / 32
        if abs(c) > 1e-9:
            out += 2 * abs(c) * np.cos(2 * np.pi * k * freq * t + np.angle(c))
    return out


def envelope(vol0, pace, n):
    """GB volume envelope (decreasing): vol0 - floor(t * 64 / pace), as gain 0..1."""
    t = np.arange(n) / SR
    return np.maximum(0, vol0 - np.floor(t * 64 / pace)) / 15


_LFSR = {}


def lfsr_bits(width7):
    """One period of the noise LFSR output (1 = high), 7-bit or 15-bit mode."""
    if width7 not in _LFSR:
        lfsr, bits = 0x7FFF, []
        period = 127 if width7 else 32767
        for i in range(period + 300):
            x = (lfsr ^ (lfsr >> 1)) & 1
            lfsr = (lfsr >> 1) | (x << 14)
            if width7:
                lfsr = (lfsr & ~0x40) | (x << 6)
            if i >= 300:  # skip the start-up transient
                bits.append(0 if lfsr & 1 else 1)
        _LFSR[width7] = np.array(bits, float)
    return _LFSR[width7]


def noise(nr43, n):
    """Noise channel output for an NR43 value, box-filtered from the LFSR clock to SR."""
    shift, width7, r = nr43 >> 4, bool(nr43 & 8), nr43 & 7
    fc = 4194304 / (NOISE_DIV[r] * 2 ** shift)  # LFSR clocks per second
    bits = lfsr_bits(width7)
    P = len(bits)
    cum = np.concatenate([[0], np.cumsum(bits)])
    total = cum[-1]
    edges = np.floor(np.arange(n + 1) * fc / SR).astype(np.int64)

    def C(x):  # number of high bits among clocks [0, x)
        return (x // P) * total + cum[x % P]

    a, b = edges[:-1], edges[1:]
    span = b - a
    out = np.where(span > 0, (C(b) - C(a)) / np.maximum(span, 1), bits[a % P])
    return out - bits.mean()


def main():
    t0, size, count = time.perf_counter(), 0, 0
    for sub in ("sq", "noise", "wave"):
        (OUT / sub).mkdir(parents=True, exist_ok=True)

    sustain_n = int(SR * 2.0)
    for dname, duty in DUTIES.items():
        for m in SQ_MIDI:
            longest = int(SR * (15 * 7 / 64 + 0.05))
            base = pulse(midi_hz(m), duty, max(sustain_n, longest))
            for L, vol in LEVELS.items():
                size += write(OUT / "sq" / f"sq{dname}_{m}_{L}.ogg", ramps(base[:sustain_n] * PEAK * vol / 15))
                count += 1
                for pace in PACES:
                    n = int(SR * (vol * pace / 64 + 0.02))
                    x = base[:n] * PEAK * envelope(vol, pace, n)
                    size += write(OUT / "sq" / f"sqd{dname}_{m}_{L}_{pace}.ogg", ramps(x))
                    count += 1

    noise_n = int(SR * 1.0)
    for nr43 in range(256):
        if nr43 >> 4 >= 14:
            continue  # shift 14/15: the LFSR isn't clocked, channel is silent
        x = noise(nr43, noise_n)
        for L, vol in LEVELS.items():
            size += write(OUT / "noise" / f"n{nr43}_{L}.ogg", ramps(x * PEAK * vol / 15))
            count += 1

    count_w, size_w = write_wave_set(TRIANGLE, "tri")
    count, size = count + count_w, size + size_w

    # The .toc loads sound\waves.lua; per-game wave packs (make_wave_pack.py) add to it.
    manifest = OUT / "waves.lua"
    if not manifest.exists():
        manifest.write_text("-- Generated by tools/make_wave_pack.py: wave RAM pattern (hex) -> sample set id.\n"
                            "GBSoundWaves = GBSoundWaves or {}\n", encoding="ascii", newline="\n")
    print(f"wrote {count} files to {OUT} ({size / 1e6:.1f} MB) in {time.perf_counter() - t0:.0f}s")


def write_wave_set(pattern_hex, wave_id):
    n = int(SR * 2.0)
    count = size = 0
    for m in WAVE_MIDI:
        base = wave_tone(pattern_hex, midi_hz(m), n)
        for L, gain in WAVE_LEVELS.items():
            size += write(OUT / "wave" / f"w{wave_id}_{m}_{L}.ogg", ramps(base * PEAK * gain))
            count += 1
    return count, size


if __name__ == "__main__":
    main()
