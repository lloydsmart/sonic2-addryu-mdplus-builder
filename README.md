# Sonic 2 — Addryu Mega-CD Remix MD+ builder

[![CI](https://github.com/lloydsmart/sonic2-addryu-mdplus-builder/actions/workflows/ci.yml/badge.svg)](https://github.com/lloydsmart/sonic2-addryu-mdplus-builder/actions/workflows/ci.yml)

This project reproducibly builds the proven Sonic 2 MD+ source conversion and
turns user-supplied Addryu WAVs into a MiSTer-ready directory. It does **not**
contain or distribute a ROM, Sega assets, the Addryu soundtrack, or proprietary
binaries.

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

Current status: the ROM conversion, Emerald Hill, and Chemical Plant are
reproducible. Emerald Hill's sector `292 → 3892` loop and Chemical Plant's
sector `1900 → 5500` loop have been verified as seamless on MiSTer. The other
Addryu tracks are mapped but deliberately disabled until their loop points
have been measured and hardware-tested.

## What the build does

1. Fetches exact, pinned revisions of ArcadeTV's Sonic 2 MSU-MD source and the
   Sonic-compatible AS assembler.
2. Builds the assembler locally from source.
3. Deterministically removes the Mega-CD bootstrap/polling/seek path, replaces
   playback with MD+ commands, and wraps every command in a short-lived MD+
   overlay transaction after Sonic's startup checksum.
4. Builds the Rev 0 ROM and verifies its Mega Drive header checksum, MD+
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

No Python packages are required. Network access is needed only to fetch the two
pinned source dependencies. The build never downloads a ROM or soundtrack.

## Quick start

Clone this repository, then place your lawfully obtained Addryu WAVs under an
ignored directory:

```text
inputs/audio/
  Addryu - Sonic the Hedgehog 2 -Mega-CD Remix- - 01 Emerald Hill Zone.wav
  Addryu - Sonic the Hedgehog 2 -Mega-CD Remix- - 02 Chemical Plant Zone.wav
```

Run:

```sh
make doctor
make all INPUT_DIR="$PWD/inputs/audio"
```

The initial manifest builds the two hardware-verified stage tracks at:

```text
dist/Sonic 2 - Addryu Mega-CD Remix MD+/
  Sonic 2 - Addryu Mega-CD Remix MD+.md
  Sonic 2 - Addryu Mega-CD Remix MD+.cue
  track03.wav
  track05.wav
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

To reuse an existing clean checkout instead of downloading the Sonic source:

```sh
python3 -m tools.mdplus_builder bootstrap \
  --local-source "$HOME/sonic2-mdplus"
```

The tool clones the specified checkout at the pinned commit into `build/source`;
it does not alter the original experiment.

## ROM verification

The source build is the authoritative path; a clean cartridge ROM is not used
as build input. If you want to confirm the provenance of your own dump:

```sh
python3 -m tools.mdplus_builder verify-clean-rom \
  "/path/to/Sonic The Hedgehog 2 (World).md"
```

The expected Rev 0 CRC32 is `24AB4C3A`. Generated ROM verification is stricter:

```sh
python3 -m tools.mdplus_builder verify-rom \
  --strict-regression build/sonic2-mdplus.md
```

Expected proven regression values:

- size: `2,129,922` bytes
- SHA-256: `b388cd875145b1c637623bd0846bd071c7fefd12b289e3912fd9dbd63a50956b`
- Mega Drive checksum: `32E3`
- 52 complete MD+ open/command/close signatures and one Emerald Hill track-03
  signature

## Adding tracks and loop points

Edit a working copy of `config/tracks.json`; do not guess loop values. The
manifest refuses to build an enabled looping track without valid start/end
sectors. See [docs/TRACKS.md](docs/TRACKS.md) for candidate detection,
sector/sample arithmetic, speed-shoes tracks, listening tests, and MiSTer
verification.

## Limitations

The included Addryu album mappings cover the stage tracks present on the album.
Sonic cues for which no enabled external track exists will be silent under this
MD+ conversion. A complete soundtrack pack therefore requires lawfully
supplied replacements for those cues and separately verified speed-shoes
variants. The project records that limitation instead of filling gaps with
copyrighted game or album audio.

## Copyright

Read [docs/LEGAL.md](docs/LEGAL.md). In short: publish the scripts and metadata,
not the generated game or audio. `build/`, `dist/`, ROMs, WAVs, CUEs, and common
disc-image formats are ignored on purpose.

The original tooling in this repository is licensed under
[GPL-3.0-only](LICENSE). See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
for dependency licensing and trademark notices. Contributions are covered by
[CONTRIBUTING.md](CONTRIBUTING.md), the [Code of Conduct](CODE_OF_CONDUCT.md),
and the [security policy](SECURITY.md).
