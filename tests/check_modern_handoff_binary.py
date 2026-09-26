"""Regress compiled Stage 4 68000/Z80 APIs with native ownership.

PYTHONPATH=. build/emulation-venv/bin/python tests/check_modern_handoff_binary.py
Requires both modern builds; uses the existing dual-CPU/chip-write harness.
"""
from __future__ import annotations

import unittest

from check_hybrid_binary import Machine
from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_READ
from unicorn.m68k_const import UC_M68K_REG_A5, UC_M68K_REG_A6, UC_M68K_REG_PC

from tools.mdplus_builder import modern
from tools.mdplus_builder.driver import saxman_decode


class ModernMachine(Machine):
    def __init__(self):
        super().__init__(modern.PREPARED_MODERN_DIR)

    @staticmethod
    def read_symbols(source):
        return modern.modern_symbols(source / 's2.lst')

    def set68(self, name, value):
        address = self.symbols[name]
        self.cpu.mem_write(address, bytes([value]))
        self.cpu.mem_write(address | 0xFF000000, bytes([value]))

    @property
    def state(self):
        return self.get68('ForgeModernHandoff')

    @property
    def mdplus(self):
        return [event for event in self.events if event[0] in (0x3F7FA, 0x3F7FE)]

    def snapshot(self):
        return (self.state, self.get68('Sound_Queue.Music0'), self.get68('Sound_Queue.Music1'),
                self.getz('zAbsVar.QueueToPlay'), self.getz('zHybridAck'))

    def vint_frame(self):
        # A DAC-starting VInt replaces its return with the sample main loop.
        # Stop at that handoff; the next test frame enters another actual VInt.
        # Sound-chip timing and DAC sample playback are outside this harness.
        tail = self.symbols['zWriteToDAC']
        self.z80.set_breakpoint(tail)
        self.z80.pc = self.symbols['zVInt']
        self.z80.sp = 0x1B60
        self.z80.memory[0x1B60:0x1B62] = b'\x00\x70'
        self.z80.ix = self.symbols['zAbsVar']
        for _ in range(20):
            self.z80.ticks_to_stop = 100000
            self.z80.run()
            if self.z80.pc in (0x7000, tail):
                break
        else:
            raise AssertionError(f'VInt frame did not finish: {self.z80.pc:04X}')
        self.z80.clear_breakpoint(tail)

    def request(self):
        self.call68('ForgeModernBeginHandoff')
        self.input()


class ModernHandoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        modern.verify_modern(modern.MODERN_ROM_PATH)

    def test_complete_internal_flow_and_ordered_ack(self):
        m = ModernMachine()
        m.callz('zPlaySoundByIndex', m.symbols['MusID_Title'])
        self.assertTrue(m.getz('zSongFM1.PlaybackControl') & 0x80)
        trace = [m.snapshot()]
        m.call68('ForgeModernBeginHandoff')
        trace.append(m.snapshot())
        m.setz('zHybridAck', 0xA5)  # stale completion before delivery
        m.input()
        trace.append(m.snapshot())
        # Break before the final ACK store: public ready is already visible,
        # while the private completion latch must still be clear.
        stop = m.symbols['zHybridCodeEnd'] - 4
        self.assertEqual(bytes(m.z80.memory[stop:stop + 4]), bytes.fromhex('32f41fc9'))
        m.z80.set_breakpoint(stop)
        m.z80.pc = m.symbols['zPlaySoundByIndex']
        m.z80.ix = m.symbols['zAbsVar']
        m.z80.a = 0xF7
        m.z80.sp = 0x1B60
        m.z80.memory[0x1B60:0x1B62] = b'\x00\x70'
        m.z80.ticks_to_stop = 100000
        m.z80.run()
        self.assertEqual(m.z80.pc, stop)
        self.assertEqual(m.getz('zAbsVar.QueueToPlay'), 0x80)
        self.assertEqual(m.getz('zHybridAck'), 0)
        for track in ('DAC', 'FM1', 'FM2', 'FM3', 'FM4', 'FM5', 'FM6', 'PSG1', 'PSG2', 'PSG3'):
            self.assertFalse(m.getz(f'zSong{track}.PlaybackControl') & 0x80)
        m.z80.clear_breakpoint(stop)
        m.z80.ticks_to_stop = 100000
        m.z80.run()
        self.assertEqual(m.z80.pc, 0x7000)
        trace.append(m.snapshot())
        m.input()
        trace.append(m.snapshot())
        self.assertEqual(trace, [(0, 0, 0, 0x80, 0), (1, 0xF7, 0, 0x80, 0),
                                (2, 0, 0, 0xF7, 0), (2, 0, 0, 0x80, 0xA5), (0, 0, 0, 0x80, 0)])
        self.assertEqual(m.mdplus, [])
        print('state/Music0/Music1/Queue/ACK:', trace)

    def test_music_only_stop_preserves_sfx_and_mutes_only_unoverridden_channels(self):
        m = ModernMachine()
        m.callz('zPlaySoundByIndex', m.symbols['MusID_Title'])
        start, end = m.symbols['zTracksSFXStart'], m.symbols['zTracksSFXEnd']
        original = bytes((i * 13 + 7) & 255 for i in range(end - start))
        m.z80.memory[start:end] = original
        for i, value in enumerate((0xA0, 0xA1, 0xA2)):
            m.setz(f'zAbsVar.Queue{i}', value)
        m.setz('zAbsVar.SFXPriorityVal', 0x67)
        cleared = ['zAbsVar.StopMusic', 'zPaused', 'zAbsVar.FadeOutCounter', 'zAbsVar.FadeInFlag',
                   'zAbsVar.1upPlaying', 'zAbsVar.SpeedUpFlag', 'zSongDAC.PlaybackControl',
                   'zCurDAC', 'zAbsVar.DACEnabled']
        for name in cleared:
            m.setz(name, 0xFF)
        for i, voice in enumerate((0, 1, 2, 4, 5, 6), 1):
            m.setz(f'zSongFM{i}.VoiceControl', voice)
            m.setz(f'zSongFM{i}.PlaybackControl', 0x84 if i == 1 else 0x80)
        for i, voice in enumerate((0x80, 0xA0, 0xC0), 1):
            m.setz(f'zSongPSG{i}.VoiceControl', voice)
            m.setz(f'zSongPSG{i}.PlaybackControl', 0x84 if i == 1 else 0x80)
        m.request()
        m.events.clear()
        m.consume_stop()
        self.assertEqual(bytes(m.z80.memory[start:end]), original)
        self.assertEqual([m.getz(f'zAbsVar.Queue{i}') for i in range(3)], [0xA0, 0xA1, 0xA2])
        self.assertEqual(m.getz('zAbsVar.SFXPriorityVal'), 0x67)
        for name in cleared:
            self.assertEqual(m.getz(name), 0, name)
        self.assertEqual(m.getz('zSongFM1.PlaybackControl'), 4)
        self.assertEqual(m.getz('zSongPSG1.PlaybackControl'), 4)
        # DAC disable first, then FM panning zeroes excluding overridden FM1.
        fm = [(a, v) for a, v in m.events if 0x4000 <= a <= 0x4003]
        self.assertEqual(fm, [(0x4000, 0x2B), (0x4001, 0)] +
                         [(a, v) for port, reg in ((0, 0xB5), (0, 0xB6),
                                                 (2, 0xB4), (2, 0xB5), (2, 0xB6))
                          for a, v in ((0x4000 + port, reg), (0x4001 + port, 0))])
        self.assertEqual([v for a, v in m.events if a == 0x7F11], [0xBF, 0xDF])
        self.assertEqual(m.getz('zHybridAck'), 0xA5)
        self.assertEqual(m.mdplus, [])

    def test_uninitialized_psg_is_skipped_and_initialized_noise_stops(self):
        for voice, expected in ((0, []), (0xE0, [0xFF])):
            m = ModernMachine()
            m.setz('zSongPSG3.VoiceControl', voice)
            m.setz('zSongPSG3.PlaybackControl', 0x80)
            m.request()
            m.events.clear()
            m.consume_stop()
            self.assertEqual([v for a, v in m.events if a == 0x7F11], expected)
            self.assertEqual(m.getz('zHybridAck'), 0xA5)
            self.assertEqual(m.mdplus, [])

    def test_paused_native_handoff_and_delayed_ack_sfx_progress(self):
        for paused in (False, True):
            with self.subTest(paused=paused):
                m = ModernMachine()
                m.callz('zPlaySoundByIndex', m.symbols['MusID_Title'])
                if paused:
                    m.setz('zAbsVar.StopMusic', 0x7F)
                    m.callz('zVInt')
                    self.assertNotEqual(m.getz('zPaused'), 0)
                m.request()
                m.callz('zVInt')
                self.assertEqual(m.getz('zAbsVar.StopMusic'), 0)
                self.assertEqual(m.getz('zPaused'), 0)
                self.assertEqual(m.getz('zHybridAck'), 0xA5)
                for _ in range(120):
                    m.setz('zAbsVar.Queue0', m.symbols['SndID_Jump'])
                    m.callz('zVInt')
                    self.assertEqual(m.getz('zAbsVar.Queue0'), 0)
                    self.assertEqual(m.getz('zAbsVar.QueueToPlay'), 0x80)
                    self.assertEqual(m.getz('zHybridAck'), 0xA5)
                    self.assertTrue(m.getz('zSFX_PSG1.PlaybackControl') & 0x80)
                    self.assertEqual(m.state, 2)
                m.input()
                self.assertEqual(m.state, 0)
                self.assertEqual(m.getz('zHybridAck'), 0)
                self.assertEqual(m.mdplus, [])
        print('Paused/unpaused handoff: ACK; each survives 120 VInts with SFX consumed every frame')

    def test_mailbox_contention_second_slot_and_no_duplicates(self):
        for first, second, expected in ((0, 0x85, (0xF7, 0x85)), (0x82, 0, (0x82, 0xF7)),
                                        (0x82, 0x85, (0x82, 0x85)), (0xF7, 0, (0xF7, 0)),
                                        (0, 0xF7, (0, 0xF7))):
            m = ModernMachine()
            m.set68('Sound_Queue.Music0', first)
            m.set68('Sound_Queue.Music1', second)
            m.call68('ForgeModernBeginHandoff')
            for _ in range(3):
                m.call68('ForgeModernQueueStop')
            self.assertEqual(m.snapshot()[1:3], expected)
            self.assertEqual(m.state, 1)
            self.assertEqual(m.mdplus, [])
        m = ModernMachine()
        m.set68('Sound_Queue.Music0', 0x82)
        m.set68('Sound_Queue.Music1', 0x85)
        m.setz('zAbsVar.QueueToPlay', 0x81)
        m.request()
        self.assertEqual(m.snapshot(), (1, 0x82, 0x85, 0x81, 0))
        m.set68('Sound_Queue.Music1', 0)
        m.input()
        self.assertEqual(m.snapshot(), (1, 0x82, 0xF7, 0x81, 0))
        m.setz('zAbsVar.QueueToPlay', 0x80)
        m.input()
        self.assertEqual(m.snapshot(), (1, 0, 0xF7, 0x82, 0))
        m.callz('zPlaySoundByIndex', 0x82)
        m.input()
        self.assertEqual(m.snapshot(), (2, 0, 0, 0xF7, 0))
        m.consume_stop()
        m.input()
        self.assertEqual(m.state, 0)
        self.assertEqual(m.mdplus, [])
        print('Contention: both mailboxes preserved; later Music1 capacity used; F7 delivered once')

    def test_false_ready_retries_and_stale_ack_is_discarded(self):
        m = ModernMachine()
        m.request()
        m.input()  # busy: no duplicate request
        self.assertEqual(m.snapshot(), (2, 0, 0, 0xF7, 0))
        m.setz('zAbsVar.QueueToPlay', 0x80)  # overwritten by native init/1-up
        m.input()
        self.assertEqual(m.snapshot(), (2, 0, 0, 0xF7, 0))
        m.consume_stop()
        m.input()
        self.assertEqual(m.snapshot(), (0, 0, 0, 0x80, 0))
        for state in (0, 1):
            m.set68('ForgeModernHandoff', state)
            m.setz('zHybridAck', 0xA5)
            m.input()
            self.assertEqual(m.getz('zHybridAck'), 0)
            self.assertEqual(m.state, 0 if state == 0 else 2)
        self.assertEqual(m.mdplus, [])
        print('False-ready: F7 redelivered; only A5 completes; stale ACK discarded in states 0 and 1')

    def test_three_sfx_slots_preserve_music1_and_voice_pointer(self):
        for slot in range(3):
            m = ModernMachine()
            m.setz('zAbsVar.QueueToPlay', 0x82)
            m.set68('Sound_Queue.Music1', 0x85)
            m.setz('zAbsVar.VoiceTblPtr', 0)  # exposes the original fourth-copy defect
            m.z80.memory[m.symbols['zAbsVar.VoiceTblPtr'] + 1] = 0x56
            for i in range(3):
                m.set68(f'Sound_Queue.SFX{i}', 0xA0 + i)
                m.setz(f'zAbsVar.Queue{i}', 0xB0 if i == slot else 0)
            m.input()
            self.assertEqual(m.get68('Sound_Queue.Music1'), 0x85)
            ptr = m.symbols['zAbsVar.VoiceTblPtr']
            self.assertEqual(bytes(m.z80.memory[ptr:ptr + 2]), b'\x00\x56')
            for i in range(3):
                self.assertEqual(m.getz(f'zAbsVar.Queue{i}'), 0xB0 if i == slot else 0xA0 + i)
                self.assertEqual(m.get68(f'Sound_Queue.SFX{i}'), 0xA0 + i if i == slot else 0)
            self.assertEqual(m.mdplus, [])

    def test_ack_outside_clear_init_and_one_up_save_restore(self):
        m = ModernMachine()
        expected = {'zMusicData': 0x1380, 'zStack': 0x1B80, 'zAbsVar': 0x1B80,
                    'zTracksSongStart': 0x1B98, 'zTracksSongEnd': 0x1D3C,
                    'zTracksSFXStart': 0x1D3C, 'zTracksSFXEnd': 0x1E38,
                    'zTracksSaveStart': 0x1E38, 'zTracksSaveEnd': 0x1FF4, 'zHybridAck': 0x1FF4}
        for label, address in expected.items():
            self.assertEqual(m.symbols[label], address)
        for routine in ('zClearTrackPlaybackMem', 'zInitMusicPlayback'):
            m.setz('zHybridAck', 0xA5)
            m.callz(routine)
            self.assertEqual(m.getz('zHybridAck'), 0xA5)
        m.callz('zPlaySoundByIndex', m.symbols['MusID_Title'])
        m.setz('zHybridAck', 0xA5)
        m.callz('zPlaySoundByIndex', m.symbols['MusID_ExtraLife'])
        self.assertEqual(m.getz('zHybridAck'), 0xA5)
        self.assertTrue(m.getz('zAbsVar.1upPlaying'))
        # Run actual VInts until the 1-up's E4 restore executes.
        for _frame in range(600):
            m.vint_frame()
            self.assertEqual(m.getz('zHybridAck'), 0xA5)
            if not m.getz('zAbsVar.1upPlaying'):
                break
        else:
            self.fail('Native 1-up never restored')
        self.assertTrue(m.getz('zSongFM1.PlaybackControl') & 0x80)
        print(f'ACK survives clear/init and actual 1-up save/restore ({_frame + 1} VInts)')

    def test_warm_and_cold_game_init_clear_handoff_before_service(self):
        m = ModernMachine()
        for state in (1, 2, 255):
            m.set68('ForgeModernHandoff', state)
            # GameInit is common to both boot paths. Stop immediately after
            # its actual clear loop, before unrelated VDP setup starts.
            stop = m.symbols['GameClrRAM'] + 6
            m.cpu.emu_start(m.symbols['GameInit'], stop, count=100000)
            self.assertEqual(m.cpu.reg_read(UC_M68K_REG_PC), stop)
            self.assertEqual(m.state, 0)
            m.input()
            self.assertEqual(m.snapshot(), (0, 0, 0, 0x80, 0))
        self.assertEqual(m.mdplus, [])

    def test_f6_invalid_f7_private_stock_command_and_script_namespaces(self):
        m = ModernMachine()
        m.callz('zPlaySoundByIndex', m.symbols['MusID_Title'])
        music = bytes(m.z80.memory[0x1B98:0x1D3C])
        m.setz('zAbsVar.QueueToPlay', 0xF6)
        m.callz('zPlaySoundByIndex', 0xF6)
        self.assertEqual(m.getz('zAbsVar.QueueToPlay'), 0x80)
        self.assertEqual(m.getz('zHybridAck'), 0)
        self.assertEqual(bytes(m.z80.memory[0x1B98:0x1D3C]), music)
        stock = modern.STOCK_MODERN_ROM_PATH.read_bytes()
        syms = modern.modern_symbols(modern.STOCK_MODERN_LISTING_PATH)
        size = int.from_bytes(stock[modern.DRIVER_LENGTH_ADDRESS:modern.DRIVER_LENGTH_ADDRESS + 2], 'big')
        original = saxman_decode(stock[modern.DRIVER_START:modern.DRIVER_START + size])
        handlers = ('zStopSoundEffects', 'zFadeOutMusic', 'zPlaySegaSound', 'zSpeedUpMusic',
                    'zSlowDownMusic', 'zStopSoundAndMusic')
        for offset, handler in enumerate(handlers):
            for driver, symbols in ((original, syms), (m.z80.memory, m.symbols)):
                address = symbols['zCommandIndex'] + offset * 4
                self.assertEqual(bytes(driver[address:address + 4]),
                                 b'\xc3' + symbols[handler].to_bytes(2, 'little') + b'\x00')
            # Execute modern dispatch up to the unchanged stock handler.
            stop = m.symbols[handler]
            m.z80.set_breakpoint(stop)
            m.z80.pc = m.symbols['zPlaySoundByIndex']
            m.z80.ix = m.symbols['zAbsVar']
            m.z80.a = 0xF8 + offset
            m.z80.ticks_to_stop = 10000
            m.z80.run()
            self.assertEqual(m.z80.pc, stop)
            self.assertEqual(m.getz('zAbsVar.QueueToPlay'), 0x80)
            self.assertEqual(m.getz('zHybridAck'), 0)
            m.z80.clear_breakpoint(stop)
        # Compare script F6/F7 destinations separately from the sound request IDs.
        for request in (0xF6, 0xF7):
            offset = (request - 0xE0) * 4 + 2
            a, b = syms['coordflagLookup'] + offset, m.symbols['coordflagLookup'] + offset
            old_target = int.from_bytes(original[a + 1:a + 3], 'little')
            names = [name for name in syms if name.startswith('cf') and syms[name] == old_target]
            self.assertEqual(len(names), 1)
            self.assertEqual(bytes(m.z80.memory[b:b + 4]),
                             b'\xc3' + m.symbols[names[0]].to_bytes(2, 'little') + b'\x00')
        m.callz('zPlaySoundByIndex', 0xF7)
        self.assertEqual(m.getz('zHybridAck'), 0xA5)
        self.assertEqual(m.mdplus, [])
        print('F6 invalid; F7 stops/ACKs; F8–FD retain all six stock targets; script F6/F7 unchanged')

    def test_ordinary_pause_unpause_remains_native(self):
        m = ModernMachine()
        m.callz('zPlaySoundByIndex', m.symbols['MusID_Title'])
        for request, flag in ((0xFE, 0x7F), (0xFF, 0x80)):
            m.call68('PlayMusic', request)
            m.input()
            self.assertEqual(m.getz('zAbsVar.StopMusic'), flag)
            self.assertEqual(m.state, 0)
            m.callz('zVInt')
            self.assertEqual(bool(m.getz('zPaused')), request == 0xFE)
            self.assertEqual(m.getz('zHybridAck'), 0)
        self.assertEqual(m.mdplus, [])


