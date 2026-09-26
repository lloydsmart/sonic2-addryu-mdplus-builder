# Changelog

All notable changes to this project will be documented here.

The format is based on Keep a Changelog, and the project uses Semantic
Versioning for its own tooling releases.

## [Unreleased]

## [2.0.0] - 2026-09-25

### Changed

- Promote the hardware-verified current-s2disasm REV01 implementation to the
  default bootstrap, source, ROM, full-build, verification and packaging paths.
  The canonical ROM is `build/sonic2-mdplus.md`, byte-identical to Stage 5
  (`BE41`, SHA-256 `bd12138cd478596e4d294a06f573a98a6d37747dfe58d726ca62cf50dc3a8c44`).
  Keep explicit `--legacy` / `*-legacy` fallback commands and the prior ROM
  identity under `build/sonic2-legacy-mdplus.md`. Retain modern command aliases
  and the old modern filename as a symlink to the canonical ROM.
- Require the selected implementation's exact regression identity when packaging,
  including rejection of a stale legacy ROM under the canonical output name.
  Preserve all audio inputs, Addryu routing, loop metadata and package names.
- Prepare legacy source in a disposable clone, retaining dependency inputs.
  CI now builds and verifies both ROMs and executes the compiled CPU suites;
  include the production Lua wrapper in Python package data.

### Added

The entries below record the migration stages before the production cutover
described above.

- Initially experimental Stage 5 modern live MD+ routing with acknowledged native-to-MD+
  ownership transfer, native temporary cues, pause/resume, fade/stop, and
  255-VInt extra-life ducking through all six upstream paths. Fixed-size
  PlaySound/PlaySound2, VInt, reset and direct pause hooks preserve upstream
  layout. The Stage 3 primitives and Stage 4 Z80 image remain byte-identical.
  Exact binary audits and compiled CPU tests cover the new layer. Its original
  output was `build/sonic2-modern-mdplus.md`; Stage 6 promoted the same ROM to
  the default described above and retained that filename as a compatibility symlink.
  The required MiSTer FPGA hardware gate has passed, covering native/MD+
  transitions, SFX, controls, progression, warm reset and Death Egg/ending.
  The optional missing-WAV robustness test was not run.

- Inert Stage 4 modern music-only Z80 handoff using private F7 and ACK A5.
  At that stage, native gameplay and the disconnected Stage 3 MD+ backend were preserved.
  Hash-locked preparation audits all three changed upstream files. Compiled
  CPU tests cover the loader, paused handoff, SFX preservation/progress,
  mailbox contention, retries and RAM boundaries. Stage 5 subsequently added
  ownership and connected live routing.
- Targeted modern three-slot SFX copy correction, required to preserve Music1,
  and Saxman loader correction, required to load every modified Z80 byte.
  Global `fixBugs=1` remains unsupported. At Stage 4, these changes were confined
  to the experimental modern path; the then-production legacy transformer and
  ROM remained unchanged.

- Internal Stage 3 modern MD+ backend with the production sixteen-track Addryu
  routing policy and five isolated control primitives in the appended Forge
  region. At Stage 3, gameplay remained entirely native; the backend stayed
  disconnected until Stage 4 added the handoff and Stage 5 added ownership/routing.
  Exact binary audits and direct CPU tests cover transactions, routes and
  unchanged native PlayMusic behaviour. Legacy remained the default at that stage.

- Internal `prepare-modern` and `build-modern` migration scaffold with a fixed
  PlayMusic trampoline and Forge-owned implementation in an appended ROM region.
  The Stage 2 seam kept all music native, with no runtime state or MD+ commands.
  Strict binary checks and CPU tests protect native mailbox, register and condition-code
  behaviour; stock modern and the then-default legacy MD+ builds remained separate.

- Initially experimental `bootstrap-modern` and `build-stock-modern` commands
  for pinned current sonicretro/s2disasm, using upstream's Lua build and exact
  stock REV01 size, MD5, and SHA-256 verification. At Stage 1, the modern build
  had no MD+ support; production MD+ commands still selected the legacy source.

## [1.0.0] - 2026-09-24

### Changed

