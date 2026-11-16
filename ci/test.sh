#!/usr/bin/env bash
# Full emulator test suite (Python + real Lua 5.1 via lupa). Needs: pip install -r tools/requirements.txt
#   1. core/Core.lua is up to date with src/Core.template.lua + tools/gen_core.py
#   2. Blargg cpu_instrs (12 ROMs), dmg-acid2 + cgb-acid2 pixel-exact, CGB/save/joypad
#      test ROMs, Blargg dmg_sound (known wave-timing failures allowed), addon harness.
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"

echo "== Generated core is up to date =="
"$PY" tools/gen_core.py
if git ls-files --error-unmatch ForeverGBPlayer/core/Core.lua >/dev/null 2>&1; then
  if ! git diff --exit-code --stat -- ForeverGBPlayer/core/Core.lua; then
    echo "ERROR: ForeverGBPlayer/core/Core.lua doesn't match the template. Run 'py tools/gen_core.py' and commit it."
    exit 1
  fi
fi

echo "== Test ROMs =="
bash scripts/fetch-testroms.sh
"$PY" tools/make_joypad_test.py
"$PY" tools/make_cgb_tests.py

echo "== CPU: Blargg cpu_instrs =="
"$PY" tools/test_cpu.py testroms/blargg/cpu_instrs/individual/*.gb testroms/blargg/cpu_instrs/cpu_instrs.gb

echo "== PPU: dmg-acid2 / cgb-acid2 =="
"$PY" tools/test_ppu.py testroms/acid2/dmg-acid2.gb testroms/acid2/reference-dmg.png
"$PY" tools/test_ppu.py testroms/acid2/cgb-acid2.gbc testroms/acid2/reference-cgb.png

echo "== CGB double speed / DMA / WRAM banks / battery saves =="
"$PY" tools/test_cgb.py

echo "== Joypad =="
"$PY" tools/test_joypad.py

echo "== Sound chip: Blargg dmg_sound =="
"$PY" tools/test_apu.py testroms/blargg/dmg_sound/*.gb

echo "== Addon under a mocked WoW API (renderers, ROM packs + API, input, saves, sound) =="
"$PY" tools/harness.py

echo "All tests passed."
