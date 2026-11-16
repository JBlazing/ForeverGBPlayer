# ForeverGBPlayer

A Game Boy and Game Boy Color emulator that runs inside World of Warcraft as an addon.
It covers the CPU, picture processor, input, battery saves and sample-based sound.
ROMs are installed as separate ROM pack addons. Type `/fgb play <rom>`; the old
`/gbspike` still works as an alias. It started as a rendering test, which is why the
renderer benchmark (`/fgb bench`) is still in here.

## Renderers

| name    | textures | per changed region                                        |
|---------|----------|------------------------------------------------------------|
| `atlas` | 5,760    | `SetTexCoord` into a 64x64 atlas of all 256 four-pixel patterns |
| `pixel` | 23,040   | `SetColorTexture` per 1x1 pixel                             |

Both only touch regions that changed since the last frame (`/fgb force` disables that).

## Install & run

1. Copy or symlink the `ForeverGBPlayer/` folder into `World of Warcraft/<flavor>/Interface/AddOns/`.
   - Symlink (admin PowerShell): `New-Item -ItemType SymbolicLink -Path "<AddOns>\ForeverGBPlayer" -Target "<repo>\ForeverGBPlayer"`
2. The `.toc` files target Interface 16001 (Camelot) and 20506 (TBC). Add or adjust one for other clients.
3. In game: `/fgb bench`, then stand still in a quiet area for ~40 s. Then
   `/fgb bench` again in a busy area (e.g. a capital city) for comparison.

Other commands: `/fgb help`.

## What to look at

- **render ms**: Lua plus C API time spent pushing the frame. An emulator also needs
  roughly 8-12 ms per frame for the CPU core, so rendering should stay well under ~4 ms.
- **fps vs the `none/static` baseline**: catches costs `debugprofilestop` can't see,
  i.e. the engine laying out and drawing thousands of textures.
- **Visual check**: run `/fgb atlas` + `/fgb scroll` and look for seams, blur or
  bleed between segments, at `/fgb scale 2`, `3` and `4`.
- `sprites` is the realistic case (most of a Game Boy frame is unchanged); `scroll` /
  `+force` are the worst case (full-screen scrolling).

## ROMs

Addons can't read files, so each ROM ships as its own small **ROM pack addon** that depends on
ForeverGBPlayer and registers the ROM while the game starts:

```
AddOns\ForeverGBPlayer_Rom_<name>\
    ForeverGBPlayer_Rom_<name>.toc   (+ _Camelot, _TBC)   ## Dependencies: ForeverGBPlayer
    <name>.lua                      local rom = {...}; ForeverGBPlayer.RegisterRom(rom, ...)
```

Make packs either way. Both produce byte-identical output:
- **In the browser:** `tools/rom-converter.html`. It's also published as a private artifact, and it downloads a zip of pack folders.
- **On the command line:** `py tools/rom2lua.py game.gb [more.gbc ...] [--name NAME] [--out-dir <AddOns folder>]`.
  The default output folder is `rom-addons/`, which is gitignored.

Restart WoW after adding a pack, because `/reload` doesn't pick up new addon folders. Turn packs on or off in the AddOns list.

**API** (in `ForeverGBPlayer.lua`). Other addons can use it too:

| Call | Returns |
|---|---|
| `ForeverGBPlayer.API_VERSION` | `1` |
| `ForeverGBPlayer.RegisterRom(rom, sourceAddon)` | `true`, or `false, message` |
| `ForeverGBPlayer.GetRom(name)` | ROM table or `nil` |
| `ForeverGBPlayer.ListRoms()` | sorted names |

`RegisterRom` refuses invalid names and truncated or missing banks, plus a different ROM under a name that's already taken.
Registering the same ROM twice is accepted. A pack loaded without ForeverGBPlayer prints a message instead of erroring.

**ROM table:** `name, title, size, sha1, cartType, cartName, cgbFlag, cgb, ramSize, numBanks, banks`.
Each 16 KB bank is one Lua string. The byte at address `A` is `string.byte(rom.banks[floor(A/0x4000)], A % 0x4000 + 1)`.

**Accepted files:** `.gb` and `.gbc`. `.gba` is rejected because it's a different console with an ARM CPU.

In game: `/fgb roms` recomputes the checksums from the loaded data. `/fgb logo` draws the
header's Nintendo logo. `/fgb tiles <rom> 0x4350` shows the bytes as 2bpp tiles.
Both views go through the renderer.

## CPU core

`ForeverGBPlayer/core/Core.lua` is **generated**: edit `src/Core.template.lua` (bus, MBC1/3/5,
timer, interrupts, ALU helpers) or `tools/gen_core.py` (one Lua function per opcode). Then run
`py tools/gen_core.py`.

```
GBCore.New(GBRomLibrary[name]) -> core | nil, err
core.RunFrame()  -- runs to the next VBlank; core.fb then holds 160x144 shades 0..3
core.RunCycles(n)  core.GetSerial()  core.GetRegs()  core.Read(a)  core.Write(a, v)
```

Status:
- **CPU:** passes all of Blargg's `cpu_instrs` (11 individual ROMs plus the combined MBC1 ROM).
- **PPU (DMG):** a scanline renderer with STAT/LYC interrupts. It matches `dmg-acid2` pixel for pixel.
- **Game Boy Color:** used for ROMs whose header supports or requires it. It includes VRAM and WRAM banking, colour
  palettes, tile attributes, CGB sprite priority, general and HBlank DMA, and double speed.
  It matches `cgb-acid2` pixel for pixel. Colour games draw through the `pixel` renderer.
