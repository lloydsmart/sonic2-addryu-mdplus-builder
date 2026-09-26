from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import zlib
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build"
DIST = ROOT / "dist"
DEPENDENCIES = ROOT / "config" / "dependencies.json"
DEFAULT_MANIFEST = ROOT / "config" / "tracks.json"
SOURCE_DIR = BUILD / "source"
ASSEMBLER_DIR = BUILD / "asl"
AUDIO_DIR = BUILD / "audio"
ROM_PATH = BUILD / "sonic2-mdplus.md"
LEGACY_ROM_PATH = BUILD / "sonic2-legacy-mdplus.md"
PREPARED_LEGACY_DIR = BUILD / "prepared-legacy"


class BuildError(RuntimeError):
    pass


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BuildError(f"Cannot read {path}: {exc}") from exc


def run(args: Iterable[str | Path], *, cwd: Path | None = None, env: dict | None = None) -> None:
    printable = [str(item) for item in args]
    print("+", " ".join(printable))
    try:
        subprocess.run(printable, cwd=cwd, env=env, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise BuildError(f"Command failed: {' '.join(printable)}") from exc


def require_program(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise BuildError(f"Required program not found on PATH: {name}")
    return path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def crc32(path: Path) -> str:
    value = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value = zlib.crc32(chunk, value)
    return f"{value & 0xFFFFFFFF:08X}"


def fail(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 1
