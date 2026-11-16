# Releasing Forever GB Player

Releases are published to CurseForge by the GitLab pipeline whenever a version tag is pushed.
`scripts/release.sh` updates the addon's version and creates that tag for you. The setup is
the same as FojjiCore: Poker's.

## One-time setup

1. **GitLab project.** Create it, then push this repo to it:

   ```sh
   git add -A && git commit -m "Initial commit"
   git remote add origin <your GitLab URL>
   git push -u origin main
   ```

   The first pipeline runs `lint` and `test`, then builds a dev zip in `package` (download it from the job's
   artifacts). The `curseforge` job only runs on version tags.
2. **CurseForge project.** Create a World of Warcraft addon project for *Forever GB Player*,
   pick a license, and upload `media/logo.png` as the project logo.
   (`py scripts/make_logo.py` redraws it and the in-game icon.) Wait for CurseForge to approve it.
   - **Project ID:** shown in the project's About box.
   - **License:** if you add a `LICENSE` file to the repo root, `ci/package.sh` ships it inside the addon.
3. **CI/CD variables** (Settings > CI/CD > Variables):

   | Key | Value | Flags |
   | --- | --- | --- |
   | `CF_API_TOKEN` | API token from <https://authors.curseforge.com/account/api-tokens> | Masked, Protected |
   | `CF_PROJECT_ID` | the CurseForge project ID | |
   | `RELEASE_TOKEN` | only for releasing from GitLab (see below) | Masked, Protected |
   | `CF_GAME_VERSION_IDS` | optional: set if the automatic lookup from the `## Interface:` lines finds no match | |
   | `CF_DRY_RUN` | optional: `1` builds and tests everything but skips the upload | |

   Protected variables are only visible to protected branches and tags, so protect `main` and
   `v*` tags (Settings > Repository).
4. **Runner.** Jobs pull their images through the Docker Hub cache on the Pi (`HUB_MIRROR`,
   default `localhost:5001`), the same as FojjiCore: Poker. `test` and `package` use
   `python:3.12-slim-bookworm`; the rest use `alpine:3.20`.

## Releasing from GitLab (no local setup)

1. **Build > Pipelines > Run pipeline**, branch `main`.
2. Fill in the inputs:

   | Input | Values | Meaning |
   | --- | --- | --- |
   | `release` | `true` / `false` | Must be `true` to cut a release. |
   | `bump` | `patch` (default), `minor`, `major`, `none` | `none` tags the current `.toc` version: use it for the next beta, or the final release after betas. |
   | `channel` | `beta` (default), `alpha`, `prod` | CurseForge release type. `prod` tags `vX.Y.Z`. |
   | `message` | text | Changelog. Empty = commits since the previous tag. |

3. The pipeline runs `lint` and `test`, then the `release` job. It runs `scripts/release.sh` on `main`,
   then pushes two things:
   - the version commit, with `ci.skip` so it doesn't start another pipeline;
   - the tag. The tag's own pipeline packages the addon and uploads it to CurseForge.

`RELEASE_TOKEN` is a project access token (**Settings > Access tokens**: role **Maintainer**,
scope **write_repository**). The job can't use its own job token, because pushes made with
the job token don't start pipelines, so the tag would never be published.

## Releasing from your PC

Run from Git Bash in the repo:

```sh
bash scripts/release.sh patch --beta   # 0.1.0 -> 0.1.1, commit, tag v0.1.1-beta.1
bash scripts/release.sh --beta         # tag v0.1.1-beta.2 (no version change)
bash scripts/release.sh                # tag v0.1.1 (final release)
bash scripts/release.sh minor --alpha  # 0.1.1 -> 0.2.0, tag v0.2.0-alpha.1
bash scripts/release.sh 1.0.0 -m "First public release"
```

Commit or stash your work first, because the script won't run with uncommitted changes. Run it with `-h` for every
option: `--push`/`--no-push`, `-y`, `-n` (dry run), `-m`.

## What the pipeline does

| Job | Image | What it does |
| --- | --- | --- |
| **lint** | alpine | Lua 5.1 syntax check of the addon and the core template. Every file each `.toc` lists exists; the generated sound pack is exempt. All `.toc` versions agree. **No ROMs or converted ROM packs are inside the addon.** On tags, the tag matches the `.toc` version. |
| **test** | python | `ci/test.sh` (see below). |
| **package** | python | Generates the sound pack (about 5,700 OGG files) and zips the addon into `dist/` (about 55 MB). |
| **curseforge** | alpine | Uploads the zip with the tag message as the changelog. Runs on tags only. |

`ci/test.sh` runs the whole test suite:
- `core/Core.lua` matches the template.
- Blargg `cpu_instrs` (12 ROMs).
- `dmg-acid2` and `cgb-acid2`, pixel-exact.
- The CGB, battery-save and joypad test ROMs.
- Blargg `dmg_sound`. The 3 wave-timing tests are known failures, and they're checked to stay failing.
- The addon harness.

The test ROMs are downloaded by `scripts/fetch-testroms.sh`. Every file is checked against a pinned SHA-1, and the
files are cached between pipelines.

Run the same checks locally before pushing:

```sh
py -m pip install -r tools/requirements.txt
PYTHON=py bash ci/test.sh
```

## What ships

The zip contains the `ForeverGBPlayer` addon only: the code, the generated core, the atlas texture and the
shared sound pack. Per-game wave packs from your machine are stripped, and `waves.lua` ships empty.
**No ROMs are ever packaged.** Players make their own ROM pack addons with the
converter page or `tools/rom2lua.py`.

## Tag → CurseForge release type

| Tag | Release type |
| --- | --- |
| `v1.0.1` | release |
| `v1.0.1-beta.1` | beta |
| `v1.0.1-alpha.1` | alpha |
