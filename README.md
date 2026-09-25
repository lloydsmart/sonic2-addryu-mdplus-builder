# Sonic 2 MD+ Forge

[![CI](https://github.com/lloydsmart/sonic2-mdplus-forge/actions/workflows/ci.yml/badge.svg)](https://github.com/lloydsmart/sonic2-mdplus-forge/actions/workflows/ci.yml)

Sonic 2 MD+ Forge is a reproducible build system for creating MD+ variants of
Sonic the Hedgehog 2 for the Mega Drive. It combines external soundtrack
arrangements with original Mega Drive audio where appropriate. The first and
currently supported soundtrack is Addryu's Sonic the Hedgehog 2 Mega-CD Remix;
the architecture is intended to allow additional soundtrack variants in future,
but no other profiles are currently supported.

The project does **not** contain or distribute a ROM, Sega assets, the Addryu
soundtrack, or proprietary binaries.

## Support Addryu — buy the soundtrack

**To use this builder, buy Addryu's
[Sonic the Hedgehog 2 [Mega-CD Remix] album on Bandcamp](https://addryu.bandcamp.com/album/sonic-the-hedgehog-2-mega-cd-remix)
and download your purchase in WAV format.** Please support the artist whose
work makes this soundtrack possible.

We do not condone unauthorized distribution of Addryu's work. Do not share or
upload the purchased tracks, converted or trimmed WAVs, or a finished package
containing them. Purchasing the album does not grant permission to redistribute
it, and this project's GPL license does not cover the music. The builder does
not download audio; you supply your own legitimately purchased files.

## Build status

Current status: all 16 Addryu cues are enabled in the default package and have
been hardware-verified on MiSTer, including their loops. Native title/menu
music, temporary native cues, native SFX alongside MD+ BGM, pause/resume and
fades have also been tested.

The pinned `msu-md-sonic2` fork includes the game-mode dispatch repair
submitted upstream as
[ArcadeTV PR #5](https://github.com/ArcadeTV/msu-md-sonic2/pull/5).
The Sound Test `19, 65, 09, 17` cheat followed by holding A + Start now opens
the normal 1P level select, and defeating the Death Egg final boss now enters
the ending cinematic instead of the VS/multiplayer level-select menu. Both
fixes have passed MiSTer hardware verification. REV01 is the current
hardware-verified baseline.

## What the build does

1. Fetches exact, pinned revisions of
   [`lloydsmart/msu-md-sonic2`](https://github.com/lloydsmart/msu-md-sonic2),
   a fork of ArcadeTV's Sonic 2 MSU-MD source, and the maintained
   Macroassembler AS (ASL) release.
2. Builds the assembler locally from source.
3. Deterministically removes the Mega-CD bootstrap/polling/seek path, replaces
   playback with MD+ commands, and wraps every command in a short-lived MD+
   overlay transaction after Sonic's startup checksum. A fixed sixteen-cue
   policy routes Addryu arrangements to MD+ and all other music to the original
   Sonic 2 YM2612/PSG/DAC soundtrack; SFX always use the native driver.
4. Builds the Rev 1 ROM and verifies its Mega Drive header checksum, MD+
   instruction signatures, size, and SHA-256 regression value.
5. Normalizes enabled user source audio to 44.1 kHz, signed 16-bit stereo PCM,
   trims it on an exact 75 Hz sector boundary, validates it, and generates the
   MD+ CUE.
6. Creates an ignored `dist/` directory ready to copy to MiSTer's Mega Drive
   games area.

## Prerequisites

The supported build host is a current Debian-like Linux system, including
RetroNAS. Install:

```sh
sudo apt install git make gcc python3 ffmpeg
```

No Python packages are required. Network access is needed only to fetch pinned
dependencies (two for the default MD+ build). The build never downloads a ROM or
soundtrack.

## Quick start

Clone this repository, then place your lawfully obtained Addryu WAVs under an
ignored directory:

```text
inputs/audio/
  Addryu - Sonic the Hedgehog 2 -Mega-CD Remix- - 01 Emerald Hill Zone.wav
  Addryu - Sonic the Hedgehog 2 -Mega-CD Remix- - 02 Chemical Plant Zone.wav
  Addryu - Sonic the Hedgehog 2 -Mega-CD Remix- - 03 Aquatic Ruin Zone.wav
  ... (all 16 album WAVs listed in config/tracks.json)
```

Run:

```sh
make doctor
make all INPUT_DIR="$PWD/inputs/audio"
```

The default manifest builds all 16 hardware-verified Addryu cues at:

```text
dist/Sonic 2 - Addryu Mega-CD Remix MD+/
  Sonic 2 - Addryu Mega-CD Remix MD+.md
  Sonic 2 - Addryu Mega-CD Remix MD+.cue
  track03.wav
  track05.wav
  track07.wav
  track08.wav
  track09.wav
  track10.wav
  track11.wav
  track12.wav
  track13.wav
  track14.wav
  track15.wav
  track26.wav
  track27.wav
  track28.wav
  track29.wav
  track31.wav
  SHA256SUMS.json
```

Copy that directory to MiSTer's Mega Drive library and launch the `.md` file
with a Main/MegaDrive core version that supports MD+. Do not launch the CUE
directly.

## Repeatable commands

Run the stages independently when developing:

```sh
make bootstrap
make source
make rom
make audio INPUT_DIR="$PWD/inputs/audio"
make package
make test
```

## Experimental modern stock build

An explicit parallel path builds unmodified stock REV01 from current
[`sonicretro/s2disasm`](https://github.com/sonicretro/s2disasm), pinned to
`380f37a731bfc720bb0371a35a593184a7ec5e43`. This source is **not yet MD+
capable**. The production MD+ implementation remains the default for
`make bootstrap`, `make source`, `make rom`, and `make all`.

With Lua 5.3 or newer available as `lua` (tested with 5.3.6), run:

```sh
make bootstrap-modern
make build-stock-modern
```

Bootstrap fetches only the modern source into ignored `build/source-modern/`.
It also accepts `python3 -m tools.mdplus_builder bootstrap-modern
--local-source /path/to/s2disasm` to reuse a local clone containing the pin.
The build uses a disposable clean clone under `build/`, leaving the dependency
checkout untouched and excluding local edits or earlier build output. It runs
upstream's `lua build.lua` with unchanged settings and native build tools,
without Forge's legacy ASL transformations.

Only an exact audited stock REV01 match is copied to
`build/sonic2-stock-modern.md`:

- Size: `1,048,576` bytes
- MD5: `9feeb724052c39982d432a7851c98d3e`
- SHA-256: `193bc4064ce0daf27ea9e908ed246d87ec576cc294833badebb590b6ad8e8f6b`

This experimental ROM is not used by the MD+ packaging or audio commands.

## Experimental modern live MD+ build

Stage 5 is the first modern build with live MD+ ownership and routing. It uses
all sixteen production Addryu routes, the unchanged Stage 3 transaction backend,
and the frozen Stage 4 acknowledged music-only Z80 stop. Local CPU validation
has passed, and **the required MiSTer FPGA hardware gate has passed**, as reported
by the maintainer. The optional missing-WAV robustness test was not run.

```sh
make bootstrap-modern
make build-stock-modern
make prepare-modern
make build-modern
```

The verified experimental ROM is `build/sonic2-modern-mdplus.md`.
`build/prepared-modern/` contains the regenerated source, listing, and assembler
object evidence. Preparation checks the pinned hashes of all three transformed
upstream files and starts from committed input each time. Edit Forge's
transformer/includes; generated preparation is replaced on every build.

`make rom`, `make all`, audio and packaging commands still use the production
legacy path. Modern packaging and the default cutover are not implemented.
The stock modern REV01 build remains separate and byte-identical.

See [the Stage 5 architecture and audit](docs/MODERN_STAGE5.md) for the complete
state machine, RAM/ROM addresses, upstream call-site audit, exact hashes, CPU
traces, remaining limits and the MiSTer procedure. [Stage 4](docs/MODERN_STAGE4.md)
records the preceding inert handoff stage.

With the optional emulation environment described below, run all three suites:

```sh
PYTHONPATH=. build/emulation-venv/bin/python tests/check_modern_binary.py
PYTHONPATH=. build/emulation-venv/bin/python tests/check_modern_handoff_binary.py
PYTHONPATH=. build/emulation-venv/bin/python tests/check_modern_live_binary.py
```

These execute compiled 68000/Z80 instructions. They cover register/CCR and
mailbox contracts, ACK ordering, cancellation, pause/resume, native temporary
cues, all six extra-life call sites, 255-VInt ducking and checksum/reset order.
They do not model audible mixing, SD-card access or console bus timing.

## Assembler toolchain

The assembler is ASL 1.42 build 306 from
[Macroassembler-AS/asl-releases](https://github.com/Macroassembler-AS/asl-releases),
pinned to commit `c7155b4fd3d33110f0eb098dede4295a8c008772` in
`config/dependencies.json`. Bootstrap builds its unmodified source with the
portable `Makefile.def.tmpl` and `make binaries` under ignored `build/asl/`.
No system-wide assembler installation is required.

Existing checkouts created before the fixed source pin should remove the
ignored `build/source/` checkout once before running `make bootstrap`:

```sh
rm -rf build/source
make bootstrap
```

This does not affect soundtrack inputs under `inputs/`. The previous
`build/as-sonic/` directory is unused and can remain in place. Source
preparation remains deterministic and rejects unexpected edits.

The pinned Sonic source predates current ASL semantics. Preparation balances
replacement RAM `PHASE` sections, checks RAM usage without relying on 32-bit
counter wraparound, makes word-sized RAM operands explicit, and parenthesizes
ambiguous anonymous-label expressions. It also makes the signed 8-bit intent
of 33 audited high-byte `moveq` operands explicit while retaining symbolic IDs.
These are syntax compatibility changes;
the source revision, upstream build script, Sonic object converter/compressor,
pointer fixups, and header fixer remain unchanged.

The assembler migration preserved the complete ROM SHA-256 at that time,
including the compressed Z80 driver. The nine CPU-level
tests described below provide additional regression coverage. The only remaining
ASL warning is the intentional odd-address word access (`move.w (1).w,d0`),
which causes a hardware crash; its instruction remains unchanged. The assembler
migration itself did not change the ROM baseline. The subsequent game-mode
repair establishes the hardware-verified baseline below.

## Audio normalization policy

Supply the original WAV files from your lawful soundtrack download; manual
sample-rate or bit-depth conversion is not required. The builder probes each
source with FFprobe and normalizes it to the MD+ output format.

Native 44.1 kHz, signed 16-bit stereo PCM WAVs use a sample-preserving copy and
trim path, without resampling or dithering. Other sample rates are converted
once with FFmpeg's SoX Resampler at precision 33. Reduction to signed 16-bit
PCM, including conversion after a speed change, uses explicit high-pass
triangular dithering. Expanding lower-bit integer PCM does not add dither. Mono
input is expanded by copying each final mono sample exactly to left and right
with no gain change; input with more than two channels is rejected rather than
applying an unspecified downmix. Source input is intentionally WAV-only; other
containers are rejected rather than treated as an implicit compatibility
promise.

All trimming and sector calculations occur after conversion in the final
44.1 kHz domain. Without an explicit end sector, only complete 588-frame CD
sectors are retained and the incomplete trailing fragment is reported.

To reuse an existing clean checkout instead of downloading the Sonic source,
the checkout must contain the pinned `lloydsmart/msu-md-sonic2` commit:

```sh
python3 -m tools.mdplus_builder bootstrap \
  --local-source "$HOME/src/msu-md-sonic2"
```

The tool clones the specified checkout at the exact pinned commit into
`build/source`; it does not alter the original checkout. An ArcadeTV-only clone
that has not fetched the fork commit cannot supply this dependency.

## ROM verification

The source build is the authoritative path; a clean cartridge ROM is not used
as build input. If you want to confirm the provenance of your own dump:

```sh
python3 -m tools.mdplus_builder verify-clean-rom \
  "/path/to/Sonic The Hedgehog 2 (World).md"
```

`verify-clean-rom` recognises both supported canonical World revisions:
Rev 0 (`24AB4C3A`) and Rev 1 (`7B905383`). Generated ROM verification is
stricter:

```sh
python3 -m tools.mdplus_builder verify-rom \
  --strict-regression build/sonic2-mdplus.md
```

Hardware-verified hybrid regression values:

- size: `2,129,922` bytes
- SHA-256: `315c69fb84dbca2a31ceffe3face70b4138317feed53feb7e23c6a5ab009205e`
- Mega Drive checksum: `2911`
- 21 complete MD+ open/command/close signatures and one Emerald Hill track-03
  signature

The repaired REV01 ROM is the audited production baseline. Both `build-rom`
and `--strict-regression` enforce these values after a complete MiSTer
hardware playthrough, including the level-select cheat, MD+ and native-audio
handoffs, Special Stages, 2P, Super Sonic, and the Death Egg ending transition.

The first hybrid hardware test failed. This corrected ROM fixes the truncated
Z80 driver load, separates the handoff ACK from the command queue, and has since
passed extended MiSTer testing. See the
[failure analysis](docs/HYBRID_AUDIO.md#first-hardware-failure).

## Adding tracks and loop points

Edit a working copy of `config/tracks.json`; do not guess loop values. The
manifest refuses to build an enabled looping track without valid start/end
sectors. An optional `trim_start_sector` removes whole CD sectors from the
start of the processed 44.1 kHz audio before the output WAV is written; loop
start/end sectors remain relative to the generated WAV after that trim. See
[docs/TRACKS.md](docs/TRACKS.md) for candidate
detection, sector/sample arithmetic, speed-shoes tracks, listening tests, and
MiSTer verification.

## Limitations

The [sixteen Addryu cues](docs/TRACKS.md#fixed-rom-routing) are fixed in the ROM,
independent of manifest flags, CUE contents, and files on disk. Missing WAVs for
those cues are incomplete-package errors; they never select native music.
The default package includes all sixteen Addryu-owned cues, each verified on
MiSTer hardware.

Unarranged cues, including title/options, bosses, invincibility, drowning, act
clear, ending and credits, use the original Sonic 2 soundtrack. No second
soundtrack or conversion of native music to WAV is needed. MD+ speed variants
are disabled: speed shoes change physics while Addryu music keeps playing at
normal speed. Native speed controls retain the original driver behavior.

See [hybrid architecture](docs/HYBRID_AUDIO.md) for queue semantics, handoff
ordering, RAM allocation, and the retained native 1-up limitations.

## Clean Linux regression

After `make bootstrap`, create a separate clean checkout of the pinned source
and rebuild it without touching existing diagnostic checkouts:

```sh
python3 - <<'PYTHON'
from tools.mdplus_builder.common import BUILD, SOURCE_DIR, DEPENDENCIES, load_json
from tools.mdplus_builder.source import _clone_at, apply_mdplus, build_rom

deps = load_json(DEPENDENCIES)["source"]
clean = BUILD / "hybrid-clean"
_clone_at(deps["url"], deps["commit"], clean, local_source=SOURCE_DIR)
print(apply_mdplus(clean))
print(build_rom(clean, BUILD / "hybrid-clean.md"))
PYTHON
```

Every build also verifies the loader instructions and compares the complete
ROM-decompressed Z80 driver against the assembled object segment. Use a fresh
destination for later runs if that checkout already contains generated changes.
The clean build must pass the strict regression check against the audited
hardware baseline above. Run both binary suites below against that build.

For CPU-level handoff regression tests, install the optional emulation tools
in an ignored virtual environment and use the generated ROM and map:

```sh
python3 -m venv build/emulation-venv
build/emulation-venv/bin/pip install -e '.[emulation]'
PYTHONPATH=. build/emulation-venv/bin/python tests/check_hybrid_binary.py \
  build/hybrid-clean
PYTHONPATH=. build/emulation-venv/bin/python tests/check_game_modes_binary.py \
  build/hybrid-clean
```

These tests execute the actual loader, router, input service, Z80 dispatcher and
VInt code. They record MD+ commands and sound-chip writes, supplementing the
existing MiSTer audio verification with deterministic CPU-level coverage.
The gameplay suite additionally checks all eleven compiled game-mode slots,
sound-test cheat entry and title transitions (including negative controls),
the final Death Egg transition, and the 2P Results return stack. It executes
actual ROM code at these boundaries, with graphics/interrupt timing excluded;
it does not replace MiSTer gameplay testing.

## Copyright

Read [docs/LEGAL.md](docs/LEGAL.md). In short: publish the scripts and metadata,
not the generated game or audio. `build/`, `dist/`, ROMs, WAVs, CUEs, and common
disc-image formats are ignored on purpose.

The original tooling in this repository is licensed under
[GPL-3.0-only](LICENSE). See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
for dependency licensing and trademark notices. Contributions are covered by
[CONTRIBUTING.md](CONTRIBUTING.md), the [Code of Conduct](CODE_OF_CONDUCT.md),
and the [security policy](SECURITY.md).
