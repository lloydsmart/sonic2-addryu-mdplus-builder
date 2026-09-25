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


class ModernAdapterTests(unittest.TestCase):
    # Synthetic structure, not an upstream source/asset fixture.
    fixture = (modern.NATIVE_SOURCE + '\nunchanged body\n' + modern.TAIL_SOURCE + 'EndOfRom:\n').encode()

    def test_exact_transform_has_one_small_hook_and_one_late_include(self) -> None:
        with patch.object(modern, 'UPSTREAM_S2_SHA256', hashlib.sha256(self.fixture).hexdigest()):
            prepared = modern._prepare_modern_source(self.fixture).decode()
        self.assertEqual(prepared.count('PlayMusic:\n'), 1)
        self.assertEqual(prepared.count('jmp\t(ForgeModernPlayMusic).l'), 1)
        self.assertEqual(prepared.count('include "hybrid_modern.asm"'), 1)
        self.assertLess(prepared.index('unchanged body'), prepared.index('include "hybrid_modern.asm"'))
        self.assertLess(prepared.index('include "hybrid_modern.asm"'), prepared.index('EndOfRom:'))
        self.assertNotIn('tst.b', prepared)
        self.assertNotIn('msu-md.asm', prepared)

    def test_unexpected_hash_and_missing_or_duplicate_patterns_fail(self) -> None:
        with self.assertRaisesRegex(BuildError, 'structure changed'):
            modern._prepare_modern_source(self.fixture)
        for old in (modern.NATIVE_SOURCE, modern.TAIL_SOURCE):
            for replacement in ('', old + old):
                bad = self.fixture.replace(old.encode(), replacement.encode())
                with (
                    self.subTest(pattern=old, replacement=replacement),
                    patch.object(modern, 'UPSTREAM_S2_SHA256', hashlib.sha256(bad).hexdigest()),
                    self.assertRaisesRegex(BuildError, 'exactly one'),
                ):
                    modern._prepare_modern_source(bad)

    def test_prepare_recreates_clean_pinned_input_and_leaves_dependency_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkout, prepared = root / 'input', root / 'prepared'
            checkout.mkdir()
            (checkout / 's2.asm').write_bytes(b'local edits must not be used')

            def clone(url, commit, destination, local_source):
                self.assertEqual(commit, modern.AUDITED_MODERN_COMMIT)
                self.assertEqual(local_source, checkout)
                self.assertFalse(destination.exists())
                destination.mkdir()
                (destination / 's2.asm').write_bytes(self.fixture)
                (destination / 's2.sounddriver.asm').write_bytes(b'unchanged Z80')

            with (
                patch.object(modern, 'BUILD', root),
                patch.object(modern, 'SOURCE_MODERN_DIR', checkout),
                patch.object(modern, 'PREPARED_MODERN_DIR', prepared),
                patch.object(modern, '_git_output', return_value=modern.AUDITED_MODERN_COMMIT),
                patch.object(modern, '_clone_at', side_effect=clone),
                patch.object(modern, 'UPSTREAM_S2_SHA256', hashlib.sha256(self.fixture).hexdigest()),
            ):
                result = modern.prepare_modern()
                first = (prepared / 's2.asm').read_bytes()
                (prepared / 's2built.bin').write_bytes(b'stale output')
                (prepared / 's2.asm').write_bytes(b'stale edits')
                self.assertEqual(modern.prepare_modern(), result)
                self.assertEqual((prepared / 's2.asm').read_bytes(), first)
                self.assertFalse((prepared / 's2built.bin').exists())
                self.assertEqual((prepared / 's2.sounddriver.asm').read_bytes(), b'unchanged Z80')
                self.assertEqual(result['source_commit'], modern.AUDITED_MODERN_COMMIT)
                self.assertEqual((prepared / 'hybrid_modern.asm').read_bytes(),
                                 Path(modern.__file__).with_name('hybrid_modern.asm').read_bytes())
            self.assertEqual((checkout / 's2.asm').read_bytes(), b'local edits must not be used')

    def test_prepare_rejects_missing_source_wrong_head_and_changed_pin(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch.object(modern, 'SOURCE_MODERN_DIR', root / 'missing'),
                self.assertRaisesRegex(BuildError, 'bootstrap-modern'),
            ):
                modern.prepare_modern()
            with (
                patch.object(modern, 'SOURCE_MODERN_DIR', root),
                patch.object(modern, '_git_output', return_value='0' * 40),
                self.assertRaisesRegex(BuildError, 'expected'),
            ):
                modern.prepare_modern()
            deps = load_json(DEPENDENCIES)
            deps['source_modern']['commit'] = '0' * 40
            with (
                patch.object(modern, 'load_json', return_value=deps),
                self.assertRaisesRegex(BuildError, 'audited pinned commit'),
            ):
                modern.prepare_modern()

    def test_prepared_cli_and_build_verify_before_publishing(self) -> None:
        for command, function in [('prepare-modern', 'prepare_modern'), ('build-modern', 'build_modern')]:
            with patch.object(cli, function, return_value={}) as call, patch.object(cli, '_print_json'):
                self.assertEqual(cli.main([command]), 0)
                call.assert_called_once_with()
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            output = work / 'output.md'
            output.write_bytes(b'previous output')
            (work / 's2built.bin').write_bytes(b'new output')
            with (
                patch.object(modern, 'PREPARED_MODERN_DIR', work),
                patch.object(modern, 'MODERN_ROM_PATH', output),
                patch.object(modern, 'require_program', return_value='/usr/bin/lua'),
                patch.object(modern, 'prepare_modern', return_value={'source_commit': 'pin'}) as prepare,
                patch.object(modern, 'run') as run,
                patch.object(modern, 'verify_modern', side_effect=BuildError('invalid')) as verify,
            ):
                with self.assertRaisesRegex(BuildError, 'invalid'):
                    modern.build_modern()
                self.assertEqual(output.read_bytes(), b'previous output')
                prepare.assert_called_once_with()
                run.assert_called_with(['/usr/bin/lua', 'build.lua'], cwd=work)
                verify.assert_called_once_with(work / 's2built.bin')
                verify.side_effect = None
                verify.return_value = {'size': 10}
                self.assertEqual(modern.build_modern(), {'source_commit': 'pin', 'size': 10})
                self.assertEqual(output.read_bytes(), b'new output')


