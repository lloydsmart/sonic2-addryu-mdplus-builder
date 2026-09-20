# Contributing

Contributions to the build tooling, validation, documentation, and independently
measured loop metadata are welcome.

## Before opening a change

1. Create a branch from `main`.
2. Keep copyrighted ROM, game, and soundtrack data outside the repository.
3. Run the checks listed in `AGENTS.md`.
4. Explain how the change was tested.

For a loop-point contribution, include the source track name, proposed start
and end sectors, detection method, listening-test result, and MiSTer/core version
used for final verification. Waveform similarity alone is not sufficient.

## Development setup

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[lint]'
ruff check .
python -m unittest discover -s tests -v
```

The supported integration environment is Linux with Git, Make, GCC, Python
3.10 or newer, and FFmpeg. See the README for the complete build workflow.

## Pull requests

Keep pull requests focused and describe any legal/provenance implications.
Generated ROMs, WAVs, CUEs, disc images, and MiSTer output directories must not
be attached to issues, pull requests, or releases.

By contributing, you agree that your contribution is licensed under
GPL-3.0-only, the repository's license.