- **Battery saves:** cartridge RAM is stored in `ForeverGBPlayerDB` (SavedVariables), keyed by ROM SHA-1.
  It's written on logout, `/reload`, `/fgb stop` or a ROM switch, and loaded on `/fgb play`.
- **Speed** (plain Lua 5.1 on a desktop PC): about 1–2 ms per Game Boy frame, including the PPU.
  Double-speed Color games use about twice the CPU time.
- **Not done yet:** audio, colouring of original Game Boy games on Color hardware, MBC2, RTC, mid-scanline effects
  and per-memory-access timing.

```
py tools/test_cpu.py testroms/blargg/cpu_instrs/individual/*.gb                    # CPU, offline
py tools/test_ppu.py testroms/acid2/dmg-acid2.gb testroms/acid2/reference-dmg.png  # PPU vs reference
py tools/test_ppu.py testroms/acid2/cgb-acid2.gbc testroms/acid2/reference-cgb.png # CGB PPU
py tools/make_cgb_tests.py && py tools/test_cgb.py    # double speed, DMA, WRAM banks, saves
py tools/make_joypad_test.py && py tools/test_joypad.py
/fgb cpu <rom>    # in game: serial output + ms/frame
/fgb play <rom>   # in game: run the emulator and draw it through the atlas renderer
```

## Playing

`/fgb play <rom>` starts the game and grabs the keyboard. Click the screen to grab it
again; Esc releases it. While grabbed, the keys below are temporarily rebound with WoW
override bindings (`SetOverrideBindingClick`). Releasing restores your normal bindings, and
nothing is saved to your keybinding settings. Combat releases the keyboard automatically,
because override bindings are protected in combat. `/fgb keys` prints every button
press and release, for debugging.

| Game Boy | Keys |
|---|---|
| D-pad | Arrow keys or WASD |
| A / B | `]` / `[` |
| Start / Select | Enter / Backspace or Right Shift |

Only those keys are taken over while the screen has focus. Every other key keeps its normal binding.
Emulation is paced to the real 59.73 Hz whatever WoW's frame rate is: at most 3 Game Boy
frames per WoW frame, and time beyond that is dropped rather than fast-forwarded.
`py tools/make_joypad_test.py && py tools/test_joypad.py` tests the joypad register and interrupt.

## Sound

WoW addons can't synthesise audio, change pitch or set per-sound volume. So the core models
the sound chip's registers and channel state, and the addon plays **pre-rendered samples**
for all 4 channels.

- **Core:** a sound-chip register model covering triggers, length, envelopes, sweep and the 512 Hz internal clock.
  It passes 9 of 12 of Blargg's `dmg_sound` tests. The 3 failures need the exact position inside the wave buffer,
  which doesn't matter for sample playback.
- **Shared pack:** `py tools/make_sound_pack.py` writes about 5,700 band-limited OGGs (about 67 MB, gitignored) to `ForeverGBPlayer/sound/`:
  - Squares: 25%/50% duty × C2–B7 × 4 volume levels, sustained, plus a version with each fade speed baked in.
  - Noise: every NR43 setting × 4 levels, built from the real LFSR sequence.
  - Wave: a triangle fallback.
- **Per-game wave pack:** `py tools/make_wave_pack.py <rom> --seconds 120` plays the game offline, records the
  channel-3 waveforms it uses, renders them and registers them in `sound/waves.lua`, which the `.toc` loads.
- **Player:** each WoW frame it maps every channel's state to a file. A fading square note plays a baked-fade
  file from start to end. Mid-note restarts were what made the rhythm uneven: the pacing was simulated and
  ruled out, at about 5 ms jitter at 60 fps either way. Noise follows its envelope by restarting, which doesn't click.
  Commands: `/fgb sound on|off`, `mode envelope|steps`, `channels 1234`, `fade <ms>`.
- **Preview without WoW:** `py tools/sound_preview.py <rom> [--mode envelope|steps] [--channels 12] [--fade 15]`
  writes `testroms/out/<rom>-sound-*.wav`. It runs the real addon code against a simulated `PlaySoundFile`.

`testroms/` is gitignored. Sources: Blargg ROMs from github.com/retrio/gb-test-roms, and
dmg-acid2 and cgb-acid2 from github.com/mattcurrie. The joypad, CGB and save test ROMs are
built by the `tools/make_*.py` scripts.

## Tools

- `tools/rom2lua.py`: ROM to Lua converter (see above).
- `tools/gen_core.py`: generates the CPU core. `tools/test_cpu.py`: runs test ROMs on it.
- `tools/make_atlas.py`: regenerates `media/atlas4.tga`.
- `tools/harness.py`: runs the addon under real Lua 5.1 (`py -m pip install lupa`) with
  a mocked WoW API. It checks the atlas texcoords and runs the benchmark. It then loads every
  converted ROM via `roms.xml`, checks that it rebuilds byte for byte (SHA-1) and passes the
  checksums, and prints the logo and tile views as ASCII. Its timings are a
  lower bound, because the mocked API calls are empty functions, and they have 1 ms
  timer resolution on Windows.

## Releasing

Tagged versions are tested, packaged and uploaded to CurseForge by the GitLab pipeline
(`.gitlab-ci.yml`, `ci/`). See [RELEASING.md](RELEASING.md) for the one-time setup and how to cut a release.
