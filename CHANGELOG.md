# Changelog

All notable changes to this project will be documented here.

The format is based on Keep a Changelog, and the project uses Semantic
Versioning for its own tooling releases.

## [Unreleased]

### Added

- Experimental Stage 5 modern live MD+ routing with acknowledged native-to-MD+
  ownership transfer, native temporary cues, pause/resume, fade/stop, and
  255-VInt extra-life ducking through all six upstream paths. Fixed-size
  PlaySound/PlaySound2, VInt, reset and direct pause hooks preserve upstream
  layout. The Stage 3 primitives and Stage 4 Z80 image remain byte-identical.
  Exact binary audits and compiled CPU tests cover the new layer. Output is
  `build/sonic2-modern-mdplus.md`; legacy defaults and packaging are unchanged.
  The required MiSTer FPGA hardware gate has passed, covering native/MD+
  transitions, SFX, controls, progression, warm reset and Death Egg/ending.
  The optional missing-WAV robustness test was not run.

- Inert Stage 4 modern music-only Z80 handoff using private F7 and ACK A5.
  Native gameplay and the disconnected Stage 3 MD+ backend are preserved.
  Hash-locked preparation audits all three changed upstream files. Compiled
  CPU tests cover the loader, paused handoff, SFX preservation/progress,
  mailbox contention, retries and RAM boundaries. Stage 5 will add ownership
  and connect live routing.
- Targeted modern three-slot SFX copy correction, required to preserve Music1,
  and Saxman loader correction, required to load every modified Z80 byte.
  Global `fixBugs=1` remains unsupported. All changes stay on the experimental
  modern path; the production transformer and ROM remain unchanged.

- Internal Stage 3 modern MD+ backend with the production sixteen-track Addryu
  routing policy and five isolated control primitives in the appended Forge
  region. Gameplay remains entirely native; the backend is disconnected until
  Stage 4 adds the handoff and Stage 5 adds ownership/routing. Exact binary audits and direct
  CPU tests cover transactions, routes and unchanged native PlayMusic behaviour.
  Production MD+ remains the legacy/default path.

- Internal `prepare-modern` and `build-modern` migration scaffold with a fixed
  PlayMusic trampoline and Forge-owned implementation in an appended ROM region.
  The Stage 2 seam keeps all music native, with no runtime state or MD+ commands.
  Strict binary checks and CPU tests protect native mailbox, register and condition-code
  behaviour; stock modern and default production MD+ builds remain separate.

- Explicit experimental `bootstrap-modern` and `build-stock-modern` commands
  for pinned current sonicretro/s2disasm, using upstream's Lua build and exact
  stock REV01 size, MD5, and SHA-256 verification. The modern source is not yet
  MD+ capable; all production MD+ commands retain their existing source path.

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
