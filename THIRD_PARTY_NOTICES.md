# Third-party notices

This repository contains original build tooling and does not vendor the two
source dependencies below. The bootstrap command fetches their exact pinned
commits into the ignored `build/` directory.

## ArcadeTV/msu-md-sonic2

- Repository: <https://github.com/ArcadeTV/msu-md-sonic2>
- Pinned commit: `23d24dda3758a1fd341c01e7f7e94e11780a2608`
- Declared repository license: CC0 1.0 Universal

The project applies a deterministic MD+ conversion to a temporary checkout.
The dependency may contain material whose rights are not granted merely by its
repository license; users remain responsible for lawful use.

## Macroassembler-AS/asl-releases

- Repository: <https://github.com/Macroassembler-AS/asl-releases>
- Pinned commit: `c7155b4fd3d33110f0eb098dede4295a8c008772`
- Release: ASL 1.42 build 306 (`asl-current-142-bld306`)
- Declared repository license: GNU General Public License version 2

The assembler is fetched and built as a separate executable. It is not linked
into, vendored by, or redistributed with this project's Python tooling.

## FFmpeg

FFmpeg is a user-installed command-line dependency. Its exact licensing depends
on how the user's binary was configured. No FFmpeg binary or library is
distributed by this repository.

Sonic the Hedgehog, Sonic the Hedgehog 2, Sega, Addryu, MiSTer, and other names
belong to their respective owners. No endorsement is implied.
