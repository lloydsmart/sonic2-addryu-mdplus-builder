# Security policy

## Supported versions

Until the first stable release, only the latest `main` branch is supported.

## Reporting a vulnerability

Use GitHub's private vulnerability-reporting feature if it is enabled. If it is
not available, contact the repository owner privately through the contact
method on the `lloydsmart` GitHub profile. Do not publish exploitable details in
an issue.

Include the affected revision, reproduction steps, impact, and any suggested
mitigation. You should normally receive an acknowledgement within seven days.

## Supply-chain scope

The build intentionally executes code from two pinned third-party Git commits
and invokes local Git, Make, GCC, Python, and FFmpeg installations. Review
dependency-pin changes carefully. The project does not download ROMs or audio,
and it must never upload generated copyrighted material from CI.
