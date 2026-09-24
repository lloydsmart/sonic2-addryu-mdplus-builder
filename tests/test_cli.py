from __future__ import annotations

import unittest

from tools.mdplus_builder.cli import _clean_rom_revision
from tools.mdplus_builder.common import BuildError


class CleanRomRevisionTests(unittest.TestCase):
    def test_recognises_rev00(self) -> None:
        self.assertEqual(
            _clean_rom_revision("24AB4C3A"),
            "World Rev 0",
        )

    def test_recognises_rev01(self) -> None:
        self.assertEqual(
            _clean_rom_revision("7B905383"),
            "World Rev 1",
        )

    def test_rejects_unknown_crc(self) -> None:
        with self.assertRaisesRegex(
            BuildError,
            "24AB4C3A .*World Rev 0.*7B905383 .*World Rev 1",
        ):
            _clean_rom_revision("DEADBEEF")


if __name__ == "__main__":
    unittest.main()
