from __future__ import annotations

import unittest

from tools.mdplus_builder.common import BuildError
from tools.mdplus_builder.source import _repair_game_mode_dispatch

DISPATCH = (
    "\tandi.w\t#$3C,d0\t; limit Game Mode value to $3C max "
    "(change to a maximum of 7C to add more game modes)\n"
    "\tjsr\tGameModesArray(pc,d0.w)\t; jump to apt location in ROM\n"
    "\tbra.s\tMainGameLoop\t; loop indefinitely\n"
)
ENTRY = "GameMode_2PResults:\tjsr\tTwoPlayerResults\t; 2P results mode\n"
PLACEMENT = "LevelSelectMenu: ;;\n\tjmp\t(MenuScreen).l\n"


class GameModeConversionTests(unittest.TestCase):
    def fixture(self):
        return DISPATCH + 'GameModesArray: ;;\n' + ENTRY + 'ChecksumError:\n' + PLACEMENT + 'V_Int:\n'

    def test_restores_tail_transfers_outside_table_and_keeps_dispatch(self):
        converted = _repair_game_mode_dispatch(self.fixture())
        self.assertTrue(converted.startswith(DISPATCH))
        self.assertIn('GameMode_2PResults:\tbra.w\tJmpTo_TwoPlayerResults\t', converted)
        self.assertIn('JmpTo_TwoPlayerResults:\n\tjmp\t(TwoPlayerResults).l\n', converted)
        self.assertLess(converted.index('ChecksumError:'), converted.index('JmpTo_TwoPlayerResults:'))
        self.assertLess(converted.index(PLACEMENT), converted.index('JmpTo_TwoPlayerResults:'))
        self.assertLess(converted.index('JmpTo_TwoPlayerResults:'), converted.index('V_Int:'))
        self.assertNotIn('jsr\tTwoPlayerResults', converted)
        self.assertNotIn('bsr', converted)

    def test_missing_changed_or_duplicate_entry_fails_closed(self):
        for replacement in ('', ENTRY * 2, ENTRY.replace('jsr', 'bsr.w'), ENTRY.replace('jsr', 'jmp')):
            with self.subTest(entry=replacement), self.assertRaises(BuildError):
                _repair_game_mode_dispatch(self.fixture().replace(ENTRY, replacement))

    def test_missing_changed_or_duplicate_placement_fails_closed(self):
        for replacement in ('', PLACEMENT * 2, PLACEMENT.replace('jmp', 'jsr')):
            with self.subTest(placement=replacement), self.assertRaises(BuildError):
                _repair_game_mode_dispatch(self.fixture().replace(PLACEMENT, replacement))

    def test_changed_or_duplicate_dispatch_fails_closed(self):
        for replacement in ('', DISPATCH * 2, DISPATCH.replace('$3C', '$3E'),
                            DISPATCH.replace('pc,d0.w', 'pc,d1.w')):
            with self.subTest(dispatch=replacement), self.assertRaises(BuildError):
                _repair_game_mode_dispatch(self.fixture().replace(DISPATCH, replacement))

    def test_existing_trampoline_or_already_repaired_source_fails_closed(self):
        with self.assertRaisesRegex(BuildError, 'existing JmpTo_TwoPlayerResults'):
            _repair_game_mode_dispatch(self.fixture() + 'JmpTo_TwoPlayerResults:\n')
        with self.assertRaises(BuildError):
            _repair_game_mode_dispatch(_repair_game_mode_dispatch(self.fixture()))


if __name__ == '__main__':
    unittest.main()
