from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.mdplus_builder import cli, modern, source
from tools.mdplus_builder.common import DEPENDENCIES, ROM_PATH, SOURCE_DIR, BuildError, load_json


class ModernSourceTests(unittest.TestCase):
    def test_pins_and_paths_are_separate(self) -> None:
        deps = load_json(DEPENDENCIES)
        self.assertEqual(deps['source_modern'], {
            'url': 'https://github.com/sonicretro/s2disasm.git',
            'commit': '380f37a731bfc720bb0371a35a593184a7ec5e43',
        })
        self.assertEqual(deps['source']['commit'], 'b49afdb010090c282e1bb79f18f14a32d1bb7a99')
        self.assertNotEqual(modern.SOURCE_MODERN_DIR, SOURCE_DIR)
        self.assertNotEqual(modern.STOCK_MODERN_ROM_PATH, ROM_PATH)
        self.assertEqual(cli.parser().parse_args(['build-rom']).source_dir, SOURCE_DIR)
        self.assertEqual(cli.parser().parse_args(['build-rom']).output, ROM_PATH)

    def test_bootstraps_fetch_only_their_dependencies(self) -> None:
        deps = load_json(DEPENDENCIES)
        with patch.object(modern, '_clone_at') as clone:
            modern.bootstrap_modern(local_source=Path('/local/s2disasm'))
            clone.assert_called_once_with(
                deps['source_modern']['url'], deps['source_modern']['commit'],
                modern.SOURCE_MODERN_DIR, Path('/local/s2disasm'),
            )
        with patch.object(source, '_clone_at') as clone:
            source.bootstrap(skip_assembler_build=True)
            self.assertEqual([call.args[1] for call in clone.call_args_list],
                             [deps['source']['commit'], deps['assembler']['commit']])

    def test_cli_routes_modern_commands(self) -> None:
        with patch.object(cli, 'bootstrap_modern') as bootstrap:
            self.assertEqual(cli.main(['bootstrap-modern']), 0)
            bootstrap.assert_called_once_with(local_source=None)
        with patch.object(cli, 'build_stock_modern', return_value={}) as build, patch.object(cli, '_print_json'):
            self.assertEqual(cli.main(['build-stock-modern']), 0)
            build.assert_called_once_with()

    def test_all_still_uses_legacy_source(self) -> None:
        with (
            patch.object(cli, 'bootstrap') as bootstrap,
            patch.object(cli, 'apply_mdplus') as prepare,
            patch.object(cli, 'build_rom') as build,
            patch.object(cli, 'prepare_audio'),
            patch.object(cli, 'assemble'),
            patch.object(cli, 'bootstrap_modern') as modern_bootstrap,
            patch.object(cli, 'build_stock_modern') as modern_build,
            patch('builtins.print'),
        ):
            self.assertEqual(cli.main(['all', '--input-dir', 'inputs/audio']), 0)
            bootstrap.assert_called_once_with(local_source=None)
            prepare.assert_called_once_with(SOURCE_DIR)
            build.assert_called_once_with()
            modern_bootstrap.assert_not_called()
            modern_build.assert_not_called()

    def test_missing_lua_is_a_cli_error(self) -> None:
        with patch('shutil.which', return_value=None), patch('sys.stderr'):
            self.assertEqual(cli.main(['build-stock-modern']), 1)

    def test_missing_source_and_wrong_pin_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch.object(modern, 'SOURCE_MODERN_DIR', root / 'missing'),
                patch.object(modern, 'require_program', return_value='/usr/bin/lua'),
                patch.object(modern, 'run'),
                self.assertRaisesRegex(BuildError, 'bootstrap-modern'),
            ):
                modern.build_stock_modern()
            with (
                patch.object(modern, 'SOURCE_MODERN_DIR', root),
                patch.object(modern, 'require_program', return_value='/usr/bin/lua'),
                patch.object(modern, 'run'),
                patch.object(modern, '_git_output', return_value='0' * 40),
                self.assertRaisesRegex(BuildError, 'expected'),
            ):
                modern.build_stock_modern()

    def test_build_uses_clean_clone_and_only_publishes_verified_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkout = root / 'checkout'
            checkout.mkdir()
            (checkout / 's2built.bin').write_bytes(b'stale input')
            output = root / 'stock.md'
            output.write_bytes(b'previous output')

            def clone(url: str, commit: str, destination: Path, local_source: Path) -> None:
                self.assertEqual(local_source, checkout)
                destination.mkdir()

            def run(args: list, *, cwd: Path | None = None) -> None:
                if cwd is not None:
                    self.assertNotEqual(cwd, checkout)
                    self.assertFalse((cwd / 's2built.bin').exists())
                    self.assertEqual(args, ['/usr/bin/lua', 'build.lua'])
                    (cwd / 's2built.bin').write_bytes(b'new output')

            with (
                patch.object(modern, 'BUILD', root),
                patch.object(modern, 'SOURCE_MODERN_DIR', checkout),
                patch.object(modern, 'STOCK_MODERN_ROM_PATH', output),
                patch.object(modern, 'require_program', return_value='/usr/bin/lua'),
                patch.object(modern, '_git_output', return_value=load_json(DEPENDENCIES)['source_modern']['commit']),
                patch.object(modern, '_clone_at', side_effect=clone),
                patch.object(modern, 'run', side_effect=run),
            ):
                with self.assertRaisesRegex(BuildError, 'audited REV01'):
                    modern.build_stock_modern()
                self.assertEqual(output.read_bytes(), b'previous output')
                with patch.object(modern, 'verify_stock_modern', return_value={'size': 10}):
                    self.assertEqual(modern.build_stock_modern(), {'size': 10})
                self.assertEqual(output.read_bytes(), b'new output')
            self.assertEqual((checkout / 's2built.bin').read_bytes(), b'stale input')


