# Legal and copyright boundaries

This repository contains only original build tooling, configuration, tests,
and documentation. It does not contain Sonic the Hedgehog 2 ROM data, Sega
assets, the Addryu album, converted soundtrack files, or prebuilt assembler
binaries.

Buy the soundtrack directly from
[Addryu on Bandcamp](https://addryu.bandcamp.com/album/sonic-the-hedgehog-2-mega-cd-remix)
and use the WAV download from your purchase. We do not condone unauthorized
distribution of Addryu's work, including converted audio or completed packages.
A purchase does not grant redistribution rights, and our GPL license does not
apply to the soundtrack.

The repository's original tooling is distributed under GPL-3.0-only. That
license applies to this project, not to Sega assets, third-party music, or the
separately fetched dependencies described in `THIRD_PARTY_NOTICES.md`.

Users must supply lawfully obtained audio and, if they use the optional ROM
provenance check, their own clean Sonic 2 cartridge dump. The normal build is
source-based and does not copy that clean ROM into the output.

The build fetches pinned revisions of third-party source projects. Those
projects retain their own notices and licensing terms. A license attached to
disassembly tooling or source code does not grant rights to Sega game assets,
trademarks, or third-party music.

Never upload `build/`, `dist/`, input ROMs, input WAVs, generated WAVs, or the
generated `.md` ROM. The repository ignore rules reject their common file
extensions as an additional guard, but the person publishing a release remains
responsible for checking its contents.