- Trim Sky Chase Zone track 13 by 1162 sectors (15.493333 seconds), shifting its
  output loop coordinates from `11113 → 14082` to `9951 → 12920` while
  preserving the same 2969-sector source loop. The trimmed opening and loop
  were verified end-to-end on MiSTer hardware.

- Pin the Sonic source dependency to `lloydsmart/msu-md-sonic2` commit
  `b49afdb010090c282e1bb79f18f14a32d1bb7a99`, which contains the game-mode
  dispatch repair submitted upstream as ArcadeTV PR #5. Remove the duplicate
  forge-side source rewrite while preserving the exact audited ROM bytes.

- Mark all 16 enabled Addryu cues as MiSTer-hardware verified, preserving every
  loop point and WAV.
- Promote the repaired REV01 ROM to the audited strict regression baseline
  after a complete MiSTer hardware playthrough: checksum `2911`, SHA-256
  `315c69fb84dbca2a31ceffe3face70b4138317feed53feb7e23c6a5ab009205e`.

- Enable Aquatic Ruin Zone MD+ track 07 with the hardware-verified sector
  `828 → 4284` loop.

- Replace `as-sonic` with pinned maintained ASL 1.42 build 306, with bounded
  source syntax conversion preserving the exact hardware-verified ROM hash.

- Rename the project to Sonic 2 MD+ Forge and make its positioning ready for
  additional soundtrack variants without changing the current Addryu profile.

### Added

- Optional `trim_start_sector` audio-manifest support for sector-exact
  final-domain start trimming while keeping loop coordinates relative to the
  generated WAV, with matching native PCM and FFmpeg paths plus unit and
  manifest-integration coverage.

- Deterministic hybrid music: sixteen fixed Addryu cues use MD+, while other
  cues use Sonic 2's original soundtrack. Missing Addryu WAVs never change ROM
  routing; MD+ speed-shoes variants remain disabled.
- Ownership-aware pause, resume, fade and stop, with an acknowledged native
  music-only handoff that preserves SFX and consecutive MD+ transactions.

- Hardware-verified Chemical Plant loop metadata (`1900 → 5500`).
- Source-aware audio normalization with FFprobe reporting, sample-preserving
  native PCM handling, SoXR precision-33 resampling, explicit high-pass
  triangular dithering, and functional FFmpeg capability checks.
- Markdownlint with locked development dependencies and monthly Dependabot updates.
- File-sensitive CI lint steps for Python and Markdown, preserving the required test check.

- Prominent guidance to purchase Addryu's album from Bandcamp and not
  redistribute the original or converted soundtrack.
- Dependabot version updates for Python development dependencies.

- Reproducible, pinned Sonic 2 MD+ source conversion.
- Rev 1 ROM checksum, signature, size, and SHA-256 verification.
- WAV normalization, sector-aligned trimming, loop candidate detection, loop
  scoring, CUE generation, and MiSTer package assembly.
- Hardware-verified Emerald Hill loop metadata (`292 → 3892`).
- Unit tests, Ruff linting, and GitHub Actions checks.
- Legal, contribution, security, conduct, and third-party documentation.

### Fixed

- Restore the level-select cheat and Death Egg ending transition through the
  pinned `msu-md-sonic2` source's four-byte game-mode dispatch repair, submitted
  upstream as ArcadeTV PR #5. Both REV00 and REV01 passed MiSTer hardware
  verification; the repaired REV01 ROM is the audited production baseline.

- Eliminate 33 ASL MOVEQ sign-extension warning sites through guarded symbolic
  signed-byte conversion, preserving the exact ROM and intentional odd-address access.

- Process the final compressed Z80 driver byte; the first hybrid ROM otherwise
  omitted its handoff ACK store and return, causing the first level transition
  to fail on MiSTer. Builds now verify the entire loaded driver against assembly.
- Move handoff completion out of `QueueToPlay` into dedicated Z80 RAM so delayed
  68000 acknowledgement cannot starve normal SFX. Add CPU-level regression
  coverage for the loader, handoff, VInt paths and continued SFX dispatch.

- Keep the second music mailbox out of the SFX-copy loop, where the pinned
  source otherwise writes it into the Z80 voice-table pointer.

- Close the MD+ overlay immediately after every command transaction, avoiding
  corruption when live Sonic 2 code crosses the MD+ register window.
