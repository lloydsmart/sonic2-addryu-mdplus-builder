"""ROM regression suite: PYTHONPATH=. python tests/check_game_modes_binary.py SOURCE_DIR.

Requires the emulation extra and a built s2built.bin/s2.map. Executes unmodified
68000 bytes, adapting the level-select diagnostic. VDP/audio registers are only
memory-backed: this does not simulate rendering, interrupts or a full console.
Tests enter the title's input decision after supplying title-ready state, and
resume menu classification/results completion past their rendering loops.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

from unicorn import UC_ARCH_M68K, UC_HOOK_CODE, UC_HOOK_MEM_WRITE, UC_MODE_BIG_ENDIAN, Uc
from unicorn.m68k_const import (
    UC_CPU_M68K_M68000,
    UC_M68K_REG_A0,
    UC_M68K_REG_A7,
    UC_M68K_REG_D0,
    UC_M68K_REG_PC,
    UC_M68K_REG_SR,
)

SOURCE = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('build/source')
MODES = (
    'SegaScreen', 'TitleScreen', 'Demo', 'Level', 'SpecialStage', 'ContinueScreen',
    '2PResults', '2PLevelSelect', 'EndingSequence', 'OptionsMenu', 'LevelSelect',
)


class GameMachine:
    RETURN = 0xF00000
    STACK = 0xFFEF00
    # The 68000 ignores the top address byte. Options embeds the maximum sound
    # value ($7F) there; absolute-short RAM instructions sign-extend it to $FF.
    RAM_TAGS = (0, 0x7F000000, 0xFF000000)

    def __init__(self, source=SOURCE):
        self.symbols = {key: int(value, 16) & 0xFFFFFF for key, value in re.findall(
            r'(\S+)\s+Int\s+([0-9A-F]+)\s', (source / 's2.map').read_text())}
        self.rom = (source / 's2built.bin').read_bytes()
        self.cpu = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
        self.cpu.ctl_set_cpu_model(UC_CPU_M68K_M68000)
        self.cpu.mem_map(0, 0x1000000)
        for tag in self.RAM_TAGS[1:]:
            self.cpu.mem_map(tag | 0xFF0000, 0x10000)
        self.cpu.mem_write(0, self.rom)
        self.cpu.reg_write(UC_M68K_REG_SR, 0x2300)
        for index in range(7):
            self.cpu.reg_write(UC_M68K_REG_A0 + index, 0xFF9000 + index * 0x100)
        self.visited = set()
        self.writes = []
        self.stops = set()
        self.cpu.hook_add(UC_HOOK_CODE, self.step)
        self.cpu.hook_add(UC_HOOK_MEM_WRITE, self.write)
        self.reset_stack()

    def address(self, name):
        return self.symbols[name] if isinstance(name, str) else name

    def put(self, name, value, size=1):
        address = self.address(name) & 0xFFFFFF
        data = value.to_bytes(size, 'big')
        for tag in self.RAM_TAGS if address >= 0xFF0000 else (0,):
            self.cpu.mem_write(tag | address, data)

    def get(self, name, size=1):
        return int.from_bytes(self.cpu.mem_read(self.address(name), size), 'big')

    def write(self, cpu, access, address, size, value, user):
        physical = address & 0xFFFFFF
        if physical >= 0xFF0000:
            self.put(physical, value, size)
        self.writes.append((physical, size, value))

    def step(self, cpu, address, size, user):
        self.visited.add(address)
        if address in self.stops:
            cpu.emu_stop()

    def reset_stack(self, return_to=RETURN):
        self.cpu.reg_write(UC_M68K_REG_A7, self.STACK)
        self.put(self.STACK, self.address(return_to), 4)

    def run(self, start, stops=()):
        self.stops = {self.address(name) for name in stops}
        self.stops.add(self.symbols['ChecksumFailed_Loop'])
        self.cpu.emu_start(self.address(start), self.RETURN, count=200_000)
        pc = self.cpu.reg_read(UC_M68K_REG_PC)
        if pc not in self.stops and pc != self.RETURN:
            raise AssertionError(f'Instruction budget exhausted at {pc:#x}')
        return pc

    def call(self, label):
        self.reset_stack()
        if self.run(label) != self.RETURN:
            raise AssertionError(f'{label} did not return')
        if self.cpu.reg_read(UC_M68K_REG_A7) != self.STACK + 4:
            raise AssertionError(f'{label} unbalanced the stack')

    def locate(self, pattern, start, end):
        start, end = self.address(start), self.address(end)
        address = self.rom.find(pattern, start, end)
        if address < 0 or self.rom.find(pattern, address + 1, end) >= 0:
            raise AssertionError(f'Expected one instruction sequence between {start:#x} and {end:#x}')
        return address

    def title_start(self, *, option=0, held_a=False):
        self.put('Game_Mode', 4)
        self.put('Title_screen_option', option)
        self.put('Ctrl_1_Held', 0x80 | (0x40 if held_a else 0))
        self.put('Ctrl_1_Press', 0x80)
        self.put('Ctrl_2_Press', 0)
        # MOVE.B Ctrl_1_Press,D0; OR.B Ctrl_2_Press,D0; ANDI.B #Start,D0.
        # The block has no label; locate it within symbolic title boundaries.
        entry = self.locate(bytes.fromhex('1038f6058038f60702000080'),
                            'TitleScreen_Loop', 'TitleScreen_CheckIfChose2P')
        self.reset_stack('MainGameLoop')
        return self.run(entry, ('MenuScreen', 'Level'))

    def classify_menu(self):
        # Resume after graphics loading, retaining the mode chosen by real code.
        mode = self.symbols['GameModeID_OptionsMenu']
        pattern = bytes.fromhex('0c38') + mode.to_bytes(2, 'big') + bytes.fromhex('f6006700')
        entry = self.locate(pattern, 'MenuScreen', 'MenuScreen_Options')
        # Two CMP/BEQ.W pairs precede the unlabelled VS fallback.
        fallback = entry + 20
        return self.run(entry, ('MenuScreen_Options', 'MenuScreen_LevelSelect', fallback)), fallback


class GameModeBinaryTests(unittest.TestCase):
    def assert_safe(self, machine):
        for name in ('ChecksumError', 'Checksum_Red', 'ChecksumFailed_Loop', 'ErrorTrap'):
            self.assertFalse(machine.symbols[name] in machine.visited, f'entered {name}')
        self.assertNotIn((0xC00000, 2, 0xE), machine.writes, 'red CRAM write')

    def enter_cheat(self, machine, sequence=(0x19, 0x65, 9, 0x17), counts=(1, 2, 3, 0)):
        machine.put('Options_menu_box', 2)
        machine.put('Ctrl_1_Press', 0x20)  # C plays each sound-test entry.
        for index, (sound, count) in enumerate(zip(sequence, counts, strict=True)):
            machine.put('Sound_test_sound', sound, 2)
            machine.call('OptionScreen_Controls')
            self.assertEqual(machine.get('Correct_cheat_entries', 2), count)
            self.assertEqual(machine.get('Correct_cheat_entries_2', 2), 0)
            enabled = sequence == (0x19, 0x65, 9, 0x17) and index == 3
            self.assertEqual(machine.get('Level_select_flag', 2), 0x101 if enabled else 0)

    def test_compiled_table_has_eleven_four_byte_tail_branches_and_canonical_ids(self):
        m = GameMachine()
        base = m.symbols['GameModesArray']
        self.assertEqual(m.rom[m.symbols['MainGameLoop']:base],
                         bytes.fromhex('1038f6000240003c4ebb000460f2'))
        for index, name in enumerate(MODES):
            with self.subTest(mode=name):
                slot = m.symbols['GameMode_' + name]
                self.assertEqual(slot - base, index * 4)
                self.assertEqual(m.symbols['GameModeID_' + name], index * 4)
                self.assertEqual(m.rom[slot:slot+2], bytes.fromhex('6000'))  # BRA.W, never BSR/JSR
                target = slot + 2 + int.from_bytes(m.rom[slot+2:slot+4], 'big', signed=True)
                self.assertFalse(base <= target < base + 44)
        self.assertEqual(m.symbols['ChecksumError'] - base, 44)  # bounds final slot too
        shim = m.symbols['JmpTo_TwoPlayerResults']
        self.assertGreaterEqual(shim, base + 44)
        self.assertEqual(m.rom[shim:shim+6], bytes.fromhex('4ef9') +
                         m.symbols['TwoPlayerResults'].to_bytes(4, 'big'))

    def test_sound_test_cheat_then_a_start_enters_level_select(self):
        m = GameMachine()
        self.enter_cheat(m)
        self.assertIn(m.symbols['CheckCheats'], m.visited)
        self.assertEqual(m.get('SFX_to_play'), m.symbols['SndID_Ring'])
        m.call('OptionScreen_Select_Other')
        self.assertEqual(m.get('Game_Mode'), 0)
        self.assertEqual(m.get('Level_select_flag', 2), 0x101)
        pc = m.title_start(held_a=True)
        self.assert_safe(m)
        self.assertEqual(m.get('Game_Mode'), 0x28)
        self.assertEqual(pc, m.symbols['MenuScreen'])
        self.assertEqual(m.classify_menu()[0], m.symbols['MenuScreen_LevelSelect'])
        self.assertEqual(m.get('Two_player_mode', 2), 0)

    def test_correct_cheat_without_a_starts_ordinary_level(self):
        m = GameMachine()
        self.enter_cheat(m)
        self.assertEqual(m.title_start(), m.symbols['Level'])
        self.assertEqual(m.get('Game_Mode'), 0x0C)
        self.assert_safe(m)

    def test_incorrect_cheat_with_a_starts_ordinary_level(self):
        m = GameMachine()
        self.enter_cheat(m, (0x19, 0x65, 9, 0x16), (1, 2, 3, 0))
        self.assertEqual(m.title_start(held_a=True), m.symbols['Level'])
        self.assertEqual(m.get('Game_Mode'), 0x0C)
        self.assert_safe(m)

    def test_ordinary_start_without_cheat_starts_level(self):
        m = GameMachine()
        self.assertEqual(m.title_start(), m.symbols['Level'])
        self.assertEqual(m.get('Game_Mode'), 0x0C)
        self.assertEqual(m.get('Two_player_mode', 2), 0)
        self.assert_safe(m)

    def test_title_options_and_two_player_selections_dispatch_correctly(self):
        for option, mode in ((1, 0x1C), (2, 0x24)):
            with self.subTest(option=option):
                m = GameMachine()
                self.assertEqual(m.title_start(option=option), m.symbols['MenuScreen'])
                self.assertEqual(m.get('Game_Mode'), mode)
                pc, fallback = m.classify_menu()
                self.assertEqual(pc, fallback if option == 1 else m.symbols['MenuScreen_Options'])
                if option == 1:
                    self.assertEqual(m.get('Two_player_mode', 2), 1)
                    self.assertEqual(m.get('Two_player_mode_copy', 2), 1)
                self.assert_safe(m)

    def test_final_death_egg_fade_dispatches_ending_not_vs_menu(self):
        m = GameMachine()
        obj = m.symbols['MainCharacter'] + 0x800
        m.cpu.reg_write(UC_M68K_REG_A0, obj)
        m.put(obj + m.symbols['anim_frame_duration'], 1)
        m.put(obj, 0xC7)
        m.reset_stack('MainGameLoop')
        pc = m.run('loc_3D9D6', ('EndingSequence', 'MenuScreen'))
        self.assertIn(m.symbols['PlaySound'], m.visited)
        self.assertIn(m.symbols['PlayMusic'], m.visited)
        self.assertIn((m.symbols['Music_to_play'], 1, m.symbols['MusID_FadeOut']), m.writes)
        self.assertIn(m.symbols['DeleteObject'], m.visited)
        self.assertEqual(m.get(obj), 0)
        self.assertEqual(m.get('Game_Mode'), 0x20)
        self.assertEqual(pc, m.symbols['EndingSequence'])
        self.assertNotIn(m.symbols['MenuScreen'], m.visited)
        self.assert_safe(m)

    def test_two_player_results_has_only_dispatch_return_and_returns_to_main_loop(self):
        m = GameMachine()
        m.put('Game_Mode', 0x18)
        continuation = m.symbols['GameModesArray'] - 2  # main loop's BRA.S after JSR
        self.assertEqual(m.run('MainGameLoop', ('TwoPlayerResults',)), m.symbols['TwoPlayerResults'])
        self.assertEqual(m.cpu.reg_read(UC_M68K_REG_A7), m.STACK - 4)
        self.assertEqual(m.get(m.STACK - 4, 4), continuation)
        self.assertEqual(m.get(m.STACK, 4), m.RETURN)
        # Skip the results rendering/wait loop, preserving its entry stack.
        # Execute the actual completed-game exit, including its RTS.
        m.cpu.reg_write(UC_M68K_REG_D0, 1)
        pc = m.run('TwoPlayerResultsDone_Game', (continuation, 'GameMode_2PLevelSelect'))
        self.assertEqual(pc, continuation)
        self.assertEqual(m.cpu.reg_read(UC_M68K_REG_A7), m.STACK)
        self.assertEqual(m.get('Game_Mode'), 0)
        self.assertNotIn(m.symbols['GameMode_2PLevelSelect'], m.visited)
        self.assert_safe(m)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]], verbosity=2)
