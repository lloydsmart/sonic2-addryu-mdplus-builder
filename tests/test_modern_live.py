from __future__ import annotations

import hashlib
import unittest
from pathlib import Path
from unittest.mock import patch

import test_modern

from tools.mdplus_builder import modern
from tools.mdplus_builder.common import BuildError


class ModernLiveStructureTests(unittest.TestCase):
    def test_all_four_direct_pause_patterns_have_exact_counts(self):
        fixture = test_modern.ModernAdapterTests.fixture
        for old, new, count in modern.PAUSE_SOURCES:
            with patch.object(modern, 'UPSTREAM_S2_SHA256', hashlib.sha256(fixture).hexdigest()):
                prepared = modern._prepare_modern_source(fixture).decode()
            self.assertEqual(prepared.count(new), count)
            self.assertNotIn(old, prepared)
            for delta in (-1, 1):
                bad = fixture.replace(old.encode(), old.encode() * (1 + delta), 1)
                with (patch.object(modern, 'UPSTREAM_S2_SHA256', hashlib.sha256(bad).hexdigest()),
                      self.assertRaisesRegex(BuildError, f'exactly {count} direct')):
                    modern._prepare_modern_source(bad)

    def test_every_state_address_asserts_hole_and_gameinit_clear_bounds(self):
        self.assertEqual(modern.RAM_STATE, {
            'ForgeModernCounter': (0xFFF100, 4), 'ForgeModernDuck': (0xFFF108, 1),
            'ForgeModernOwner': (0xFFF111, 1), 'ForgeModernPending': (0xFFF112, 1),
            'ForgeModernHandoff': (0xFFF113, 1), 'ForgeModernPaused': (0xFFF114, 1),
            'ForgeModernActive': (0xFFF115, 1),
        })
        text = modern._modern_router_source()
        for name, (address, size) in modern.RAM_STATE.items():
            self.assertIn(f'{name}<>ramaddr(${address | 0xFF000000:X})', text)
            self.assertIn(f'{name}<Underwater_palette+$80', text)
            self.assertIn(f'{name}+{size}>Game_Mode', text)
            self.assertIn(f'{name}<RAM_Start', text)
            self.assertIn(f'{name}+{size}>CrossResetRAM', text)
        self.assertIn('(fixBugs<>0)', modern._modern_extension_source())
        self.assertEqual(modern._modern_router_source().count('beq.w   ForgeModernRequest'), 16)
        self.assertNotIn('@ROUTE@', text)

    def test_frozen_z80_source_and_bounded_stage4_completion_change(self):
        root = Path(modern.__file__).parent
        self.assertEqual(hashlib.sha256((root / 'hybrid_modern_z80.asm').read_bytes()).hexdigest(),
                         '02e749e1e1b6d63416a26bec3d7df86268035fb8da470a77fb043767a7f8a917')
        source = (root / 'hybrid_modern_handoff.asm').read_text()
        self.assertEqual(source.count('jmp     (ForgeModernComplete).l'), 1)
        self.assertEqual(modern.COMPLETION_ADDRESS, 0x100300)
        self.assertEqual(modern.HANDOFF_END, modern.ROUTER_ADDRESS)
        self.assertEqual(modern.Z80_COMPRESSED_SIZE, 4009)
        self.assertEqual(modern.Z80_LOADED_SIZE, 4986)
        self.assertEqual(modern.Z80_SHA256, '9f997cc7217dda878297f7359f3314c7876aeb29e8705d63bd4b6db1513db24f')

    def test_exact_hook_footprints_and_separate_experimental_output(self):
        self.assertEqual(set(modern.LIVE_HOOKS), {0x382, 0x45E, 0x1370, 0x1376, 0x13AC, 0x13F2, 0x1406, 0x541A})
        for address, value in modern.expected_live_hooks().items():
            self.assertEqual(len(value), len(bytes.fromhex(modern.LIVE_HOOKS[address][2])))
        self.assertEqual(modern.MODERN_ROM_PATH.name, 'sonic2-modern-mdplus.md')
        self.assertEqual(modern.ROUTER_ADDRESSES['ForgeModernPlayMusic'], modern.ROUTER_ADDRESS)
        self.assertEqual(modern.HOOK_BYTES[:6], bytes.fromhex('4ef9001003a8'))