class ModernBinaryVerificationTests(unittest.TestCase):
    def test_only_audited_changes_are_allowed(self) -> None:
        # Entirely synthetic baseline: identity expectations are patched, while
        # all real binary layout, signature and checksum checks are exercised.
        stock = bytearray(modern.STOCK_ROM_SIZE)
        start = modern.PLAY_MUSIC_ADDRESS
        stock[start:start + 18] = modern.NATIVE_PLAY_MUSIC
        stock[0x18E:0x190] = bytes.fromhex('d951')
        stock[0x1A4:0x1A8] = (len(stock) - 1).to_bytes(4, 'big')
        data = stock + bytearray(modern.PREPARED_ROM_SIZE - len(stock))
        data[start:start + 18] = modern.HOOK_BYTES
        end = modern.IMPLEMENTATION_ADDRESS
        data[end:end + 18] = modern.NATIVE_PLAY_MUSIC
        data[0x1A4:0x1A8] = (len(data) - 1).to_bytes(4, 'big')

        def checksum(rom):
            rom[0x18E:0x190] = source.genesis_checksum(rom)[1].to_bytes(2, 'big')

        checksum(data)
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(modern, 'STOCK_ROM_MD5', hashlib.md5(stock, usedforsecurity=False).hexdigest()),
            patch.object(modern, 'STOCK_ROM_SHA256', hashlib.sha256(stock).hexdigest()),
        ):
            path = Path(directory) / 'synthetic.md'
            path.write_bytes(data)
            result = modern.verify_modern(path)
            self.assertEqual(result['size'], 0x200000)
            self.assertEqual(result['command_address_signatures'], 0)
            self.assertEqual(result['overlay_address_signatures'], 0)
            self.assertEqual(result['md5'], hashlib.md5(data, usedforsecurity=False).hexdigest())
            self.assertEqual(result['sha256'], hashlib.sha256(data).hexdigest())
            for offset, value, error in (
                (0x1A7, b'\x00', 'header end'),
                (start, b'\x00', 'absolute jump'),
                (0x2000, modern.HOOK_BYTES, 'duplicated'),
                (end, b'\x00', 'mailbox implementation'),
                (end + 18, b'\x01', 'zero padding'),
                (0x2000, bytes.fromhex('0003f7fa'), 'MD\\+ signature'),
                (0x2000, bytes.fromhex('0003f7fe'), 'MD\\+ signature'),
                (0x2000, b'\x01', 'outside the audited'),
            ):
                with self.subTest(error=error):
                    bad = bytearray(data)
                    bad[offset:offset + len(value)] = value
                    checksum(bad)
                    path.write_bytes(bad)
                    with self.assertRaisesRegex(BuildError, error):
                        modern.verify_modern(path)
            bad = bytearray(data)
            bad[0x18E] ^= 1
            path.write_bytes(bad)
            with self.assertRaisesRegex(BuildError, 'checksum mismatch'):
                modern.verify_modern(path)
            path.write_bytes(data[:-2])
            with self.assertRaisesRegex(BuildError, 'size'):
                modern.verify_modern(path)
            path.unlink()
            with self.assertRaisesRegex(BuildError, 'Cannot read modern scaffold'):
                modern.verify_modern(path)


if __name__ == '__main__':
    unittest.main()
