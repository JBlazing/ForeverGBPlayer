# Forever GB Player: pending work

What's missing or unconfirmed after the v1.0.0 release (2026-11-16), roughly in order of how
much players would notice. Each item says what's wrong today and, where known, how to fix it.

## Not yet confirmed in game

These all pass offline tests (`ci/test.sh`) but nobody has seen them in WoW yet.

- [ ] **Performance numbers.** In game, nobody has read the stats line (`emu` / `render` ms per frame, FPS) for
      an original Game Boy game, a Color game, or `/fgb bench`. Every speed figure so far comes from Lua 5.1 on a desktop PC.
- [ ] **Color games.** The pixel renderer (23,040 textures) could be expensive when a Color game scrolls the whole
      screen. If it is, add a cheaper colour renderer (see *Rendering* below).
- [ ] **Baked-fade sound** (the default `envelope` mode). Its fix for uneven rhythm, plus the bass and drum channels,
      were only heard offline as WAV previews. The earlier `steps` mode was heard in game and its rhythm sounded uneven.
- [ ] **Battery saves in a real game.** Only the test ROM was checked. Try one RPG save across logout.
- [ ] **`[` / `]` as A / B.** Check WoW accepts them as override-binding keys. `/fgb keys` shows each press it receives.
- [ ] **The AddOns-list icon and ROM pack loading** after a full client restart on a fresh install from CurseForge.
- [ ] **Link cable** (`/fgb link <name>`, `Link.lua`). Tested offline with two emulators (`tools/test_link.py`) and
      through the real FojjiCore Games Duel/Comm code under Poker's WoW mock, not in game. Try a Pokémon trade
      between two players: check real whisper latency, how long a trade takes at ~3 bytes a second, and whether
      the game's own timeouts ever fire. If it's too slow, look at Comm's 0.35 s gap (it's shared with every
      FojjiCore game) or at sending several bytes per message where a game allows it.

## Players will notice

- [ ] **Bass (wave channel) uses a triangle wave for every game.** Each game's real bass waveform comes from
      `tools/make_wave_pack.py`, which only runs on a developer's PC. Players never get those waveforms. Options:
      - ship a library of common waveforms, collected from homebrew/test ROMs, and pick the nearest match at runtime;
      - or let the converter record waveforms. That needs an emulator in the browser.
- [ ] **No in-game game picker.** Everything is a slash command. Add a list of installed ROM packs with Play, plus
      on-screen Pause and Reset buttons.
- [ ] **Window position isn't saved** between sessions. Store it in `ForeverGBPlayerDB`. Also allow resizing by dragging,
      not just `/fgb scale`.
- [ ] **Keys are fixed.** Add a way to rebind them, and show the controls in the window.
- [ ] **Sound volume** is only on/off, and plays on the Master channel. Add a volume level, or a choice of
      WoW sound channel.
- [ ] **The "no games added yet" message** points to the bundled `ROM Converter.html`. It could also print the web
      address (https://jblazing.github.io/ForeverGBPlayer/tools/rom-converter.html).
- [ ] **ROM packs need regenerating when WoW's interface version changes.** The pack `.toc` files have
      `16001` / `20506` written in (`TOC_FLAVORS` in `tools/rom2lua.py` and the converter page). Plan how packs
      stay loadable after a patch, for example by documenting "load out of date addons", or with a converter update.

## Emulation gaps

- [ ] **MBC3 real-time clock** isn't emulated. Pokémon Gold, Silver and Crystal's clock doesn't work.
- [ ] **Cartridge types MBC2, MBC6, MBC7, HuC1, HuC3 and MMM01** aren't supported. The converter warns about them, and
      the emulator refuses them.
- [ ] **Original Game Boy games on Color hardware** aren't colourised the way a real Game Boy Color tints them.
      They run in 4 shades.
- [ ] **PPU accuracy:**
  - The drawing phase has a fixed length.
  - Register changes partway through a scanline aren't seen; the renderer only draws whole lines.
  - VRAM/OAM aren't blocked during drawing, and the OAM bug isn't emulated.

  Games using those tricks may glitch. Mid-frame changes between lines do work (Super Mario Land's status bar,
  dmg-acid2, cgb-acid2).
- [ ] **CPU timing:** memory accesses within an instruction aren't timed. Blargg's `instr_timing` and `mem_timing` tests
      haven't been run. HDMA/GDMA don't stall the CPU.
- [ ] **STOP** only switches CGB speed. Low-power STOP, and waking from it with the joypad, aren't emulated.
- [ ] **Not supported:** Super Game Boy borders and palettes, save states, fast-forward.

## Sound limits (from the sample-based design)

- [ ] **Duty cycles:** the 12.5% and 75% duty cycles use the 25% samples.
- [ ] **Pitch** snaps to the nearest semitone, so vibrato and pitch slides come out stepped.
- [ ] **No stereo panning:** NR51 only turns a channel on or off.
- [ ] **Note timing** is tied to WoW's frame rate (about 5 ms jitter at 60 FPS), plus WoW's own sound start-up delay,
      which hasn't been measured.
- [ ] **Untried idea:** drive four WoW sound channels' volume settings for smooth envelopes. It changes the player's
      audio settings, so it needs care.
- [ ] **Pack size:** about 67 MB, 55 MB zipped, mostly baked-fade square files. If CurseForge size or download time
      becomes a problem, trim fade speeds or generate them per game.
- [ ] **3 of Blargg's 12 `dmg_sound` tests fail** (09, 10, 12: wave RAM while playing). That's expected for sample
      playback; `KNOWN_FAILING` in `tools/test_apu.py` keeps them from failing CI.

## Rendering

- [ ] **A cheaper colour renderer** if the pixel renderer is too slow in game. One idea is per-scanline runs of
      equal colour instead of one texture per pixel.
- [ ] **Leftover commands from the original rendering test:** `bench`, `atlas`/`pixel`, `static`/`sprites`/`scroll`,
      `force`, `report`, `logo`, `tiles`, `cpu`. Keep them as hidden debug commands or remove them. They're still in
      `/fgb help`.

## Memory and loading

- [ ] **Every enabled ROM pack loads its whole ROM at login.** That's about 1× the ROM size in memory, plus 64 KB
      tables and the 3 MB AND/OR/XOR tables once per session. Large Color games (1–4 MB) add up. Consider loading
      packs on demand with `LoadAddOn` when `/fgb play` is used.
- [ ] **Old saves:** test saves under the old `GBRenderSpikeDB` name were never migrated. That's not needed for real
      players, but say so if anyone used a pre-rename build.

## Release and project housekeeping

- [ ] **CurseForge:** approval of the first file (9654763) is pending. Paste `media/curseforge.md` into the
      description and upload `media/logo.png` as the logo.
- [ ] **GitHub Pages:** the converter there is copied by hand from `tools/rom-converter.html`. Automate it from CI, or
      keep it in sync when the page changes. The ROM-ownership notice isn't there yet.
- [ ] **Unchecked facts in the description:** the Battle.net "Show in Explorer" wording and that `hh.gbdev.io` is
      still Homebrew Hub's address.
- [ ] **No LICENSE file.** Pick one; `ci/package.sh` ships it inside the addon if it exists.
- [ ] **CI takes about 11 minutes** per pipeline on the Pi. The test ROMs and pip downloads are cached; generating the
      sound pack is most of the `package` time.
