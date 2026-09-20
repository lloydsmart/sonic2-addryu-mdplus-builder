from __future__ import annotations

import math
import wave
from array import array
from pathlib import Path

from .common import AUDIO_DIR, BuildError, load_json, require_program, run, sha256

RATE = 44_100
CHANNELS = 2
WIDTH = 2
FRAMES_PER_SECTOR = 588


def _track_name(number: int) -> str:
    return f"track{number:02d}.wav"


def inspect_wave(path: Path) -> dict[str, int | str]:
    try:
        with wave.open(str(path), "rb") as wav:
            result = {
                "channels": wav.getnchannels(),
                "sample_width": wav.getsampwidth(),
                "sample_rate": wav.getframerate(),
                "frames": wav.getnframes(),
                "compression": wav.getcomptype(),
            }
    except (OSError, wave.Error) as exc:
        raise BuildError(f"Cannot read WAV {path}: {exc}") from exc
    return result


def validate_wave(path: Path, *, end_sector: int | None = None) -> dict[str, int | str]:
    info = inspect_wave(path)
    expected = {
        "channels": CHANNELS,
        "sample_width": WIDTH,
        "sample_rate": RATE,
        "compression": "NONE",
    }
    for key, value in expected.items():
        if info[key] != value:
            raise BuildError(f"{path}: {key} is {info[key]!r}, expected {value!r}")
    if int(info["frames"]) % FRAMES_PER_SECTOR:
        raise BuildError(f"{path}: length is not aligned to a 75 Hz CD sector")
    if end_sector is not None and int(info["frames"]) != end_sector * FRAMES_PER_SECTOR:
        raise BuildError(
            f"{path}: has {info['frames']} frames, expected {end_sector * FRAMES_PER_SECTOR}"
        )
    info["sectors"] = int(info["frames"]) // FRAMES_PER_SECTOR
    info["sha256"] = sha256(path)
    return info


def validate_manifest(manifest_path: Path) -> dict:
    manifest = load_json(manifest_path)
    if manifest.get("schema") != 1 or not isinstance(manifest.get("tracks"), list):
        raise BuildError("Unsupported or malformed track manifest")
    seen: set[int] = set()
    for entry in manifest["tracks"]:
        number = entry.get("track")
        if not isinstance(number, int) or not 1 <= number <= 99 or number in seen:
            raise BuildError(f"Invalid or duplicate track number: {number!r}")
        seen.add(number)
        mode = entry.get("mode")
        if mode not in {"loop", "noloop"}:
            raise BuildError(f"Track {number}: mode must be loop or noloop")
        if entry.get("enabled"):
            source = entry.get("source")
            if not source:
                raise BuildError(f"Track {number}: enabled entry has no source filename")
            if Path(source).name != source:
                raise BuildError(f"Track {number}: source must be a filename, not a path")
            if mode == "loop":
                start, end = entry.get("loop_start_sector"), entry.get("loop_end_sector")
                if not isinstance(start, int) or not isinstance(end, int) or not (0 <= start < end):
                    raise BuildError(f"Track {number}: invalid loop sector pair {start!r} -> {end!r}")
    return manifest


def convert_audio_file(
    source: Path,
    destination: Path,
    *,
    end_sector: int | None = None,
    speed: float = 1.0,
) -> dict[str, int | str]:
    require_program("ffmpeg")
    if not source.is_file():
        raise BuildError(f"Input file not found: {source}")
    if not 0.5 <= speed <= 2.0:
        raise BuildError("Speed must be between 0.5 and 2.0")
    if end_sector is not None and end_sector <= 0:
        raise BuildError("End sector must be positive")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Sector/sample arithmetic is defined at the final MD+ format. Normalize
    # rate and channel layout before speed changes or sample-count trimming.
    filters = ["aresample=44100", "aformat=sample_fmts=s16:channel_layouts=stereo"]
    if not math.isclose(speed, 1.0):
        filters.append(f"atempo={speed:.10g}")
    if end_sector is not None:
        filters.append(f"atrim=end_sample={end_sector * FRAMES_PER_SECTOR}")
    filters.append("asetpts=PTS-STARTPTS")
    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            source,
            "-af",
            ",".join(filters),
            "-ar",
            str(RATE),
            "-ac",
            str(CHANNELS),
            "-c:a",
            "pcm_s16le",
            destination,
        ]
    )
    return validate_wave(destination, end_sector=end_sector)