class ModernLoaderTests(unittest.TestCase):
    def test_actual_loader_equals_complete_multi_record_assembled_segment(self):
        m = ModernMachine()
        expected = modern.assembled_modern_driver(modern.PREPARED_MODERN_DIR / 'forge-s2.p')
        self.assertEqual(m.loaded, len(expected))
        self.assertEqual(bytes(m.z80.memory[:m.loaded]), expected)
        self.assertEqual(m.loaded, 4986)
        self.assertEqual(m.cpu.reg_read(UC_M68K_REG_A6), modern.DRIVER_START + 4009)
        print('Actual 68000 loader: 4009 compressed bytes -> all 4986 assembler bytes, exact match')

    def test_actual_loader_final_literal_and_match_without_overread(self):
        for packed, expected in ((b'\x01\xc9', b'\xc9'),
                                 (bytes.fromhex('0f32881bc9eef1'), bytes.fromhex('32881bc9') * 2)):
            m = ModernMachine()
            m.cpu.mem_write(modern.DRIVER_START, packed + b'\xAA' * 16)
            m.cpu.mem_write(modern.DRIVER_LENGTH_ADDRESS, len(packed).to_bytes(2, 'big'))
            m.cpu.ctl_remove_cache(0xEC04A, modern.DRIVER_START)
            m.cpu.mem_write(0xA00000, b'\xCC' * 0x2000)
            reads = []
            hook = m.cpu.hook_add(UC_HOOK_MEM_READ, lambda c, a, p, s, v, u, reads=reads: reads.append((p, s)),
                                 begin=modern.DRIVER_START, end=modern.DRIVER_START + len(packed) + 16)
            m.call68('DecompressSoundDriver')
            m.cpu.hook_del(hook)
            self.assertEqual(m.cpu.reg_read(UC_M68K_REG_A5) - 0xA00000, len(expected))
            self.assertEqual(bytes(m.cpu.mem_read(0xA00000, len(expected) + 1)), expected + b'\xCC')
            self.assertEqual(reads, [(modern.DRIVER_START + i, 1) for i in range(len(packed))])
            self.assertEqual(m.mdplus, [])

    def test_service_calls_execute_inside_stock_vint_bus_lock(self):
        # The unchanged stock VInt code holds the bus across these call sites.
        # Check their source structure, then execute the input -> ACK call.
        # This harness does not emulate bus arbitration or unrelated graphics.
        source = (modern.PREPARED_MODERN_DIR / 's2.asm').read_text()
        for start, end in (('Vint_Level:', 'Vint_S2SS:'), ('Vint_TitleCard:', 'Vint_0E:')):
            block = source.split(start, 1)[1].split(end, 1)[0]
            self.assertLess(block.index('stopZ80'), block.index('sndDriverInput'))
            self.assertLess(block.index('sndDriverInput'), block.index('startZ80'))
        m = ModernMachine()
        calls = []
        hook = m.cpu.hook_add(UC_HOOK_CODE, lambda c, p, s, u: calls.append(p),
                             begin=m.symbols['ForgeModernCheckReady'], end=m.symbols['ForgeModernCheckReady'])
        m.input()
        m.cpu.hook_del(hook)
        self.assertEqual(calls, [m.symbols['ForgeModernCheckReady']])


if __name__ == '__main__':
    unittest.main(verbosity=2)
