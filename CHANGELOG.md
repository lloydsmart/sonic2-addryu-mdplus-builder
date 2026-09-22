# Changelog

All notable changes to this project will be documented here.

The format is based on Keep a Changelog, and the project uses Semantic
Versioning for its own tooling releases.

## [Unreleased]

### Added

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

- Close the MD+ overlay immediately after every command transaction, avoiding
  corruption when live Sonic 2 code crosses the MD+ register window.
