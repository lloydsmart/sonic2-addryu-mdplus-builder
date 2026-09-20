from __future__ import annotations

import json
import tempfile
import unittest
import wave
from pathlib import Path

from tools.mdplus_builder.audio import FRAMES_PER_SECTOR, score_loop, validate_manifest, validate_wave
from tools.mdplus_builder.common import BuildError
from tools.mdplus_builder.package import cue_text
from tools.mdplus_builder.source import genesis_checksum


class BuilderTests(unittest.TestCase):
    def test_genesis_checksum(self) -> None:
        data = bytearray(0x206)
        data[0x200:0x206] = bytes.fromhex("1234 ABCD 0001")
        expected = (0x1234 + 0xABCD + 1) & 0xFFFF
        data[0x18E:0x190] = expected.to_bytes(2, "big")
        self.assertEqual(genesis_checksum(bytes(data)), (expected, expected))

    def test_cue_uses_explicit_track_and_loop(self) -> None:
        manifest = {
            "tracks": [
                {
                    "track": 3,
                    "enabled": True,
                    "mode": "loop",
                    "loop_start_sector": 292,
                }
            ]
        }
        self.assertEqual(
            cue_text(manifest),
            'FILE "track03.wav" WAVE\n  TRACK 03 AUDIO\n    INDEX 01 00:00:00\n    REM LOOP 292\n',
        )

    def test_wave_sector_alignment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.wav"
            with wave.open(str(path), "wb") as wav:
                wav.setnchannels(2)
                wav.setsampwidth(2)
                wav.setframerate(44_100)
                wav.writeframes(b"\0" * FRAMES_PER_SECTOR * 4)
            info = validate_wave(path, end_sector=1)
            self.assertEqual(info["sectors"], 1)

    def test_enabled_loop_requires_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tracks.json"
            path.write_text(
                json.dumps(
                    {
                        "schema": 1,
                        "tracks": [
                            {
                                "track": 3,
                                "enabled": True,
                                "source": "track.wav",
                                "mode": "loop",
                                "loop_start_sector": None,
                                "loop_end_sector": None,
                            }
                        ],
                    }
                )
            )
            with self.assertRaises(BuildError):
                validate_manifest(path)

    def test_manifest_rejects_source_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tracks.json"
            path.write_text(
                json.dumps(
                    {
                        "schema": 1,
                        "tracks": [
                            {
                                "track": 3,
                                "enabled": True,
                                "source": "../track.wav",
                                "mode": "loop",
                                "loop_start_sector": 1,
                                "loop_end_sector": 2,
                            }
                        ],
                    }
                )
            )
            with self.assertRaises(BuildError):
                validate_manifest(path)

    def test_loop_score_for_repeated_silence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "loop.wav"
            with wave.open(str(path), "wb") as wav:
                wav.setnchannels(2)
                wav.setsampwidth(2)
                wav.setframerate(44_100)
                wav.writeframes(b"\0" * FRAMES_PER_SECTOR * 6 * 4)
            self.assertEqual(score_loop(path, 2, 5, window_ms=10), 0.0)


if __name__ == "__main__":
    unittest.main()
