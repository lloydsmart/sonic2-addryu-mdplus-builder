"""Explicit ROM integration suite: python -m tests.check_hybrid_binary SOURCE_DIR.

Requires the emulation extra. Executes the built 68000/Z80 bytes with RAM and
ROM banking, recording chip writes; this does not emulate audible MD+ playback.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

import z80
from unicorn import UC_ARCH_M68K, UC_HOOK_MEM_WRITE, UC_MODE_BIG_ENDIAN, Uc
from unicorn.m68k_const import (
    UC_CPU_M68K_M68000,
    UC_M68K_REG_A5,
    UC_M68K_REG_A7,
    UC_M68K_REG_D0,
    UC_M68K_REG_PC,
    UC_M68K_REG_SR,
)

from tools.mdplus_builder.driver import assembled_driver, verify_driver_load

SOURCE = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('build/source')


class Machine:
    def __init__(self, source=SOURCE):
        self.symbols = {k: int(v, 16) & 0xFFFFFF for k, v in re.findall(
            r'(\S+)\s+Int\s+([0-9A-F]+)\s', (source / 's2.map').read_text(errors='replace'))}
        self.rom = (source / 's2built.bin').read_bytes()
        self.cpu = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
        self.cpu.ctl_set_cpu_model(UC_CPU_M68K_M68000)
        self.cpu.mem_map(0, 0x1000000)
        self.cpu.mem_map(0xFFFF0000, 0x10000)  # sign-extended absolute-short RAM
        self.cpu.mem_write(0, self.rom)
        self.events = []
        self.cpu.hook_add(UC_HOOK_MEM_WRITE, self.write68)
        self.z80 = z80.Z80Machine()
        self.bank = 0
        self.z80.set_read_callback(self.readz)
        self.z80.set_write_callback(self.writez)
        self.z80.mark_addrs(0x2000, 0xE000, self.z80.READ_MARK | self.z80.WRITE_MARK)
        self.z80.set_breakpoint(0x7000)
        self.call68('DecompressSoundDriver')
        self.loaded = self.cpu.reg_read(UC_M68K_REG_A5) - 0xA00000
        self.z80.memory[:0x2000] = self.cpu.mem_read(0xA00000, 0x2000)
        self.setz('zAbsVar.QueueToPlay', 0x80)

    def write68(self, cpu, access, address, size, value, user):
        physical = address & 0xFFFFFF
        if physical >= 0xFF0000:
            other = physical if address > 0xFFFFFF else physical | 0xFF000000
            cpu.mem_write(other, value.to_bytes(size, 'big'))
        if physical in (0x3F7FA, 0x3F7FE):
            self.events.append((physical, value))

    def readz(self, address):
        if address < 0x4000:
            return self.z80.memory[address & 0x1FFF]
        if address >= 0x8000:
            offset = (self.bank << 15) | (address & 0x7FFF)
            return self.rom[offset] if offset < len(self.rom) else 0
        return 0  # YM2612 not busy

    def writez(self, address, value):
        if address < 0x4000:
            self.z80.memory[address & 0x1FFF] = value
        elif address == 0x6000:
            self.bank = (self.bank >> 1) | ((value & 1) << 8)
        else:
            self.events.append((address, value))

    def call68(self, label, d0=0):
        self.cpu.reg_write(UC_M68K_REG_SR, 0x2700)
        self.cpu.reg_write(UC_M68K_REG_A7, 0xFFEF00)
        self.cpu.mem_write(0xFFEF00, (0xF00000).to_bytes(4, 'big'))
        self.cpu.reg_write(UC_M68K_REG_D0, d0)
        self.cpu.emu_start(self.symbols[label], 0xF00000, count=2_000_000)
        assert self.cpu.reg_read(UC_M68K_REG_PC) == 0xF00000, label

    def callz(self, label, a=0):
        self.z80.pc = self.symbols[label]
        self.z80.sp = 0x1B60
        self.z80.memory[0x1B60:0x1B62] = b'\x00\x70'
        self.z80.ix = self.symbols['zAbsVar']
        self.z80.a = a
        for _ in range(20):
            self.z80.ticks_to_stop = 100_000
            self.z80.run()
            if self.z80.pc == 0x7000:
                assert self.z80.sp == 0x1B62, (label, self.z80.sp)
                return
        raise AssertionError(f'{label} failed to return; PC={self.z80.pc:04X}')

    def input(self):
        self.cpu.mem_write(0xA00000, bytes(self.z80.memory[:0x2000]))
        self.call68('sndDriverInput')
        self.z80.memory[:0x2000] = self.cpu.mem_read(0xA00000, 0x2000)

    def getz(self, name):
        return self.z80.memory[self.symbols[name]]

    def setz(self, name, value):
        self.z80.memory[self.symbols[name]] = value

    def get68(self, name):
        return self.cpu.mem_read(self.symbols[name], 1)[0]

    @property
    def commands(self):
        return [value for address, value in self.events if address == 0x3F7FE]

    def request(self):
        self.call68('PlayMusic', self.symbols['MusID_EHZ'])
        self.input()

    def consume_stop(self):
        self.callz('zPlaySoundByIndex', self.getz('zAbsVar.QueueToPlay'))


class BinaryHandoffTests(unittest.TestCase):
    def test_title_to_ehz_vint_then_boss_and_cpz(self):
        m = Machine()
        m.callz('zPlaySoundByIndex', m.symbols['MusID_Title'])
        self.assertTrue(m.getz('zSongFM1.PlaybackControl') & 0x80)
        m.request()
        m.callz('zVInt')
        self.assertEqual(m.getz('zAbsVar.QueueToPlay'), 0x80)
        self.assertEqual(m.getz('zHybridAck'), 0xA5)
        # Full Z80 frame updates continue even with 68K service withheld.
        for _ in range(60):
            m.setz('zAbsVar.SFXToPlay', m.symbols['SndID_Jump'])
            m.callz('zVInt')
            self.assertEqual(m.getz('zAbsVar.SFXToPlay'), 0)
            self.assertEqual(m.getz('zAbsVar.QueueToPlay'), 0x80)
            self.assertEqual(m.getz('zHybridAck'), 0xA5)
        m.input()
        self.assertEqual(m.commands[-1], 0x1203)
        m.call68('PlayMusic', m.symbols['MusID_Boss'])
        self.assertEqual(m.commands[-1], 0x1300)
        m.input()
        m.callz('zPlaySoundByIndex', m.getz('zAbsVar.QueueToPlay'))
        self.assertTrue(m.getz('zSongFM1.PlaybackControl') & 0x80)
        m.call68('PlayMusic', m.symbols['MusID_CPZ'])
        m.input()
        m.callz('zVInt')
        m.input()
        self.assertEqual(m.commands[-1], 0x1205)

    def test_paused_native_song_can_complete_handoff_in_vint(self):
        m = Machine()
        m.callz('zPlaySoundByIndex', m.symbols['MusID_Title'])
        m.setz('zAbsVar.StopMusic', 0x7F)
        m.setz('zPaused', 1)
        m.request()
        m.callz('zVInt')
        self.assertEqual(m.getz('zAbsVar.StopMusic'), 0)
        self.assertEqual(m.getz('zAbsVar.QueueToPlay'), 0x80)
        self.assertEqual(m.getz('zHybridAck'), 0xA5)
        m.input()
        self.assertEqual(m.commands[-1], 0x1203)

    def test_actual_68000_loader_loads_every_assembled_byte(self):
        m = Machine()
        expected = assembled_driver(SOURCE / 's2.p')
        self.assertEqual(m.loaded, len(expected))
        self.assertEqual(bytes(m.z80.memory[:m.loaded]), expected)
        verify_driver_load(SOURCE, m.rom)

    def test_ehz_through_both_cpus_starts_track03_only_after_stop(self):
        m = Machine()
        m.setz('zHybridAck', 0xA5)  # stale completion must not satisfy a new request
        m.request()
        self.assertEqual(m.commands, [])
        self.assertEqual(m.get68('v_MusicBackend'), 1)
        self.assertEqual(m.get68('v_MDPlusHandoff'), 2)
        self.assertEqual(m.getz('zAbsVar.QueueToPlay'), 0xF7)
        self.assertEqual(m.getz('zHybridAck'), 0)
        m.consume_stop()
        self.assertEqual(m.getz('zAbsVar.QueueToPlay'), 0x80)
        self.assertEqual(m.getz('zHybridAck'), 0xA5)
        self.assertEqual(m.commands, [])
        m.input()
        self.assertEqual(m.getz('zHybridAck'), 0)
        self.assertEqual(m.get68('v_MDPlusHandoff'), 0)
        self.assertEqual(m.commands, [0x15FF, 0x1203])
        transactions = [(address, value) for address, value in m.events if address in (0x3F7FA, 0x3F7FE)]
        self.assertEqual(transactions, [(0x3F7FA, 0xCD54), (0x3F7FE, 0x15FF), (0x3F7FA, 0),
                                        (0x3F7FA, 0xCD54), (0x3F7FE, 0x1203), (0x3F7FA, 0)])

    def test_sfx_consumed_repeatedly_without_any_68000_ack_observation(self):
        m = Machine()
        m.request()
        m.consume_stop()
        for _ in range(120):
            m.setz('zAbsVar.SFXToPlay', m.symbols['SndID_Jump'])
            m.callz('zCycleQueue')
            self.assertEqual(m.getz('zAbsVar.SFXToPlay'), 0)
            self.assertEqual(m.getz('zAbsVar.QueueToPlay'), m.symbols['SndID_Jump'])
            m.callz('zPlaySoundByIndex', m.getz('zAbsVar.QueueToPlay'))
            self.assertEqual(m.getz('zAbsVar.QueueToPlay'), 0x80)
            self.assertTrue(m.getz('zSFX_PSG1.PlaybackControl') & 0x80)
            self.assertEqual(m.getz('zHybridAck'), 0xA5)
        self.assertEqual(m.get68('v_MDPlusHandoff'), 2)
        self.assertEqual(m.commands, [])
        m.input()
        self.assertEqual(m.commands[-1], 0x1203)

    def test_held_f6_reproduces_queue_starvation_but_is_no_longer_special(self):
        m = Machine()
        m.setz('zAbsVar.QueueToPlay', 0xF6)
        m.setz('zAbsVar.SFXToPlay', m.symbols['SndID_Jump'])
        m.callz('zCycleQueue')
        self.assertEqual(m.getz('zAbsVar.SFXToPlay'), m.symbols['SndID_Jump'])
        m.callz('zPlaySoundByIndex', 0xF6)
        self.assertEqual(m.getz('zAbsVar.QueueToPlay'), 0x80)
        m.callz('zCycleQueue')
        self.assertEqual(m.getz('zAbsVar.SFXToPlay'), 0)

    def test_ack_survives_stock_clear_init_and_one_up_save_range(self):
        m = Machine()
        self.assertEqual(m.symbols['zHybridAck'], 0x1FF4)
        self.assertEqual(m.symbols['zTracksSaveEnd'], m.symbols['zHybridAck'])
        for name in ['zClearTrackPlaybackMem', 'zInitMusicPlayback']:
            m.setz('zHybridAck', 0xA5)
            m.callz(name)
            self.assertEqual(m.getz('zHybridAck'), 0xA5)
        self.assertLess(m.symbols['zTracksSFXEnd'], m.symbols['zHybridAck'])
        self.assertLess(m.symbols['zTracksEnd'], m.symbols['zHybridAck'])

    def test_music_stop_preserves_sfx_ram_and_overridden_channels(self):
        m = Machine()
        start, end = m.symbols['zTracksSFXStart'], m.symbols['zTracksSFXEnd']
        original = bytes((i * 13 + 7) & 255 for i in range(end - start))
        m.z80.memory[start:end] = original
        m.setz('zSongFM1.PlaybackControl', 0x84)
        m.setz('zSongPSG1.PlaybackControl', 0x84)
        m.setz('zSongPSG1.VoiceControl', 0x80)
        m.request()
        m.consume_stop()
        self.assertEqual(bytes(m.z80.memory[start:end]), original)
        self.assertEqual(m.getz('zSongFM1.PlaybackControl'), 4)
        self.assertEqual(m.getz('zSongPSG1.PlaybackControl'), 4)
        self.assertEqual(m.getz('zHybridAck'), 0xA5)

    def test_level_and_title_card_vints_service_snd_driver_under_bus_lock(self):
        source = (SOURCE / 's2.asm').read_text()
        for start, end in [('Vint_Level:', 'Vint_S2SS:'), ('Vint_TitleCard:', 'Vint_0E:')]:
            block = source.split(start, 1)[1].split(end, 1)[0]
            self.assertIn('stopZ80', block)
            self.assertIn('sndDriverInput', block)
            self.assertLess(block.index('stopZ80'), block.index('sndDriverInput'))
            self.assertLess(block.index('sndDriverInput'), block.index('startZ80'))
        self.assertIn('sndDriverInput:\n\tbsr.w\tHybridCheckReady\n', source)


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]], verbosity=2)
