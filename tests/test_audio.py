from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
import wave
from array import array
from pathlib import Path

from tools.mdplus_builder.audio import (
    FRAMES_PER_SECTOR,
    build_conversion_plan,
    check_ffmpeg_audio_capabilities,
    convert_audio_file,
    prepare_audio,
    probe_audio,
)
from tools.mdplus_builder.common import BuildError


def _sample_bytes(value: int, width: int) -> bytes:
    limit = 1 << (width * 8 - 1)
    value = max(-limit, min(limit - 1, value))
    return value.to_bytes(width, "little", signed=True)


def _write_pcm_wave(
    path: Path,
    *,
    sample_rate: int = 44_100,
    sample_width: int = 2,
    channels: int = 2,
    frames: int = FRAMES_PER_SECTOR * 3,
) -> bytes:
    payload = bytearray()
    for frame in range(frames):
        for channel in range(channels):
            if sample_width == 1:
                payload.append((frame * 37 + channel * 53) % 256)
            else:
                scale = 1 << (sample_width * 8 - 16)
                base = ((frame * 7919) % 60_001) - 30_000
                fraction = (frame * 17 + channel * 31) % scale if scale > 1 else 0
                payload.extend(_sample_bytes((base + channel * 101) * scale + fraction, sample_width))
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(sample_width)
        wav.setframerate(sample_rate)
        wav.writeframes(payload)
    return bytes(payload)


