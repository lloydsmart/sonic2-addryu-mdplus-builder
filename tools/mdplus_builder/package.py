from __future__ import annotations

import json
import shutil
from pathlib import Path

from .audio import _track_name, validate_manifest, validate_wave
from .common import AUDIO_DIR, DIST, LEGACY_ROM_PATH, ROM_PATH, BuildError, sha256
from .modern import verify_modern
from .source import verify_rom


def cue_text(manifest: dict) -> str:
    lines: list[str] = []
    for entry in sorted((item for item in manifest["tracks"] if item.get("enabled")), key=lambda x: x["track"]):
        number = int(entry["track"])
        lines.extend(
            [
                f'FILE "{_track_name(number)}" WAVE',
                f"  TRACK {number:02d} AUDIO",
                "    INDEX 01 00:00:00",
            ]
        )
        if entry["mode"] == "loop":
            lines.append(f"    REM LOOP {entry['loop_start_sector']}")
        else:
            lines.append("    REM NOLOOP")
    return "\n".join(lines) + "\n"


def assemble(
    manifest_path: Path, *, rom_path: Path | None = None, audio_dir: Path = AUDIO_DIR, legacy: bool = False,
) -> Path:
    manifest = validate_manifest(manifest_path)
    rom_path = rom_path or (LEGACY_ROM_PATH if legacy else ROM_PATH)
    verifier = verify_rom if legacy else verify_modern
    verifier(rom_path, strict_regression=True)
    basename = manifest.get("rom_basename")
    if (
        not isinstance(basename, str)
        or not basename.strip()
        or basename in {".", ".."}
        or any(char in basename for char in '/\\')
    ):
        raise BuildError("rom_basename must be a non-empty filename-safe string")
    destination = DIST / basename
    expected_names = {
        f"{basename}.md",
        f"{basename}.cue",
        "SHA256SUMS.json",
        *(_track_name(int(item["track"])) for item in manifest["tracks"] if item.get("enabled")),
    }
    if destination.exists():
        unexpected = sorted(item.name for item in destination.iterdir() if item.name not in expected_names)
        if unexpected:
            raise BuildError(
                f"Output directory contains stale or unexpected files: {', '.join(unexpected)}; run clean first"
            )
    destination.mkdir(parents=True, exist_ok=True)
    output_rom = destination / f"{basename}.md"
    output_cue = destination / f"{basename}.cue"
    shutil.copy2(rom_path, output_rom)
    checksums = {output_rom.name: sha256(output_rom)}
    for entry in manifest["tracks"]:
        if not entry.get("enabled"):
            continue
        number = int(entry["track"])
        source = audio_dir / _track_name(number)
        validate_wave(source, end_sector=entry.get("loop_end_sector"))
        target = destination / source.name
        shutil.copy2(source, target)
        checksums[target.name] = sha256(target)
    output_cue.write_text(cue_text(manifest), encoding="utf-8", newline="\n")
    checksums[output_cue.name] = sha256(output_cue)
    (destination / "SHA256SUMS.json").write_text(
        json.dumps(dict(sorted(checksums.items())), indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return destination
