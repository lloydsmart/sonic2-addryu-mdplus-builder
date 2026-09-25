# Stage 6 production cutover

## Public-interface audit before editing

The starting branch is `migration/06-modern-cutover`, at integration base
`1398a775cd724e8f6e80506d170be0e11a8eda9b`. The starting working tree was clean.

| Surface | Before Stage 6 | Cutover decision |
| --- | --- | --- |
| README quick start | `make doctor`, then `make all INPUT_DIR=...` | Keep these commands; select current s2disasm |
| `bootstrap` | Fetch legacy fork and ASL | Fetch pinned current s2disasm by default |
| `prepare-source` / `make source` | Convert legacy dependency in place | Prepare current source; clone legacy input |
| `build-rom` / `make rom` | Legacy at canonical ROM path | Stage 5 bytes at the same canonical path |
| `all` | Legacy bootstrap, conversion, ROM, audio, package | Current source bootstrap, ROM, unchanged audio, package |
| `package` | Canonical ROM path, legacy signature verifier | Strict selected-implementation verification |
| `verify-rom` | Legacy verifier, optional exact regression | Current verifier by default; explicit legacy option |
| `bootstrap-modern` | Fetch current s2disasm only | Compatibility alias for default bootstrap |
| `prepare-modern`, `build-modern` | Stage 5 migration commands | Compatibility/development aliases |
| `build-stock-modern` | Independent upstream stock REV01 audit | Retain as a development command |
| Modern filename | `build/sonic2-modern-mdplus.md` | Compatibility symlink to canonical output |
| Package names and manifest | Addryu basename, 16 WAVs, matching CUE, checksums | Preserve |
| Tests | Explicitly assert `all` still selects legacy | Replace with default and fallback selection protection |
| CI | Lint, units, legacy conversion, stock and scaffold builds | Both exact ROMs and compiled CPU suites |

CLI entry points are `python3 -m tools.mdplus_builder` and the installed
`sonic2-mdplus` console script. Make delegates to the module CLI. The default
Make goal is help, so invoking bare `make` does not build a package.

The existing `source` and `source_modern` dependency keys remain unchanged;
they identify the legacy fork and current s2disasm respectively. Current source
stays pinned to `380f37a731bfc720bb0371a35a593184a7ec5e43`.

The old `*-modern` names are useful automation aliases but are migration
terminology, so they become secondary documentation. Internal Python, Lua and
`hybrid_modern*.asm` filenames remain: changing them adds no production benefit.
The historical Stage 4/5 and legacy architecture documents describe their
original stages; the README defines the current interface.

## Resulting interface and rollback

The complete normal build is `make all INPUT_DIR=/path/to/purchased/audio`.
The ROM-only sequence is `make bootstrap` then `make rom`. The equivalent module
commands are `bootstrap` and `build-rom`, without implementation flags.
The canonical ROM is `build/sonic2-mdplus.md`.

Use `make bootstrap-legacy` then `make rom-legacy` for
`build/sonic2-legacy-mdplus.md`. The same module commands with `--legacy` select
the fallback. Preparation uses `build/prepared-legacy/` instead of modifying the
source dependency. Both ROM build outputs coexist. Legacy packaging is explicit
through `make package-legacy` or `make all-legacy INPUT_DIR=...`; it replaces the
same Addryu package directory. `make package` restores the current package.

The default package is still `dist/Sonic 2 - Addryu Mega-CD Remix MD+/`, with
matching `.md` and `.cue` basenames, sixteen `trackNN.wav` files and
`SHA256SUMS.json`. The package verifier requires the selected ROM's exact
regression identity. Old legacy bytes left at the canonical path are rejected.
No audio source, conversion policy, track mapping or loop coordinate changed.
The builder neither supplies nor downloads Addryu audio.

The three `bootstrap-modern`, `prepare-modern`, and `build-modern` aliases remain.
Both production and alias builds create the canonical ROM and a relative symlink
at `build/sonic2-modern-mdplus.md`. No additional ROM copy is required.
The independent `build-stock-modern` command remains a stock-source audit.
There are no internal file renames and no functional ASM or transformer changes.
Python changes select builds, prepare the legacy working copy, name outputs,
and enforce verification. The upstream Lua wrapper is included in package data.

## Binary release-candidate contract