def _read_pcm16_frames(path: Path) -> list[tuple[int, ...]]:
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        if wav.getsampwidth() != 2:
            raise AssertionError(f"Expected 16-bit PCM test output, got width {wav.getsampwidth()}")
        samples = array("h")
        samples.frombytes(wav.readframes(wav.getnframes()))
    if sys.byteorder == "big":
        samples.byteswap()
    return [tuple(samples[index : index + channels]) for index in range(0, len(samples), channels)]


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg tools required")
class AudioConversionTests(unittest.TestCase):
    def test_probe_reports_pcm_effective_bit_depth(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source-24.wav"
            _write_pcm_wave(source, sample_width=3)

            info = probe_audio(source)

            self.assertEqual(info["codec"], "pcm_s24le")
            self.assertEqual(info["container_format"], "wav")
            self.assertEqual(info["sample_format"], "s32")
            self.assertEqual(info["sample_rate"], 44_100)
            self.assertEqual(info["effective_bit_depth"], 24)
            self.assertEqual(info["channels"], 2)

    def test_native_pcm_is_copied_without_resampling_or_dither(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.wav"
            destination = Path(directory) / "output.wav"
            source_bytes = _write_pcm_wave(source, frames=FRAMES_PER_SECTOR * 2 + 17)

            info = convert_audio_file(source, destination)

            with wave.open(str(destination), "rb") as wav:
                output_bytes = wav.readframes(wav.getnframes())
            self.assertEqual(output_bytes, source_bytes[: FRAMES_PER_SECTOR * 2 * 4])
            self.assertEqual(info["frames"], FRAMES_PER_SECTOR * 2)
            self.assertEqual(info["conversion"]["method"], "direct_pcm_wave_copy")
            self.assertFalse(info["conversion"]["sample_rate_conversion"])
            self.assertFalse(info["conversion"]["channel_conversion"])
            self.assertIsNone(info["conversion"]["channel_conversion_method"])
            self.assertFalse(info["conversion"]["format_or_codec_conversion"])
            self.assertFalse(info["conversion"]["precision_reduction"])
            self.assertFalse(info["conversion"]["precision_expansion"])
            self.assertIsNone(info["conversion"]["resampler"])
            self.assertIsNone(info["conversion"]["dither"])
            self.assertEqual(info["conversion"]["discarded_trailing_frames"], 17)

    def test_native_pcm_start_trim_copies_requested_sector_window(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.wav"
            destination = Path(directory) / "output.wav"
            source_bytes = _write_pcm_wave(
                source,
                frames=FRAMES_PER_SECTOR * 4,
            )

            info = convert_audio_file(
                source,
                destination,
                trim_start_sector=1,
                end_sector=2,
            )

            with wave.open(str(destination), "rb") as wav:
                output_bytes = wav.readframes(wav.getnframes())

            bytes_per_sector = FRAMES_PER_SECTOR * 2 * 2
            self.assertEqual(
                output_bytes,
                source_bytes[bytes_per_sector : bytes_per_sector * 3],
            )
            self.assertEqual(info["frames"], FRAMES_PER_SECTOR * 2)
            self.assertEqual(info["sectors"], 2)
            self.assertEqual(
                info["conversion"]["method"],
                "direct_pcm_wave_copy",
            )

    def test_prepare_audio_applies_manifest_start_trim(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_dir = root / "input"
            output_dir = root / "output"
            manifest_path = root / "tracks.json"
            input_dir.mkdir()

            source_bytes = _write_pcm_wave(
                input_dir / "track.wav",
                frames=FRAMES_PER_SECTOR * 4,
            )

            manifest_path.write_text(
                json.dumps(
                    {
                        "schema": 1,
                        "tracks": [
                            {
                                "track": 13,
                                "enabled": True,
                                "source": "track.wav",
                                "mode": "loop",
                                "trim_start_sector": 1,
                                "loop_start_sector": 1,
                                "loop_end_sector": 2,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            results = prepare_audio(
                manifest_path,
                input_dir,
                output_dir,
            )

            with wave.open(str(output_dir / "track13.wav"), "rb") as wav:
                output_bytes = wav.readframes(wav.getnframes())

            bytes_per_sector = FRAMES_PER_SECTOR * 2 * 2
            self.assertEqual(
                output_bytes,
                source_bytes[bytes_per_sector : bytes_per_sector * 3],
            )
            self.assertEqual(results[0]["sectors"], 2)
            self.assertEqual(
                results[0]["conversion"]["trim_start_sector"],
                1,
            )

    def test_non_wav_input_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.audio"
            destination = Path(directory) / "output.wav"
            source.write_bytes(b"synthetic non-WAV input")

            with self.assertRaisesRegex(BuildError, "must be a WAV file"):
                convert_audio_file(source, destination)
            self.assertFalse(destination.exists())

    def test_8_bit_pcm_expands_without_dither(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source-8.wav"
            destination = Path(directory) / "output.wav"
            _write_pcm_wave(source, sample_width=1, frames=FRAMES_PER_SECTOR * 2)

            plan = build_conversion_plan(probe_audio(source))
            info = convert_audio_file(source, destination)
            output_samples = [sample for frame in _read_pcm16_frames(destination) for sample in frame]

            self.assertEqual(plan.filters[0], "aformat=sample_fmts=s16")
            self.assertTrue(output_samples)
            self.assertTrue(any(sample != 0 for sample in output_samples))
            self.assertTrue(all(sample % 256 == 0 for sample in output_samples))
            self.assertTrue(info["conversion"]["format_or_codec_conversion"])
            self.assertFalse(info["conversion"]["precision_reduction"])
            self.assertTrue(info["conversion"]["precision_expansion"])
            self.assertIsNone(info["conversion"]["dither"])

    def test_24_bit_conversion_dithers_without_resampling(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source-24.wav"
            destination = Path(directory) / "output.wav"
            _write_pcm_wave(source, sample_width=3, frames=FRAMES_PER_SECTOR * 2 + 29)

            plan = build_conversion_plan(probe_audio(source))
            info = convert_audio_file(source, destination)

            self.assertIn("dither_method=triangular_hp", plan.filters[0])
            self.assertNotIn("resampler=", plan.filters[0])
            self.assertEqual(info["sample_width"], 2)
            self.assertEqual(info["sample_rate"], 44_100)
            self.assertEqual(info["channels"], 2)
            self.assertEqual(info["frames"], FRAMES_PER_SECTOR * 2)
            self.assertTrue(any(sample != 0 for frame in _read_pcm16_frames(destination) for sample in frame))
            self.assertFalse(info["conversion"]["sample_rate_conversion"])
            self.assertTrue(info["conversion"]["format_or_codec_conversion"])
            self.assertTrue(info["conversion"]["precision_reduction"])
            self.assertFalse(info["conversion"]["precision_expansion"])
            self.assertIsNone(info["conversion"]["resampler"])
            self.assertEqual(info["conversion"]["dither"], "triangular_hp")
            self.assertEqual(info["conversion"]["discarded_trailing_frames"], 29)

    def test_48_khz_conversion_uses_soxr_at_precision_33(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source-48.wav"
            destination = Path(directory) / "output.wav"
            _write_pcm_wave(source, sample_rate=48_000, frames=2_000)

            plan = build_conversion_plan(probe_audio(source))
            info = convert_audio_file(source, destination)

            self.assertIn("resampler=soxr", plan.filters[0])
            self.assertIn("precision=33", plan.filters[0])
            self.assertEqual(info["sample_rate"], 44_100)
            self.assertEqual(info["sample_width"], 2)
            self.assertEqual(info["channels"], 2)
            self.assertTrue(info["conversion"]["sample_rate_conversion"])
            self.assertFalse(info["conversion"]["precision_reduction"])
            self.assertEqual(info["conversion"]["resampler"], "soxr")
            self.assertEqual(info["conversion"]["soxr_precision"], 33)
            self.assertEqual(info["conversion"]["dither"], "triangular_hp")

    def test_explicit_end_sector_has_exact_final_domain_length(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source-48.wav"
            destination = Path(directory) / "output.wav"
            _write_pcm_wave(source, sample_rate=48_000, frames=4_000)

            info = convert_audio_file(source, destination, end_sector=2)

            self.assertEqual(info["frames"], FRAMES_PER_SECTOR * 2)
            self.assertEqual(info["sectors"], 2)

    def test_ffmpeg_start_trim_uses_final_domain_sector_window(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source-24.wav"
            destination = Path(directory) / "output.wav"
            _write_pcm_wave(
                source,
                sample_width=3,
                frames=FRAMES_PER_SECTOR * 4,
            )

            plan = build_conversion_plan(
                probe_audio(source),
                trim_start_sector=1,
                end_sector=2,
            )
            info = convert_audio_file(
                source,
                destination,
                trim_start_sector=1,
                end_sector=2,
            )

            self.assertIn(
                f"atrim=start_sample={FRAMES_PER_SECTOR}:"
                f"end_sample={FRAMES_PER_SECTOR * 3}",
                plan.filters,
            )
            self.assertEqual(info["frames"], FRAMES_PER_SECTOR * 2)
            self.assertEqual(info["sectors"], 2)
            self.assertEqual(info["conversion"]["method"], "ffmpeg")

    def test_mono_input_is_expanded_without_unnecessary_dither(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source-mono.wav"
            destination = Path(directory) / "output.wav"
            _write_pcm_wave(source, channels=1)

            source_frames = _read_pcm16_frames(source)
            plan = build_conversion_plan(probe_audio(source))
            info = convert_audio_file(source, destination)
            output_frames = _read_pcm16_frames(destination)

            self.assertEqual(plan.filters[0], "pan=stereo|c0=c0|c1=c0")
            self.assertEqual(info["channels"], 2)
            self.assertTrue(info["conversion"]["channel_conversion"])
            self.assertEqual(info["conversion"]["channel_conversion_method"], "duplicate_mono")
            self.assertFalse(info["conversion"]["sample_rate_conversion"])
            self.assertIsNone(info["conversion"]["dither"])
            self.assertEqual(len(output_frames), len(source_frames))
            self.assertEqual([frame[0] for frame in output_frames], [frame[0] for frame in source_frames])
            self.assertEqual([frame[1] for frame in output_frames], [frame[0] for frame in source_frames])

    def test_higher_precision_mono_is_dithered_once_then_duplicated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source-24-mono.wav"
            destination = Path(directory) / "output.wav"
            _write_pcm_wave(
                source,
                sample_rate=48_000,
                sample_width=3,
                channels=1,
                frames=3_000,
            )

            plan = build_conversion_plan(probe_audio(source))
            info = convert_audio_file(source, destination)
            output_frames = _read_pcm16_frames(destination)

            self.assertIn("resampler=soxr", plan.filters[0])
            self.assertIn("dither_method=triangular_hp", plan.filters[0])
            self.assertNotIn("stereo", plan.filters[0])
            self.assertEqual(plan.filters[1], "pan=stereo|c0=c0|c1=c0")
            self.assertEqual(info["conversion"]["dither"], "triangular_hp")
            self.assertEqual(info["conversion"]["channel_conversion_method"], "duplicate_mono")
            self.assertTrue(output_frames)
            self.assertTrue(all(left == right for left, right in output_frames))

    def test_more_than_two_channels_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source-3-channel.wav"
            destination = Path(directory) / "output.wav"
            _write_pcm_wave(source, channels=3)

            with self.assertRaisesRegex(BuildError, "no surround downmix policy"):
                convert_audio_file(source, destination)
            self.assertFalse(destination.exists())

    def test_higher_precision_resampling_is_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source-24-48.wav"
            first = Path(directory) / "first.wav"
            second = Path(directory) / "second.wav"
            _write_pcm_wave(source, sample_rate=48_000, sample_width=3, frames=3_000)

            first_info = convert_audio_file(source, first)
            second_info = convert_audio_file(source, second)

            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(first_info["sha256"], second_info["sha256"])

    def test_speed_filter_precedes_final_quantisation(self) -> None:
        source_info: dict[str, int | str | None] = {
            "codec": "pcm_s24le",
            "sample_format": "s32",
            "sample_rate": 48_000,
            "channels": 2,
            "channel_layout": "stereo",
            "bits_per_sample": 24,
            "bits_per_raw_sample": 24,
            "effective_bit_depth": 24,
        }

        plan = build_conversion_plan(source_info, speed=1.2)

        self.assertTrue(plan.filters[0].startswith("atempo="))
        self.assertIn("resampler=soxr", plan.filters[1])
        self.assertIn("precision=33", plan.filters[1])
        self.assertIn("dither_method=triangular_hp", plan.filters[1])

    def test_speed_conversion_uses_ffmpeg_and_final_dither(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.wav"
            destination = Path(directory) / "output.wav"
            _write_pcm_wave(source, frames=FRAMES_PER_SECTOR * 4)

            info = convert_audio_file(source, destination, speed=1.2)

            self.assertEqual(info["conversion"]["method"], "ffmpeg")
            self.assertEqual(info["conversion"]["speed"], 1.2)
            self.assertFalse(info["conversion"]["precision_reduction"])
            self.assertEqual(info["conversion"]["dither"], "triangular_hp")
            self.assertFalse(info["conversion"]["sample_rate_conversion"])

    def test_ffmpeg_capability_check(self) -> None:
        result = check_ffmpeg_audio_capabilities()

        self.assertTrue(result["soxr"])
        self.assertEqual(result["soxr_precision"], 33)
        self.assertEqual(result["dither"], "triangular_hp")


if __name__ == "__main__":
    unittest.main()
