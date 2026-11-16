#!/usr/bin/env bash
# Download the public test ROMs the test suite uses into testroms/ (gitignored) and check
# each one's SHA-1, so a changed or tampered download fails loudly instead of silently
# changing what the tests mean. Files already present with the right hash are skipped.
#
#   bash scripts/fetch-testroms.sh
#
# Sources: Blargg's test ROMs (mirror: github.com/retrio/gb-test-roms) and Matt Currie's
# dmg-acid2 / cgb-acid2 (github.com/mattcurrie). None of these are commercial games.
set -euo pipefail
cd "$(dirname "$0")/.."

BLARGG="https://raw.githubusercontent.com/retrio/gb-test-roms/master"
ACID="https://github.com/mattcurrie"
RAW_ACID="https://raw.githubusercontent.com/mattcurrie"

# sha1 | path under testroms/ | url
MANIFEST="$(cat <<EOF
c2514e74e80e10b5a6294ff49ece4ac58ca2ef0d|acid2/cgb-acid2.gbc|$ACID/cgb-acid2/releases/download/v1.1/cgb-acid2.gbc
e04b6f1b754fca299bea97fc54d00763a6f6b3ef|acid2/dmg-acid2.gb|$ACID/dmg-acid2/releases/download/v1.0/dmg-acid2.gb
721ee8b6f4713ba4949e25c31096071082869807|acid2/reference-cgb.png|$RAW_ACID/cgb-acid2/master/img/reference.png
664fd8735679225b949ce881212223a1a476b222|acid2/reference-dmg.png|$RAW_ACID/dmg-acid2/master/img/reference-dmg.png
a979a7321b63b8e744d75d6aa7866b1e00d43da8|blargg/cpu_instrs/cpu_instrs.gb|$BLARGG/cpu_instrs/cpu_instrs.gb
30def8804393401f7ea68a6a34d783966c69a6cf|blargg/cpu_instrs/individual/01-special.gb|$BLARGG/cpu_instrs/individual/01-special.gb
328c8bcae8ebc3ef5e4acac3d09f8a681ba75c6e|blargg/cpu_instrs/individual/02-interrupts.gb|$BLARGG/cpu_instrs/individual/02-interrupts.gb
a0d20d837ffedfe51058d62af30692ee6b7374e1|blargg/cpu_instrs/individual/03-op sp,hl.gb|$BLARGG/cpu_instrs/individual/03-op%20sp,hl.gb
7d709828b7ae2ba2afe4354920fceb0db3886fa7|blargg/cpu_instrs/individual/04-op r,imm.gb|$BLARGG/cpu_instrs/individual/04-op%20r,imm.gb
d92e362cbb9bfdddd23e6dd04e81cdb25429fe34|blargg/cpu_instrs/individual/05-op rp.gb|$BLARGG/cpu_instrs/individual/05-op%20rp.gb
72619ddc8db25d6315cae6ea5da5567aa7c860a8|blargg/cpu_instrs/individual/06-ld r,r.gb|$BLARGG/cpu_instrs/individual/06-ld%20r,r.gb
31ee3c4827f005a2e57fba8e0330cfab35e8ead1|blargg/cpu_instrs/individual/07-jr,jp,call,ret,rst.gb|$BLARGG/cpu_instrs/individual/07-jr,jp,call,ret,rst.gb
83fc294ec31ae94b58d3ac79d0ac6722e1e5a851|blargg/cpu_instrs/individual/08-misc instrs.gb|$BLARGG/cpu_instrs/individual/08-misc%20instrs.gb
5d6f3af0573677d5305fcf788ed77afd80b91b4d|blargg/cpu_instrs/individual/09-op r,r.gb|$BLARGG/cpu_instrs/individual/09-op%20r,r.gb
5753b04e28fa9503e2540e778f10eb134c2526be|blargg/cpu_instrs/individual/10-bit ops.gb|$BLARGG/cpu_instrs/individual/10-bit%20ops.gb
5bd6040bf3b2f8270256ff51ca9671e26b151c0a|blargg/cpu_instrs/individual/11-op a,(hl).gb|$BLARGG/cpu_instrs/individual/11-op%20a,(hl).gb
6ed3a46bbd3c49fa47b16fd760c290c15aafb427|blargg/dmg_sound/01-registers.gb|$BLARGG/dmg_sound/rom_singles/01-registers.gb
5c878e14bc2248481b543907a6a2fd4027c5aa48|blargg/dmg_sound/02-len ctr.gb|$BLARGG/dmg_sound/rom_singles/02-len%20ctr.gb
5da01e50f1a9183bb5159aa536a9cf652b0f04db|blargg/dmg_sound/03-trigger.gb|$BLARGG/dmg_sound/rom_singles/03-trigger.gb
56aea136101380d0ff01751f17b023fe94d2274c|blargg/dmg_sound/04-sweep.gb|$BLARGG/dmg_sound/rom_singles/04-sweep.gb
8b888fc12782589892e65ec1f90ead7a2109ef7b|blargg/dmg_sound/05-sweep details.gb|$BLARGG/dmg_sound/rom_singles/05-sweep%20details.gb
88e6e30ae13bd5fd60b32d3400b3f93b29d62523|blargg/dmg_sound/06-overflow on trigger.gb|$BLARGG/dmg_sound/rom_singles/06-overflow%20on%20trigger.gb
4e6c188a31b5b54a01e0318797ef8f405d6a86a1|blargg/dmg_sound/07-len sweep period sync.gb|$BLARGG/dmg_sound/rom_singles/07-len%20sweep%20period%20sync.gb
d627255a93155cf71941a9925d657471a5105b94|blargg/dmg_sound/08-len ctr during power.gb|$BLARGG/dmg_sound/rom_singles/08-len%20ctr%20during%20power.gb
49933e2331ae4411ca58d7fbd8898d9463cbb1f9|blargg/dmg_sound/09-wave read while on.gb|$BLARGG/dmg_sound/rom_singles/09-wave%20read%20while%20on.gb
76f231c68d2a8faa642cc8ef2d02e61b3e6e74c8|blargg/dmg_sound/10-wave trigger while on.gb|$BLARGG/dmg_sound/rom_singles/10-wave%20trigger%20while%20on.gb
eaf8b054d6164c9ad92b3ea43cd2b24b93cdfc70|blargg/dmg_sound/11-regs after power.gb|$BLARGG/dmg_sound/rom_singles/11-regs%20after%20power.gb
5a977450b465fe996fa987364d37ac7712c2a399|blargg/dmg_sound/12-wave write while on.gb|$BLARGG/dmg_sound/rom_singles/12-wave%20write%20while%20on.gb
EOF
)"

fetched=0 kept=0
while IFS='|' read -r sha path url; do
  dest="testroms/$path"
  if [[ -f "$dest" ]] && [[ "$(sha1sum "$dest" | cut -d' ' -f1)" == "$sha" ]]; then
    kept=$((kept + 1))
    continue
  fi
  mkdir -p "$(dirname "$dest")"
  curl -fsSL --retry 3 -o "$dest.part" "$url"
  got="$(sha1sum "$dest.part" | cut -d' ' -f1)"
  if [[ "$got" != "$sha" ]]; then
    rm -f "$dest.part"
    echo "ERROR: $path from $url has SHA-1 $got, expected $sha" >&2
    exit 1
  fi
  mv "$dest.part" "$dest"
  fetched=$((fetched + 1))
done <<<"$MANIFEST"
echo "Test ROMs ready: $fetched downloaded, $kept already present (all SHA-1 verified)."