def prepare_audio(manifest_path: Path, input_dir: Path, output_dir: Path = AUDIO_DIR) -> list[dict]:
    manifest = validate_manifest(manifest_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for entry in manifest["tracks"]:
        if not entry.get("enabled"):
            continue
        number = int(entry["track"])
        source = input_dir / entry["source"]
        if not source.is_file():
            raise BuildError(f"Track {number}: input file not found: {source}")
        destination = output_dir / _track_name(number)
        speed = float(entry.get("speed", 1.0))
        end_sector = entry.get("loop_end_sector")
        info = convert_audio_file(source, destination, end_sector=end_sector, speed=speed)
        results.append({"track": number, "path": str(destination), **info})
    if not results:
        raise BuildError("Manifest has no enabled tracks")
    return results


def _parse_range(value: str) -> tuple[int, int]:
    try:
        low, high = (float(part) for part in value.split(":", 1))
    except ValueError as exc:
        raise BuildError(f"Range must be START:END seconds, got {value!r}") from exc
    if low < 0 or high <= low:
        raise BuildError(f"Invalid range: {value!r}")
    return round(low * 75), round(high * 75)


def _read_mono(path: Path) -> array:
    validate_wave(path)
    with wave.open(str(path), "rb") as wav:
        samples = array("h")
        samples.frombytes(wav.readframes(wav.getnframes()))
    if samples.itemsize != 2:
        raise BuildError("This Python build has an unexpected short integer size")
    # WAV PCM is little-endian. byteswap only on big-endian hosts.
    import sys

    if sys.byteorder == "big":
        samples.byteswap()
    mono = array("h", ((samples[i] + samples[i + 1]) // 2 for i in range(0, len(samples), 2)))
    return mono


def detect_loops(
    path: Path,
    start_range: str,
    end_range: str,
    *,
    top: int = 10,
    window_ms: int = 300,
) -> list[tuple[float, int, int]]:
    """Rank sector-aligned repeated-boundary candidates within user-supplied ranges.

    This is deliberately a candidate finder, not an automatic musical decision.
    It compares sparse samples around each boundary, then reports the lowest
    normalized RMS errors for listening and hardware verification.
    """
    mono = _read_mono(path)
    starts = _parse_range(start_range)
    ends = _parse_range(end_range)
    radius = max(1, round(RATE * window_ms / 2000))
    offsets = [round(-radius + (2 * radius * i / 23)) for i in range(24)]

    def vector(sector: int) -> tuple[int, ...] | None:
        centre = sector * FRAMES_PER_SECTOR
        positions = [centre + offset for offset in offsets]
        if positions[0] < 0 or positions[-1] >= len(mono):
            return None
        return tuple(mono[pos] for pos in positions)

    start_vectors = [(sector, vector(sector)) for sector in range(*starts)]
    end_vectors = [(sector, vector(sector)) for sector in range(*ends)]
    start_vectors = [(sector, vec) for sector, vec in start_vectors if vec is not None]
    end_vectors = [(sector, vec) for sector, vec in end_vectors if vec is not None]
    if not start_vectors or not end_vectors:
        raise BuildError("Search ranges do not contain valid audio boundaries")

    best: list[tuple[float, int, int]] = []
    for start_sector, left in start_vectors:
        for end_sector, right in end_vectors:
            if end_sector <= start_sector:
                continue
            error = sum((a - b) ** 2 for a, b in zip(left, right, strict=True)) / len(left)
            energy = (sum(a * a + b * b for a, b in zip(left, right, strict=True)) / (2 * len(left))) + 1.0
            score = math.sqrt(error / energy)
            candidate = (score, start_sector, end_sector)
            if len(best) < top:
                best.append(candidate)
                best.sort()
            elif candidate < best[-1]:
                best[-1] = candidate
                best.sort()
    return best


def score_loop(path: Path, start_sector: int, end_sector: int, *, window_ms: int = 300) -> float:
    if not 0 < start_sector < end_sector:
        raise BuildError("Loop sectors must satisfy 0 < start < end")
    mono = _read_mono(path)
    start_frame = start_sector * FRAMES_PER_SECTOR
    end_frame = end_sector * FRAMES_PER_SECTOR
    if end_frame > len(mono):
        raise BuildError(f"Loop end is past the audio length ({len(mono) // FRAMES_PER_SECTOR} sectors)")
    window = max(1, round(RATE * window_ms / 1000))
    if start_frame < window:
        raise BuildError("Loop start is too early for the requested comparison window")
    left = mono[start_frame - window : start_frame]
    right = mono[end_frame - window : end_frame]
    error = sum((a - b) ** 2 for a, b in zip(left, right, strict=True)) / len(left)
    energy = (sum(a * a + b * b for a, b in zip(left, right, strict=True)) / (2 * len(left))) + 1.0
    return math.sqrt(error / energy)
