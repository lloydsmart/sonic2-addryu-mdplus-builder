from __future__ import annotations

import hashlib
import shutil
import tempfile
from pathlib import Path

from .common import BUILD, DEPENDENCIES, BuildError, load_json, require_program, run
from .source import _clone_at, _git_output

SOURCE_MODERN_DIR = BUILD / "source-modern"
STOCK_MODERN_ROM_PATH = BUILD / "sonic2-stock-modern.md"
STOCK_ROM_SIZE = 1_048_576
STOCK_ROM_MD5 = "9feeb724052c39982d432a7851c98d3e"
STOCK_ROM_SHA256 = "193bc4064ce0daf27ea9e908ed246d87ec576cc294833badebb590b6ad8e8f6b"


def bootstrap_modern(*, local_source: Path | None = None) -> None:
    dependency = load_json(DEPENDENCIES)["source_modern"]
    _clone_at(dependency["url"], dependency["commit"], SOURCE_MODERN_DIR, local_source)


def verify_stock_modern(path: Path) -> dict[str, str | int]:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise BuildError(f"Cannot read stock ROM {path}: {exc}") from exc
    size = len(data)
    md5 = hashlib.md5(data, usedforsecurity=False).hexdigest()
    sha256 = hashlib.sha256(data).hexdigest()
    if (size, md5, sha256) != (STOCK_ROM_SIZE, STOCK_ROM_MD5, STOCK_ROM_SHA256):
        raise BuildError(
            "Modern stock ROM differs from the audited REV01 target: "
            f"size={size}, md5={md5}, sha256={sha256}"
        )
    return {"size": size, "md5": md5, "sha256": sha256}


def build_stock_modern() -> dict[str, str | int]:
    lua = require_program("lua")
    run([lua, "-e", 'local major, minor = _VERSION:match("(%d+)%.(%d+)"); '
         'assert(tonumber(major) > 5 or (tonumber(major) == 5 and tonumber(minor) >= 3), '
         '"Modern stock build requires Lua 5.3 or newer")'])
    if not SOURCE_MODERN_DIR.is_dir():
        raise BuildError("Modern source is not fetched; run bootstrap-modern first")
    dependency = load_json(DEPENDENCIES)["source_modern"]
    head = _git_output(SOURCE_MODERN_DIR, "rev-parse", "HEAD")
    if head != dependency["commit"]:
        raise BuildError(f"{SOURCE_MODERN_DIR} is at {head}, expected {dependency['commit']}")

    # Clone only committed files: local edits and stale generated ROMs cannot
    # affect the build, and upstream's generated files stay out of the input.
    with tempfile.TemporaryDirectory(prefix="stock-modern-", dir=BUILD) as directory:
        work = Path(directory) / "source"
        _clone_at(dependency["url"], dependency["commit"], work, SOURCE_MODERN_DIR)
        run([lua, "build.lua"], cwd=work)
        built = work / "s2built.bin"
        result = verify_stock_modern(built)
        shutil.copy2(built, STOCK_MODERN_ROM_PATH)
    return result
