"""Public default/fallback selection and packaging guards; no game fixtures."""
from __future__ import annotations

import json
import tempfile
import unittest
import wave
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from tools.mdplus_builder import cli, package
from tools.mdplus_builder.common import DEFAULT_MANIFEST, LEGACY_ROM_PATH, PREPARED_LEGACY_DIR, ROM_PATH, BuildError


class PublicSelectionTests(unittest.TestCase):
    def test_default_and_explicit_legacy_all(self):
        for legacy in (False, True):
            with self.subTest(legacy=legacy), ExitStack() as stack:
                calls = {name: stack.enter_context(patch.object(cli, name)) for name in (
                    'bootstrap', 'prepare_legacy', 'build_rom', 'bootstrap_modern', 'build_modern',
                    'build_stock_modern', 'prepare_audio', 'assemble',
                )}
                stack.enter_context(patch('builtins.print'))
                args = ['all', '--input-dir', 'inputs/audio'] + (['--legacy'] if legacy else [])
                self.assertEqual(cli.main(args), 0)
                selected = ('bootstrap', 'prepare_legacy', 'build_rom') if legacy else (
                    'bootstrap_modern', 'build_modern')
                for name in selected:
                    if name.startswith('bootstrap'):
                        calls[name].assert_called_once_with(local_source=None)
                    else:
                        calls[name].assert_called_once_with()
                for name in {'bootstrap', 'prepare_legacy', 'build_rom', 'bootstrap_modern',
                             'build_modern', 'build_stock_modern'} - set(selected):
                    calls[name].assert_not_called()
                calls['prepare_audio'].assert_called_once_with(DEFAULT_MANIFEST, Path('inputs/audio').resolve())
                calls['assemble'].assert_called_once_with(DEFAULT_MANIFEST, legacy=legacy)

    def test_rom_commands_and_custom_output_select_current_source(self):
        for command in ('build-rom', 'build-modern'):
            with (
                self.subTest(command=command), patch.object(cli, 'build_modern') as modern,
                patch.object(cli, 'build_rom') as legacy, patch.object(cli, '_print_json'),
            ):
                self.assertEqual(cli.main([command]), 0)
                self.assertEqual(modern.call_count, 1)
                self.assertEqual(modern.call_args.args or (ROM_PATH,), (ROM_PATH,))
                legacy.assert_not_called()
        with patch.object(cli, 'build_modern') as build, patch.object(cli, '_print_json'):
            self.assertEqual(cli.main(['build-rom', '--output', 'build/custom.md']), 0)
            build.assert_called_once_with(Path('build/custom.md').resolve())

    def test_legacy_rom_uses_separate_preparation_and_output(self):
        with (
            patch.object(cli, 'prepare_legacy') as prepare, patch.object(cli, 'build_rom') as build,
            patch.object(cli, 'build_modern') as modern, patch.object(cli, '_print_json'),
        ):
            self.assertEqual(cli.main(['build-rom', '--legacy']), 0)
            prepare.assert_called_once_with()
            build.assert_called_once_with(PREPARED_LEGACY_DIR, LEGACY_ROM_PATH)
            modern.assert_not_called()

    def test_bootstrap_and_prepare_aliases_select_current_source(self):
        for command, function in (
            ('bootstrap', 'bootstrap_modern'), ('bootstrap-modern', 'bootstrap_modern'),
            ('prepare-source', 'prepare_modern'), ('prepare-modern', 'prepare_modern'),
        ):
            with self.subTest(command=command), patch.object(cli, function) as call, patch.object(cli, '_print_json'):
                self.assertEqual(cli.main([command]), 0)
                if command.startswith('bootstrap'):
                    call.assert_called_once_with(local_source=None)
                else:
                    call.assert_called_once_with()

    def test_legacy_only_arguments_are_not_silently_ignored(self):
        for args in (['bootstrap', '--skip-assembler-build'],
                     ['prepare-source', '--source-dir', 'build/source'],
                     ['build-rom', '--source-dir', 'build/source']):
            with self.subTest(args=args), patch('sys.stderr'):
                self.assertEqual(cli.main(args), 1)

    def test_verification_requires_explicit_legacy_selection(self):
        for legacy in (False, True):
            with (
                self.subTest(legacy=legacy), patch.object(cli, 'verify_modern') as modern,
                patch.object(cli, 'verify_rom') as old, patch.object(cli, '_print_json'),
            ):
                args = ['verify-rom', '--strict-regression', 'build/test.md'] + (['--legacy'] if legacy else [])
                self.assertEqual(cli.main(args), 0)
                (old if legacy else modern).assert_called_once_with(
                    Path('build/test.md').resolve(), strict_regression=True)
                (modern if legacy else old).assert_not_called()


class PackageSelectionTests(unittest.TestCase):
    def test_package_default_and_fallback_validate_selected_rom_before_writing(self):
        for legacy in (False, True):
            with (
                self.subTest(legacy=legacy),
                patch.object(package, 'verify_modern', side_effect=BuildError('wrong ROM')) as modern,
                patch.object(package, 'verify_rom', side_effect=BuildError('wrong ROM')) as old,
                patch.object(package.shutil, 'copy2') as copy,
            ):
                with self.assertRaisesRegex(BuildError, 'wrong ROM'):
                    package.assemble(DEFAULT_MANIFEST, legacy=legacy)
                (old if legacy else modern).assert_called_once_with(
                    LEGACY_ROM_PATH if legacy else ROM_PATH, strict_regression=True)
                (modern if legacy else old).assert_not_called()
                copy.assert_not_called()

    def test_packaged_names_cue_audio_and_checksums_are_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rom = root / 'source.md'
            rom.write_bytes(b'synthetic ROM')
            audio = root / 'track03.wav'
            with wave.open(str(audio), 'wb') as wav:
                wav.setparams((2, 2, 44100, 0, 'NONE', 'not compressed'))
                wav.writeframes(bytes(588 * 4 * 2))
            manifest = root / 'tracks.json'
            manifest.write_text(json.dumps({'schema': 1, 'rom_basename': 'Test MD+', 'tracks': [{
                'track': 3, 'enabled': True, 'source': 'input.wav', 'mode': 'loop',
                'loop_start_sector': 0, 'loop_end_sector': 2,
            }]}))
            with patch.object(package, 'DIST', root / 'dist'), patch.object(package, 'verify_modern') as verify:
                output = package.assemble(manifest, rom_path=rom, audio_dir=root)
            verify.assert_called_once_with(rom, strict_regression=True)
            self.assertEqual({p.name for p in output.iterdir()},
                             {'Test MD+.md', 'Test MD+.cue', 'track03.wav', 'SHA256SUMS.json'})
            self.assertEqual((output / 'Test MD+.md').read_bytes(), rom.read_bytes())
            self.assertEqual((output / 'track03.wav').read_bytes(), audio.read_bytes())
            self.assertEqual((output / 'Test MD+.cue').read_text(),
                             'FILE "track03.wav" WAVE\n  TRACK 03 AUDIO\n    INDEX 01 00:00:00\n    REM LOOP 0\n')
            hashes = json.loads((output / 'SHA256SUMS.json').read_text())
            self.assertEqual(hashes, {p.name: package.sha256(p) for p in output.iterdir()
                                      if p.name != 'SHA256SUMS.json'})
