#!/usr/bin/env bash
# Uploads dist/<zip> to CurseForge via the WoW upload API:
#   POST https://wow.curseforge.com/api/projects/{projectId}/upload-file
# Once uploaded and approved, the CurseForge app offers the update to users automatically.
set -euo pipefail

API="https://wow.curseforge.com/api"
ADDON_DIR="${ADDON_DIR:-ForeverGBPlayer}"
TOC="$ADDON_DIR/$ADDON_DIR.toc"

: "${CF_API_TOKEN:?Set CF_API_TOKEN in Settings > CI/CD > Variables}"
: "${CF_PROJECT_ID:?Set CF_PROJECT_ID in Settings > CI/CD > Variables}"

# Pasted tokens often carry stray spaces, newlines or quotes; CurseForge rejects those as
# "malformed" (HTTP 400). An author upload token looks like xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx.
CF_API_TOKEN="$(printf '%s' "$CF_API_TOKEN" | tr -d '[:space:]"'\''')"
if [[ ! "$CF_API_TOKEN" =~ ^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$ ]]; then
  echo "ERROR: CF_API_TOKEN doesn't look like a CurseForge upload token (${#CF_API_TOKEN} characters;"
  echo "       expected xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx). Create one at"
  echo "       https://authors.curseforge.com/account/api-tokens - not a CurseForge Core API key"
  echo "       (those start with \$2a\$) - and if it contains '\$', untick 'Expand variable reference'."
  exit 1
fi

# GET a CurseForge API path; on failure print CurseForge's own error message, not just a code.
cf_get() {
  local body code
  body="$(mktemp)"
  code="$(curl -sS -o "$body" -w '%{http_code}' -H "X-Api-Token: $CF_API_TOKEN" "$API/$1")"
  if [[ "$code" != "200" ]]; then
    echo "ERROR: CurseForge returned HTTP $code for $1:" >&2
    cat "$body" >&2; echo >&2
    rm -f "$body"
    return 1
  fi
  cat "$body"; rm -f "$body"
}

zip_name="$(cat dist/ZIP_NAME)"
version="$(cat dist/VERSION)"
zip_path="dist/$zip_name"
[[ -f "$zip_path" ]] || { echo "ERROR: $zip_path missing; did the package job run?"; exit 1; }

# --- Release type from the tag suffix ---
case "${CI_COMMIT_TAG:-}" in
  *-alpha*) release_type="alpha" ;;
  *-beta*)  release_type="beta" ;;
  *)        release_type="release" ;;
esac

# --- Game versions ---
# Prefer explicit IDs. Otherwise turn each TOC's "## Interface: 20506" into "2.5.6" and look it
# up. The addon has one TOC per client flavor, so the file is tagged with every version found.
if [[ -n "${CF_GAME_VERSION_IDS:-}" ]]; then
  game_versions="$(jq -cn --arg ids "$CF_GAME_VERSION_IDS" '$ids | split(",") | map(gsub("\\s";"") | tonumber)')"
else
  all_versions="$(cf_get game/versions)"
  game_versions="[]"
  missing=0
  for interface in $(grep -h -m1 '^## Interface:' "$ADDON_DIR"/*.toc | sed 's/^## Interface:[[:space:]]*//; s/\r$//' | tr ',' '\n' | tr -d ' ' | sort -u); do
    major=$(( interface / 10000 ))
    minor=$(( (interface % 10000) / 100 ))
    patch=$(( interface % 100 ))
    game_name="${major}.${minor}.${patch}"
    ids="$(jq -c --arg n "$game_name" '[.[] | select(.name == $n) | .id]' <<<"$all_versions")"
    echo "Interface $interface -> CurseForge game version '$game_name': $ids"
    if [[ "$ids" == "[]" ]]; then
      missing=1
      echo "WARNING: CurseForge has no game version named '$game_name'. Closest matches (id  name):"
      jq -r --arg p "${major}.${minor}" '.[] | select(.name | startswith($p)) | "  \(.id)  \(.name)"' <<<"$all_versions" | head -20
    fi
    game_versions="$(jq -cn --argjson a "$game_versions" --argjson b "$ids" '$a + $b | unique')"
  done

  if [[ "$game_versions" == "[]" ]]; then
    echo "ERROR: none of the TOC interface versions match a CurseForge game version."
    echo "Set CF_GAME_VERSION_IDS to the right ID(s) and re-run this job."
    exit 1
  fi
  if (( missing )); then
    echo "Uploading for the versions that were found. Set CF_GAME_VERSION_IDS to include the others."
  fi
fi
echo "Game version IDs: $game_versions"

# --- Changelog: annotated tag message, else commits since the previous tag ---
changelog=""
if [[ -n "${CI_COMMIT_TAG:-}" ]] && [[ "$(git cat-file -t "$CI_COMMIT_TAG" 2>/dev/null)" == "tag" ]]; then
  changelog="$(git tag -l --format='%(contents)' "$CI_COMMIT_TAG" | sed '/-----BEGIN PGP SIGNATURE-----/,$d')"
fi
if [[ -z "${changelog//[[:space:]]/}" ]]; then
  prev_tag="$(git describe --tags --abbrev=0 "${CI_COMMIT_TAG:-HEAD}^" 2>/dev/null || true)"
  range="${prev_tag:+$prev_tag..}${CI_COMMIT_TAG:-HEAD}"
  changelog="$(git log --no-merges --format='- %s' "$range")"
fi
changelog="# Forever GB Player ${version}"$'\n\n'"${changelog:-No changes listed.}"
echo "---- changelog ----"; echo "$changelog"; echo "-------------------"

metadata="$(jq -cn \
  --arg changelog "$changelog" \
  --arg displayName "Forever GB Player ${version}" \
  --arg releaseType "$release_type" \
  --argjson gameVersions "$game_versions" \
  '{changelog: $changelog, changelogType: "markdown", displayName: $displayName,
    gameVersions: $gameVersions, releaseType: $releaseType}')"
echo "Metadata: $metadata"

if [[ "${CF_DRY_RUN:-0}" == "1" ]]; then
  echo "CF_DRY_RUN=1, skipping upload of $zip_path."
  exit 0
fi

echo "Uploading $zip_path to CurseForge project $CF_PROJECT_ID as $release_type..."
response_file="$(mktemp)"
http_code="$(curl -sS -o "$response_file" -w '%{http_code}' \
  -H "X-Api-Token: $CF_API_TOKEN" \
  --form-string "metadata=$metadata" \
  -F "file=@$zip_path" \
  "$API/projects/$CF_PROJECT_ID/upload-file")"

if [[ "$http_code" != "200" ]]; then
  echo "ERROR: CurseForge returned HTTP $http_code:"
  cat "$response_file"; echo
  exit 1
fi

file_id="$(jq -r '.id' "$response_file")"
echo "Uploaded. CurseForge file ID: $file_id"
