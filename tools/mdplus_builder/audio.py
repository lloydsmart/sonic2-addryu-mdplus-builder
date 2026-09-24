from __future__ import annotations

import json
import math
import subprocess
import tempfile
import wave
from array import array
from dataclasses import dataclass
from pathlib import Path

from .common import AUDIO_DIR, BuildError, load_json, require_program, run, sha256

RATE = 44_100
CHANNELS = 2
WIDTH = 2
FRAMES_PER_SECTOR = 588


@dataclass(frozen=True)
class AudioConversionPlan:
    sample_rate_conversion: bool
    channel_conversion: bool
    channel_conversion_method: str | None
    format_or_codec_conversion: bool
    precision_reduction: bool
    precision_expansion: bool
    native_signed_16_bit_pcm: bool
    resampler: str | None
    soxr_precision: int | None
    dither: str | None
    speed: float
    filters: tuple[str, ...]


def _reported_positive_int(value: object) -> int | None:
    try:
        result = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def probe_audio(path: Path) -> dict[str, int | str | None]:
    if not path.is_file():
        raise BuildError(f"Input file not found: {path}")
    ffprobe = require_program("ffprobe")

    try:
        completed = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                (
                    "stream=codec_name,sample_fmt,sample_rate,channels,channel_layout,"
                    "bits_per_sample,bits_per_raw_sample:format=format_name"
                ),
                "-of",
                "json",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or str(exc)
        raise BuildError(f"Unable to probe audio file {path}: {detail}") from exc
    except OSError as exc:
        raise BuildError(f"Unable to probe audio file {path}: {exc}") from exc

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise BuildError(f"Unable to probe audio file {path}: ffprobe returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise BuildError(f"Unable to probe audio file {path}: ffprobe returned malformed data")
    streams = payload.get("streams", [])
    if not isinstance(streams, list) or len(streams) != 1 or not isinstance(streams[0], dict):
        count = len(streams) if isinstance(streams, list) else 0
        raise BuildError(f"{path}: expected an audio stream, found {count}")

    stream = streams[0]
    format_info = payload.get("format", {})
    container_format = (
        str(format_info.get("format_name") or "unknown")
        if isinstance(format_info, dict)
        else "unknown"
    )
    try:
        sample_rate = int(stream["sample_rate"])
        channels = int(stream["channels"])
    except (KeyError, TypeError, ValueError) as exc:
        raise BuildError(f"{path}: ffprobe did not report a usable sample rate/channel count") from exc

    if sample_rate <= 0 or channels <= 0:
        raise BuildError(f"{path}: ffprobe reported an invalid sample rate/channel count")

    sample_format = str(stream.get("sample_fmt") or "unknown")
    bits_per_sample = _reported_positive_int(stream.get("bits_per_sample"))
    bits_per_raw_sample = _reported_positive_int(stream.get("bits_per_raw_sample"))

    inferred_bits = {
        "u8": 8,
        "u8p": 8,
        "s16": 16,
        "s16p": 16,
        "s32": 32,
        "s32p": 32,
        "s64": 64,
        "s64p": 64,
        "flt": 32,
        "fltp": 32,
        "dbl": 64,
        "dblp": 64,
    }.get(sample_format)
    effective_bit_depth = bits_per_raw_sample or bits_per_sample or inferred_bits

    return {
        "codec": str(stream.get("codec_name") or "unknown"),
        "container_format": container_format,
        "sample_format": sample_format,
        "sample_rate": sample_rate,
        "channels": channels,
        "channel_layout": str(stream.get("channel_layout") or "unknown"),
        "bits_per_sample": bits_per_sample,
        "bits_per_raw_sample": bits_per_raw_sample,
        "effective_bit_depth": effective_bit_depth,
    }


def build_conversion_plan(
    source_info: dict[str, int | str | None],
    *,
    trim_start_sector: int = 0,
    end_sector: int | None = None,
    speed: float = 1.0,
) -> AudioConversionPlan:
    if not 0.5 <= speed <= 2.0:
        raise BuildError("Speed must be between 0.5 and 2.0")
    if (
        isinstance(trim_start_sector, bool)
        or not isinstance(trim_start_sector, int)
        or trim_start_sector < 0
    ):
        raise BuildError("trim_start_sector must be a non-negative integer")
    if end_sector is not None and end_sector <= 0:
        raise BuildError("End sector must be positive")

    sample_rate = int(source_info["sample_rate"])
    channels = int(source_info["channels"])
    if channels > CHANNELS:
        raise BuildError(
            f"Source has {channels} channels; only mono or stereo input is supported "
            "because no surround downmix policy is defined"
        )

    codec = str(source_info["codec"])
    sample_format = str(source_info["sample_format"])
    effective_bit_depth = source_info["effective_bit_depth"]
    native_signed_16_bit_pcm = (
        codec in {"pcm_s16le", "pcm_s16be"}
        and sample_format in {"s16", "s16p"}
        and effective_bit_depth == WIDTH * 8
    )
    sample_rate_conversion = sample_rate != RATE
    channel_conversion = channels != CHANNELS
    format_or_codec_conversion = not (
        codec == "pcm_s16le"
        and sample_format in {"s16", "s16p"}
        and effective_bit_depth == WIDTH * 8
    )
    floating_point_source = sample_format in {"flt", "fltp", "dbl", "dblp"}
    precision_reduction = floating_point_source or (
        isinstance(effective_bit_depth, int) and effective_bit_depth > WIDTH * 8
    )
    precision_expansion = (
        not floating_point_source
        and isinstance(effective_bit_depth, int)
        and effective_bit_depth < WIDTH * 8
    )
    speed_conversion = speed != 1.0
    dither_required = precision_reduction or sample_rate_conversion or speed_conversion

    filters: list[str] = []
    if speed_conversion:
        filters.append(f"atempo={speed:.17g}")

    if dither_required:
        options = [f"osr={RATE}", "osf=s16"]
        if sample_rate_conversion:
            options.extend(("resampler=soxr", "precision=33"))
        options.append("dither_method=triangular_hp")
        filters.append("aresample=" + ":".join(options))
    elif sample_format not in {"s16", "s16p"}:
        filters.append("aformat=sample_fmts=s16")

    if channel_conversion:
        filters.append("pan=stereo|c0=c0|c1=c0")

    trim_options: list[str] = []
    if trim_start_sector:
        trim_options.append(
            f"start_sample={trim_start_sector * FRAMES_PER_SECTOR}"
        )
    if end_sector is not None:
        trim_options.append(
            f"end_sample={(trim_start_sector + end_sector) * FRAMES_PER_SECTOR}"
        )
    if trim_options:
        filters.append("atrim=" + ":".join(trim_options))
    if filters:
        filters.append("asetpts=PTS-STARTPTS")

    return AudioConversionPlan(
        sample_rate_conversion=sample_rate_conversion,
        channel_conversion=channel_conversion,
        channel_conversion_method="duplicate_mono" if channel_conversion else None,
        format_or_codec_conversion=format_or_codec_conversion,
        precision_reduction=precision_reduction,
        precision_expansion=precision_expansion,
        native_signed_16_bit_pcm=native_signed_16_bit_pcm,
        resampler="soxr" if sample_rate_conversion else None,
        soxr_precision=33 if sample_rate_conversion else None,
        dither="triangular_hp" if dither_required else None,
        speed=speed,
        filters=tuple(filters),
    )


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
    info["codec"] = "pcm_s16le"
    info["sample_format"] = "s16"
    info["bits_per_sample"] = WIDTH * 8
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
            trim_start_sector = entry.get("trim_start_sector", 0)
            if (
                isinstance(trim_start_sector, bool)
                or not isinstance(trim_start_sector, int)
                or trim_start_sector < 0
            ):
                raise BuildError(
                    f"Track {number}: trim_start_sector must be a non-negative integer"
                )
            if mode == "loop":
                start, end = entry.get("loop_start_sector"), entry.get("loop_end_sector")
                if not isinstance(start, int) or not isinstance(end, int) or not (0 <= start < end):
                    raise BuildError(f"Track {number}: invalid loop sector pair {start!r} -> {end!r}")
    return manifest


def _copy_wave_frames(
    source_path: Path,
    destination: Path,
    keep_frames: int,
    *,
    start_frame: int = 0,
) -> None:
    with tempfile.NamedTemporaryFile(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp.wav",
        delete=False,
    ) as temporary_handle:
        temporary = Path(temporary_handle.name)
    try:
        with wave.open(str(source_path), "rb") as source, wave.open(str(temporary), "wb") as target:
            target.setnchannels(source.getnchannels())
            target.setsampwidth(source.getsampwidth())
            target.setframerate(source.getframerate())
            target.setcomptype(source.getcomptype(), source.getcompname())

            source.setpos(start_frame)
            bytes_per_frame = source.getnchannels() * source.getsampwidth()
            remaining = keep_frames
            while remaining:
                requested = min(remaining, 65_536)
                data = source.readframes(requested)
                if not data:
                    raise BuildError(f"{source_path}: unexpected end of WAV while copying")
                frames_read = len(data) // bytes_per_frame
                if frames_read != requested or len(data) % bytes_per_frame:
                    raise BuildError(f"{source_path}: incomplete PCM frame data")
                target.writeframesraw(data)
                remaining -= frames_read

        temporary.replace(destination)
    except (OSError, wave.Error) as exc:
        raise BuildError(f"Unable to copy PCM WAV {source_path}: {exc}") from exc
    finally:
        if temporary.exists():
            temporary.unlink()


def _copy_native_wave(
    source: Path,
    destination: Path,
    end_sector: int | None,
    trim_start_sector: int = 0,
) -> int:
    info = inspect_wave(source)
    expected = {
        "channels": CHANNELS,
        "sample_width": WIDTH,
        "sample_rate": RATE,
        "compression": "NONE",
    }
    if any(info[key] != value for key, value in expected.items()):
        raise BuildError(f"{source}: ffprobe and WAV properties disagree about native PCM format")

    frames = int(info["frames"])
    start_frame = trim_start_sector * FRAMES_PER_SECTOR
    if start_frame > frames:
        raise BuildError(
            f"{source}: has {frames} frames, fewer than the requested "
            f"start frame {start_frame}"
        )

    remaining_frames = frames - start_frame
    keep_frames = (
        end_sector * FRAMES_PER_SECTOR
        if end_sector is not None
        else remaining_frames - remaining_frames % FRAMES_PER_SECTOR
    )
    if keep_frames > remaining_frames:
        raise BuildError(
            f"{source}: has {remaining_frames} frames after start trim, "
            f"fewer than the requested {keep_frames}"
        )

    _copy_wave_frames(
        source,
        destination,
        keep_frames,
        start_frame=start_frame,
    )
    return remaining_frames - keep_frames if end_sector is None else 0


def _trim_to_whole_sectors(path: Path) -> int:
    frames = int(inspect_wave(path)["frames"])
    remainder = frames % FRAMES_PER_SECTOR
    if remainder:
        _copy_wave_frames(path, path, frames - remainder)
    return remainder


def _is_direct_copy_wave(
    path: Path,
    plan: AudioConversionPlan,
    source_info: dict[str, int | str | None],
) -> bool:
    if (
        source_info["codec"] != "pcm_s16le"
        or not plan.native_signed_16_bit_pcm
        or plan.channel_conversion
        or plan.sample_rate_conversion
        or plan.speed != 1.0
    ):
        return False
    try:
        info = inspect_wave(path)
    except BuildError:
        return False
    return (
        info["channels"] == CHANNELS
        and info["sample_width"] == WIDTH
        and info["sample_rate"] == RATE
        and info["compression"] == "NONE"
    )


def check_ffmpeg_audio_capabilities() -> dict[str, str | int | bool]:
    ffmpeg = require_program("ffmpeg")
    ffprobe = require_program("ffprobe")
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "aevalsrc=sin(2*PI*997*t):s=48000:d=0.02",
        "-af",
        (
            f"aresample=osr={RATE}:osf=s16:resampler=soxr:precision=33:"
            "dither_method=triangular_hp"
        ),
        "-f",
        "null",
        "-",
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or str(exc)
        raise BuildError(
            "FFmpeg audio capability check failed; SoXR with precision=33 and "
            f"triangular_hp dithering is required: {detail}"
        ) from exc
    except OSError as exc:
        raise BuildError(f"Unable to run FFmpeg audio capability check: {exc}") from exc
    return {
        "ffmpeg": ffmpeg,
        "ffprobe": ffprobe,
        "soxr": True,
        "soxr_precision": 33,
        "dither": "triangular_hp",
    }


def convert_audio_file(
    source: Path,
    destination: Path,
    *,
    trim_start_sector: int = 0,
    end_sector: int | None = None,
    speed: float = 1.0,
) -> dict:
    if not source.is_file():
        raise BuildError(f"Input file not found: {source}")
    if source.suffix.lower() != ".wav":
        raise BuildError(f"Source audio must be a WAV file with a .wav extension: {source}")
    source_info = probe_audio(source)
    if source_info["container_format"] != "wav":
        raise BuildError(
            f"Source audio must be a WAV file; ffprobe identified "
            f"{source_info['container_format']!r}: {source}"
        )
    plan = build_conversion_plan(
        source_info,
        trim_start_sector=trim_start_sector,
        end_sector=end_sector,
        speed=speed,
    )
    if source.resolve() == destination.resolve():
        raise BuildError("Input and output audio paths must be different")
    destination.parent.mkdir(parents=True, exist_ok=True)

    if _is_direct_copy_wave(source, plan, source_info):
        discarded_frames = _copy_native_wave(
            source,
            destination,
            end_sector,
            trim_start_sector,
        )
        method = "direct_pcm_wave_copy"
    else:
        ffmpeg = require_program("ffmpeg")
        command: list[str | Path] = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            source,
            "-map",
            "0:a:0",
            "-map_metadata",
            "-1",
            "-fflags",
            "+bitexact",
            "-flags:a",
            "+bitexact",
        ]
        if plan.filters:
            command.extend(("-af", ",".join(plan.filters)))
        command.extend(("-c:a", "pcm_s16le", destination))
        run(command)
        discarded_frames = 0 if end_sector is not None else _trim_to_whole_sectors(destination)
        method = "ffmpeg"

    info = validate_wave(destination, end_sector=end_sector)
    info["source"] = source_info
    info["conversion"] = {
        "method": method,
        "sample_rate_conversion": plan.sample_rate_conversion,
        "channel_conversion": plan.channel_conversion,
        "channel_conversion_method": plan.channel_conversion_method,
        "format_or_codec_conversion": plan.format_or_codec_conversion,
        "precision_reduction": plan.precision_reduction,
        "precision_expansion": plan.precision_expansion,
        "resampler": plan.resampler,
        "soxr_precision": plan.soxr_precision,
        "dither": plan.dither,
        "speed": plan.speed,
        "trim_start_sector": trim_start_sector,
        "discarded_trailing_frames": discarded_frames,
    }
    return info


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
        trim_start_sector = entry.get("trim_start_sector", 0)
        end_sector = entry.get("loop_end_sector")
        info = convert_audio_file(
            source,
            destination,
            trim_start_sector=trim_start_sector,
            end_sector=end_sector,
            speed=speed,
        )
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