| Measurement | Required and locally verified identity |
| --- | --- |
| Production size/checksum | 2,097,152 bytes / `BE41` |
| Production MD5 | `9eb40c0601a7c424a0d1ce168b5f40f2` |
| Production SHA-256 | `bd12138cd478596e4d294a06f573a98a6d37747dfe58d726ca62cf50dc3a8c44` |
| Legacy size/checksum | 2,129,922 bytes / `2911` |
| Legacy SHA-256 | `315c69fb84dbca2a31ceffe3face70b4138317feed53feb7e23c6a5ab009205e` |
| Stage 3 extension SHA-256 | `a42fecc8e83354d76638f42de8810bbfaa678d54c77b8ae1051a261af26103f1` |
| Stage 3 command transactions | 21 |
| Stage 4 compressed/loaded Z80 | 4,009 / 4,986 bytes |
| Stage 4 loaded SHA-256 | `9f997cc7217dda878297f7359f3314c7876aeb29e8705d63bd4b6db1513db24f` |

The production ROM is byte-identical to the already hardware-tested Stage 5 ROM.
No hook location, RAM layout, startup timing, ownership rule, handoff, ducking,
pause/resume, speed-shoe behavior or native driver byte changed.
The source pin and the default track manifest are unchanged.

## Validation and CI

The README records the complete local commands. `tests/test_cutover.py` protects
ordinary CLI selection, deliberate fallback selection, aliases and packaging.
`tests/check_production_binary.py` checks actual built ROM identities, the
prepared source pin, compatibility symlink, frozen backend and Z80. The existing
five compiled CPU suites remain unchanged. `tests/check_modern_fixbugs.py` runs
the unsupported-layout negative control in a temporary generated copy.

CI now builds stock upstream, production and legacy once each. It verifies exact
identities and runs the three production CPU suites, two legacy CPU suites and
actual `fixBugs=1` assembly rejection, alongside lint, compilation, units and
manifest validation. Unit coverage checks alias dispatch without rebuilding an
identical production ROM a second time in CI. The local RC pass also executes
all three aliases and checks the resulting binary identity.

The local RC validation passed:

| Check | Result |
| --- | --- |
| Ruff, Markdownlint, compileall, manifest, diff whitespace | Pass |
| Unit tests, including synthetic FFmpeg conversion | 95 pass |
| Stock upstream, canonical production, explicit legacy | Exact identities |
| Production backend / Stage 4 handoff / Stage 5 live CPU suites | 7 / 14 / 15 pass |
| Legacy hybrid / game-mode CPU suites | 9 / 8 pass |
| Actual `fixBugs=1` assembly | Rejected by the existing input-layout assertion |
| All three modern aliases | Pass; same canonical ROM and symlink |
| Clean disposable `make all` using local purchased WAVs | Pass; fresh dependency fetch and full package |
| Clean legacy bootstrap/build/package | Pass; exact fallback identity |
| Package audit | 19 files; all 16 WAVs, CUE and checksums valid |
| Original and disposable production packages | Identical complete checksum maps |
| Legacy package versus production | Same audio and CUE; only ROM and checksum metadata differ |

The disposable copy began with tracked and nonignored new repository files and
no generated dependencies or outputs. It used the existing local audio directory
as input. Its source checkouts remained untouched. The executed code matches the
reviewed code; only this audit document was completed after the snapshot.
The production package was restored after exercising explicit legacy packaging.
Remote GitHub Actions was not run during this uncommitted local preparation.

Review artifacts live under ignored `build/`:

- `build/stage6-review.diff`: full tracked and nonignored new-file diff.
- `build/stage6-review.txt`: interface audit, results, status and complete stat.
- `build/stage6-evidence.json`: identities, commands, logs and provenance.
- `build/stage6-validation/`: individual command logs and disposable-copy audit.
- `build/stage6-clean/`: disposable source snapshot with separate build/package.

These are local review outputs. No ROM, source assets, soundtrack or generated
package belongs in a commit or release attachment. No branch change, commit,
push, merge, PR, tag or release is part of Stage 6 preparation.

## Short MiSTer RC checklist

The required Stage 5 FPGA gate remains passed. Binary identity is established
separately from package/interface validation. A repeat hardware smoke test is
optional and checks the newly generated package; another full playthrough is
not required for unchanged ROM bytes. No new Stage 6 hardware results are claimed.

1. Copy the canonical Addryu package from `dist/` to MiSTer and launch its `.md`.
2. Cold boot and confirm normal SEGA PCM.
3. Confirm title/menu native BGM and SFX.
4. Enter EHZ and hear Addryu track03, with ordinary SFX over MD+.
5. Pause and unpause.
6. Trigger one temporary native cue, then return to MD+ level music.
7. Confirm the matching CUE and all WAV files are discovered under the unchanged
   package names. Record core version, region, date and package checksum metadata.

The optional missing-WAV robustness test was not run and is not a new gate.
