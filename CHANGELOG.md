# Changelog

All notable changes to this project will be documented here.

The format is based on Keep a Changelog, and the project uses Semantic
Versioning for its own tooling releases.

## [Unreleased]

### Changed

- Pin the Sonic source dependency to `lloydsmart/msu-md-sonic2` commit
  `b49afdb010090c282e1bb79f18f14a32d1bb7a99`, which contains the game-mode
  dispatch repair submitted upstream as ArcadeTV PR #5. Remove the duplicate
  forge-side source rewrite while preserving the exact audited ROM bytes.

- Mark all 16 enabled Addryu cues as MiSTer-hardware verified, preserving every
  loop point and WAV.
- Promote the repaired REV00 ROM to the audited strict regression baseline:
  checksum `49A0`, SHA-256
  `a1480c1699e80de5dac5b800a463ff1f1cafd4ad73642f6fbf0e09086c5df7fc`.

- Enable Aquatic Ruin Zone MD+ track 07 with the hardware-verified sector
  `828 → 4284` loop.

- Replace `as-sonic` with pinned maintained ASL 1.42 build 306, with bounded
  source syntax conversion preserving the exact hardware-verified ROM hash.

- Rename the project to Sonic 2 MD+ Forge and make its positioning ready for
  additional soundtrack variants without changing the current Addryu profile.

### Added

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
- Rev 0 ROM checksum, signature, size, and SHA-256 verification.
- WAV normalization, sector-aligned trimming, loop candidate detection, loop
  scoring, CUE generation, and MiSTer package assembly.
- Hardware-verified Emerald Hill loop metadata (`292 → 3892`).
- Unit tests, Ruff linting, and GitHub Actions checks.
- Legal, contribution, security, conduct, and third-party documentation.

### Fixed

- Restore the level-select cheat and Death Egg ending transition through the
  pinned `msu-md-sonic2` source's four-byte game-mode dispatch repair, submitted
  upstream as ArcadeTV PR #5. Both REV00 and REV01 passed MiSTer hardware
  verification; the repaired REV00 ROM is the audited production baseline.

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
