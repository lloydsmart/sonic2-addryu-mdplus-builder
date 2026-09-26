"""Verify the public cutover outputs after make rom and make rom-legacy."""
from __future__ import annotations

import unittest

from tools.mdplus_builder import modern, source
from tools.mdplus_builder.common import DEPENDENCIES, LEGACY_ROM_PATH, ROM_PATH, load_json


class ProductionIdentityTests(unittest.TestCase):
    def test_default_rom_is_exact_stage5_and_alias_is_the_same_file(self):
        result = modern.verify_modern(ROM_PATH, strict_regression=True)
        self.assertEqual((result['size'], result['header_checksum'], result['md5'], result['sha256']), (
            2_097_152, 'BE41', '9eb40c0601a7c424a0d1ce168b5f40f2',
            'bd12138cd478596e4d294a06f573a98a6d37747dfe58d726ca62cf50dc3a8c44',
        ))
        self.assertTrue(modern.MODERN_ROM_PATH.is_symlink())
        self.assertTrue(modern.MODERN_ROM_PATH.samefile(ROM_PATH))
        self.assertEqual(result['extension_sha256'],
                         'a42fecc8e83354d76638f42de8810bbfaa678d54c77b8ae1051a261af26103f1')
        self.assertEqual(result['command_transactions'], 21)
        self.assertEqual((result['z80_compressed_bytes'], result['z80_loaded_bytes']), (4009, 4986))
        self.assertEqual(result['z80_loaded_sha256'],
                         '9f997cc7217dda878297f7359f3314c7876aeb29e8705d63bd4b6db1513db24f')
        modern.verify_modern_driver(ROM_PATH.read_bytes(), modern.assembled_modern_driver(
            modern.PREPARED_MODERN_DIR / 'forge-s2.p'))

    def test_default_source_is_exact_audited_pin(self):
        expected = '380f37a731bfc720bb0371a35a593184a7ec5e43'
        self.assertEqual(load_json(DEPENDENCIES)['source_modern']['commit'], expected)
        self.assertEqual(source._git_output(modern.SOURCE_MODERN_DIR, 'rev-parse', 'HEAD'), expected)
        self.assertEqual(source._git_output(modern.PREPARED_MODERN_DIR, 'rev-parse', 'HEAD'), expected)

    def test_legacy_fallback_is_exact_previous_production_rom(self):
        result = source.verify_rom(LEGACY_ROM_PATH, strict_regression=True)
        self.assertEqual((result['size'], result['header_checksum'], result['sha256']), (
            2_129_922, '2911', '315c69fb84dbca2a31ceffe3face70b4138317feed53feb7e23c6a5ab009205e',
        ))
        self.assertNotEqual(ROM_PATH.resolve(), LEGACY_ROM_PATH.resolve())
        with self.assertRaisesRegex(modern.BuildError, 'size'):
            modern.verify_modern(LEGACY_ROM_PATH, strict_regression=True)
        with self.assertRaisesRegex(modern.BuildError, 'regression target'):
            source.verify_rom(ROM_PATH, strict_regression=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