class StockVerificationTests(unittest.TestCase):
    def test_accepts_audited_values_and_requires_each_one(self) -> None:
        # No game data in fixtures: mock only the bytes and digest operations.
        with (
            patch.object(Path, 'read_bytes', return_value=bytes(modern.STOCK_ROM_SIZE)),
            patch.object(modern.hashlib, 'md5') as md5,
            patch.object(modern.hashlib, 'sha256') as sha256,
        ):
            md5.return_value.hexdigest.return_value = modern.STOCK_ROM_MD5
            sha256.return_value.hexdigest.return_value = modern.STOCK_ROM_SHA256
            self.assertEqual(modern.verify_stock_modern(Path('stock.md')), {
                'size': 1_048_576, 'md5': modern.STOCK_ROM_MD5, 'sha256': modern.STOCK_ROM_SHA256,
            })
            for field, value in [('STOCK_ROM_SIZE', 1), ('STOCK_ROM_MD5', 'bad'), ('STOCK_ROM_SHA256', 'bad')]:
                with self.subTest(field=field), patch.object(modern, field, value), self.assertRaises(BuildError):
                    modern.verify_stock_modern(Path('stock.md'))

    def test_real_digest_calculation_and_modified_rom_rejection(self) -> None:
        data = b'synthetic stock fixture'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'stock.md'
            path.write_bytes(data)
            with (
                patch.object(modern, 'STOCK_ROM_SIZE', len(data)),
                patch.object(modern, 'STOCK_ROM_MD5', hashlib.md5(data, usedforsecurity=False).hexdigest()),
                patch.object(modern, 'STOCK_ROM_SHA256', hashlib.sha256(data).hexdigest()),
            ):
                modern.verify_stock_modern(path)
                path.write_bytes(b'S' + data[1:])
                with self.assertRaisesRegex(BuildError, 'audited REV01'):
                    modern.verify_stock_modern(path)
            path.unlink()
            with self.assertRaisesRegex(BuildError, 'Cannot read stock ROM'):
                modern.verify_stock_modern(path)


if __name__ == '__main__':
    unittest.main()
