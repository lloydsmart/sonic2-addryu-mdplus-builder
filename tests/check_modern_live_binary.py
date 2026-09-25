"""Stage 5 integration: execute compiled 68000/Z80 code, record actual writes.

PYTHONPATH=. build/emulation-venv/bin/python tests/check_modern_live_binary.py
No WAVs or model of the intended router. Bus/chip timing is outside this harness.
"""
from __future__ import annotations

import hashlib
import re
import unittest

from check_modern_binary import NativeMachine
from check_modern_handoff_binary import ModernMachine
from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE
from unicorn.m68k_const import UC_M68K_REG_A3, UC_M68K_REG_A7, UC_M68K_REG_PC, UC_M68K_REG_SR

from tools.mdplus_builder import modern


class LiveMachine(ModernMachine):
    def request(self, name='MusID_EHZ', entry='PlayMusic'):
        self.call68(entry, self.symbols[name])

    def finish(self):
        self.input()
        assert self.getz('zAbsVar.QueueToPlay') == 0xF7
        self.callz('zVInt')
        assert self.getz('zHybridAck') == 0xA5
        self.input()

    def start(self, name='MusID_EHZ'):
        self.request(name)
        self.finish()
        self.events.clear()

    def state_bytes(self):
        return tuple(self.get68(n) for n in ('ForgeModernOwner', 'ForgeModernPending',
                                           'ForgeModernHandoff', 'ForgeModernPaused', 'ForgeModernActive'))

    def counter(self):
        return int.from_bytes(self.cpu.mem_read(0xFFF100, 4), 'big')

    def put(self, name, value, size):
        address = self.symbols[name]
        for alias in (address, address | 0xFF000000):
            self.cpu.mem_write(alias, value.to_bytes(size, 'big'))

    def duck_vint(self):
        # Enter the real common return with upstream's saved register block and
        # hardware exception frame, stop at RTE (Unicorn has no M68000 RTE).
        self.cpu.reg_write(UC_M68K_REG_SR, 0x2600)
        stack = 0xFFED00
        self.cpu.reg_write(UC_M68K_REG_A7, stack)
        registers = NativeMachine.REGISTERS[:-1]
        values = [0xA5000000 + i * 0x123 for i in range(15)]
        frame = b''.join(v.to_bytes(4, 'big') for v in values) + bytes.fromhex('231f00f00000')
        self.cpu.mem_write(stack, frame)
        stop = self.symbols['ForgeModernVintReturn'] + 20
        self.cpu.emu_start(self.symbols['VintRet'], stop, count=128)
        assert self.cpu.reg_read(UC_M68K_REG_PC) == stop
        assert bytes(self.cpu.mem_read(stop, 2)) == bytes.fromhex('4e73')
        assert [self.cpu.reg_read(r) for r in registers] == values
        assert self.cpu.reg_read(UC_M68K_REG_A7) == stack + 60
        assert bytes(self.cpu.mem_read(stack + 60, 6)) == frame[-6:]


class ModernLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        modern.verify_modern(modern.MODERN_ROM_PATH)
        modern.verify_stock_modern(modern.STOCK_MODERN_ROM_PATH)

    def test_native_to_mdplus_only_after_actual_z80_ack_store(self):
        m = LiveMachine()
        m.callz('zPlaySoundByIndex', m.symbols['MusID_Title'])
        trace = [('title', m.state_bytes(), m.snapshot(), list(m.commands))]
        m.request()
        trace.append(('request', m.state_bytes(), m.snapshot(), list(m.commands)))
        self.assertEqual(m.state_bytes(), (1, 0x82, 1, 0, 0))
        m.input()
        self.assertEqual(m.commands, [])
        trace.append(('deliver', m.state_bytes(), m.snapshot(), list(m.commands)))
        before_ack = m.symbols['zHybridCodeEnd'] - 4
        m.z80.set_breakpoint(before_ack)
        m.z80.pc = m.symbols['zPlaySoundByIndex']
        m.z80.ix = m.symbols['zAbsVar']
        m.z80.a, m.z80.sp = 0xF7, 0x1B60
        m.z80.memory[0x1B60:0x1B62] = b'\x00\x70'
        m.z80.ticks_to_stop = 100000
        m.z80.run()
        self.assertEqual(m.z80.pc, before_ack)
        self.assertEqual(m.getz('zHybridAck'), 0)
        self.assertEqual(m.commands, [])
        for track in ('DAC', 'FM1', 'FM2', 'FM3', 'FM4', 'FM5', 'FM6', 'PSG1', 'PSG2', 'PSG3'):
            self.assertFalse(m.getz(f'zSong{track}.PlaybackControl') & 0x80)
        trace.append(('silent/pre-A5', m.state_bytes(), m.snapshot(), list(m.commands)))
        m.z80.clear_breakpoint(before_ack)
        m.z80.ticks_to_stop = 100000
        m.z80.run()
        self.assertEqual(m.getz('zHybridAck'), 0xA5)
        self.assertEqual(m.commands, [])
        trace.append(('A5', m.state_bytes(), m.snapshot(), list(m.commands)))
        m.input()
        self.assertEqual(m.state_bytes(), (1, 0, 0, 0, 1))
        self.assertEqual(m.commands, [0x15FF, 0x1203])
        trace.append(('service', m.state_bytes(), m.snapshot(), list(m.commands)))
        print('Native title -> EHZ: (owner,pending,handoff,pause,active), (handoff,M0,M1,Q,ACK), commands:', trace)

    def test_direct_supported_switch_and_pending_replacement(self):
        m = LiveMachine()
        m.request()
        m.request('MusID_CPZ')
        self.assertEqual(m.state_bytes(), (1, 0x8E, 1, 0, 0))
        self.assertEqual(m.snapshot()[1:3], (0xF7, 0))
        self.assertEqual(m.commands, [])
        m.finish()
        self.assertEqual(m.commands, [0x15FF, 0x1205])
        m.events.clear()
        m.request()
        self.assertEqual(m.commands, [0x15FF, 0x1203])
        self.assertEqual(m.snapshot()[1:4], (0, 0, 0x80))
        m.events.clear()
        m.request('MusID_CPZ')
        self.assertEqual(m.commands, [0x15FF, 0x1205])
        self.assertEqual(m.snapshot()[1:4], (0, 0, 0x80))
        print('Pending EHZ -> CPZ: one F7, only 15FF/1205 after A5; owned EHZ -> CPZ: 15FF/1205, no F7')

    def test_native_transition_cancellation_and_stale_ack(self):
        for phase in ('queued0', 'queued1', 'delivered', 'acknowledged', 'active'):
            with self.subTest(phase=phase):
                m = LiveMachine()
                if phase == 'queued1':
                    m.set68('Sound_Queue.Music0', m.symbols['SndID_Jump'])
                m.request()
                if phase in ('delivered', 'acknowledged', 'active'):
                    m.input()
                if phase in ('acknowledged', 'active'):
                    m.callz('zVInt')
                if phase == 'active':
                    m.input()
                m.events.clear()
                m.request('MusID_Boss')
                self.assertEqual(m.commands, [0x1300])
                self.assertEqual(m.state_bytes(), (0, 0, 0, 0, 0))
                self.assertEqual(m.get68('ForgeModernDuck'), 0)
                self.assertEqual(m.counter(), 0)
                self.assertNotIn(0xF7, m.snapshot()[1:3])
                self.assertIn(0x93, m.snapshot()[1:3])
                if phase == 'delivered':
                    m.input()
                    self.assertEqual(m.snapshot()[1], 0x93)  # waits behind delivered F7
                    m.callz('zVInt')
                # queued1 preserves original SFX in M0; deliver/consume before boss.
                if phase == 'queued1':
                    m.input()
                    m.callz('zPlaySoundByIndex', m.getz('zAbsVar.QueueToPlay'))
                m.input()
                self.assertEqual(m.getz('zHybridAck'), 0)
                self.assertEqual(m.getz('zAbsVar.QueueToPlay'), 0x93)
                m.callz('zPlaySoundByIndex', 0x93)
                self.assertTrue(m.getz('zSongFM1.PlaybackControl') & 0x80)
                self.assertEqual(m.commands, [0x1300])
                print('Cancel/transition', phase, '-> native boss queued/consumed; stale A5 discarded; commands=1300')

    def test_new_handoff_discards_old_ack_and_retries_false_ready(self):
        m = LiveMachine()
        m.request()
        m.input()
        m.request('MusID_Boss')
        m.callz('zVInt')  # late ACK of cancelled request
        m.request('MusID_CPZ')
        m.events.clear()
        m.input()  # must discard old A5 and deliver a fresh F7
        self.assertEqual(m.snapshot(), (2, 0, 0, 0xF7, 0))
        self.assertEqual(m.commands, [])
        m.setz('zAbsVar.QueueToPlay', 0x80)
        m.input()
        self.assertEqual(m.snapshot(), (2, 0, 0, 0xF7, 0))
        self.assertEqual(m.commands, [])
        m.callz('zVInt')
        m.input()
        self.assertEqual(m.commands, [0x15FF, 0x1205])
        print('New epoch: old A5 discarded, false-ready retries F7, only fresh A5 starts CPZ')

    def test_paused_native_then_pause_during_handoff_and_resume(self):
        for resume_before_ack in (False, True):
            m = LiveMachine()
            m.callz('zPlaySoundByIndex', m.symbols['MusID_Title'])
            m.setz('zAbsVar.StopMusic', 0x7F)
            m.callz('zVInt')
            m.request()
            m.request('MusID_Pause')
            self.assertEqual(m.commands, [0x1300])
            self.assertEqual(m.snapshot()[1:3], (0xF7, 0))
            if resume_before_ack:
                m.request('MusID_Unpause')
                self.assertEqual(m.commands, [0x1300])
            m.finish()
            self.assertEqual(m.getz('zPaused'), 0)
            if not resume_before_ack:
                self.assertEqual(m.state_bytes(), (1, 0x82, 0, 1, 0))
                self.assertEqual(m.commands, [0x1300])
                m.request('MusID_Unpause')
            self.assertEqual(m.state_bytes(), (1, 0, 0, 0, 1))
            self.assertEqual(m.commands, [0x1300, 0x15FF, 0x1203])
        print('Pause during F7: 1300; A5 leaves pending while paused; unpause -> 15FF/1203')

    def test_active_pause_resume_fade_stop_silent_unpause(self):
        m = LiveMachine()
        m.start()
        m.request('MusID_Pause')
        self.assertEqual(m.state_bytes(), (1, 0, 0, 1, 1))
        m.request('MusID_Unpause')
        self.assertEqual(m.commands, [0x1300, 0x1400])
        self.assertEqual(m.snapshot()[1:3], (0, 0))
        m.request('MusID_Unpause')
        self.assertEqual(m.commands, [0x1300, 0x1400])
        for name, command in (('MusID_FadeOut', 0x1328), ('MusID_Stop', 0x1300)):
            for pending in (False, True):
                m = LiveMachine()
                if pending:
                    m.request()
                else:
                    m.start()
                m.request('MusID_ExtraLife')
                m.request(name)
                self.assertEqual(m.state_bytes(), (1, 0, int(pending), 0, 0))
                self.assertEqual(m.get68('ForgeModernDuck'), 0)
                self.assertEqual(m.counter(), 0)
                self.assertEqual(m.commands, [command])
                m.request('MusID_Unpause')
                m.request('MusID_Pause')
                self.assertEqual(m.commands, [command])
                if pending:
                    m.finish()
                    self.assertEqual(m.commands, [command])
        print('Active pause/unpause=1300/1400; fade=1328, stop=1300; silent owner cannot resume old BGM')

    def test_speed_controls_and_native_sega_remain_native(self):
        for owner in (0, 1):
            m = LiveMachine()
            if owner:
                m.start()
            for name in ('MusID_SpeedUp', 'MusID_SlowDown'):
                m.request(name)
                self.assertEqual(m.commands, [])
                if owner:
                    self.assertEqual(m.snapshot()[1:3], (0, 0))
                else:
                    self.assertEqual(m.get68('Sound_Queue.Music0'), m.symbols[name])
                    m.input()
                    m.callz('zPlaySoundByIndex', m.getz('zAbsVar.QueueToPlay'))
            m.request('SndID_SegaSound', 'PlaySound')
            self.assertEqual(m.get68('Sound_Queue.SFX0'), 0xFA)
            self.assertEqual(m.get68('ForgeModernOwner'), owner)
            self.assertEqual(m.commands, [])
        print('Speed FB/FC: native passthrough, MD+ no-op; native SEGA FA -> SFX0; no track32 or 33-48')

    def test_representative_gameplay_sequences_through_both_cpus(self):
        sequences = (
            ('MusID_Title', 'MusID_EHZ', 'MusID_Invincible', 'MusID_EHZ'),
            ('MusID_EHZ', 'MusID_Boss', 'MusID_EHZ'),
            ('MusID_EHZ', 'MusID_EndLevel'),
            ('MusID_CPZ', 'MusID_Countdown', 'MusID_CPZ'),
        )
        routes = {'MusID_EHZ': 0x1203, 'MusID_CPZ': 0x1205}
        for sequence in sequences:
            m = LiveMachine()
            trace = []
            for cue in sequence:
                m.events.clear()
                m.request(cue)
                if cue in routes:
                    self.assertEqual(m.commands, [])
                    m.finish()
                    self.assertEqual(m.commands, [0x15FF, routes[cue]])
                    self.assertFalse(m.getz('zSongFM1.PlaybackControl') & 0x80)
                else:
                    m.input()
                    self.assertEqual(m.getz('zAbsVar.QueueToPlay'), m.symbols[cue])
                    m.callz('zPlaySoundByIndex', m.symbols[cue])
                    self.assertTrue(m.getz('zSongFM1.PlaybackControl') & 0x80)
                    self.assertEqual(m.get68('ForgeModernOwner'), 0)
                trace.append((cue, list(m.commands)))
            print('Gameplay:', trace)

    def test_queued_music_is_superseded_but_sfx_and_sega_are_preserved(self):
        for queued, preserved in ((0x99, False), (0x93, False), (0xFE, False),
                                  (0xA0, True), (0xB5, True), (0xFA, True)):
            m = LiveMachine()
            m.set68('Sound_Queue.Music0', queued)
            m.set68('Sound_Queue.Music1', 0x91)
            m.request()
            self.assertEqual(m.snapshot()[1:3], (queued, 0xF7) if preserved else (0xF7, 0))
            self.assertEqual(m.commands, [])

    def test_every_actual_extra_life_call_path_and_native_jingle(self):
        paths = ('CollectRing_1P', 'CollectRing_Tails', 'sonic_1up', 'tails_1up', 'AddPoints', 'AddPoints2')
        for owner in (0, 1):
            for path in paths:
                with self.subTest(owner=owner, path=path):
                    m = LiveMachine()
                    if owner:
                        m.start()
                    else:
                        m.callz('zPlaySoundByIndex', m.symbols['MusID_Title'])
                    m.put('Ring_count', 99, 2)
                    m.put('Ring_count_2P', 99, 2)
                    m.put('Two_player_mode', 1, 2)
                    m.put('Next_Extra_life_score', 1, 4)
                    m.put('Next_Extra_life_score_2P', 1, 4)
                    m.cpu.reg_write(UC_M68K_REG_A3, 0)
                    starts = []
                    hook = m.cpu.hook_add(UC_HOOK_CODE, lambda c, a, s, u, starts=starts: starts.append(a),
                                         begin=m.symbols['ForgeModernDuckStart'], end=m.symbols['ForgeModernDuckStart'])
                    m.call68(path, 1)
                    m.cpu.hook_del(hook)
                    self.assertEqual(len(starts), 1)
                    self.assertEqual(m.get68('ForgeModernDuck'), owner)
                    self.assertEqual(m.counter(), 0)
                    self.assertEqual(m.get68('ForgeModernOwner'), owner)
                    queue = 'Sound_Queue.SFX1' if path.startswith('CollectRing') else 'Sound_Queue.Music0'
                    self.assertEqual(m.get68(queue), 0x98)
                    self.assertEqual(m.commands, [])
                    m.input()
                    if path.startswith('CollectRing'):
                        m.vint_frame()
                    else:
                        m.callz('zPlaySoundByIndex', 0x98)
                    self.assertTrue(m.getz('zAbsVar.1upPlaying'))
                    if owner:
                        m.duck_vint()
                        self.assertEqual(m.commands, [0x1519])
                    print('Extra life:', path, 'owner', owner, '->', queue, '=98; duck starts once; Z80 native jingle active')

    def test_duck_255_vints_pause_handoff_and_native_jingle_restore(self):
        m = LiveMachine()
        m.start()
        m.request('MusID_ExtraLife')
        m.input()
        m.callz('zPlaySoundByIndex', 0x98)
        for blocked in ('ForgeModernPaused', 'ForgeModernHandoff'):
            m.set68(blocked, 1)
            for _ in range(3):
                m.duck_vint()
            self.assertEqual(m.counter(), 0)
            self.assertEqual(m.commands, [])
            m.set68(blocked, 0)
        for frame in range(254):
            m.duck_vint()
            m.vint_frame()
            self.assertEqual(m.counter(), frame + 1)
            self.assertEqual(m.get68('ForgeModernDuck'), 1)
        self.assertFalse(m.getz('zAbsVar.1upPlaying'))
        self.assertFalse(m.getz('zSongFM1.PlaybackControl') & 0x80)
        m.duck_vint()
        self.assertEqual(m.commands, [0x1519] * 255 + [0x15FF])
        self.assertEqual(m.counter(), 0)
        self.assertEqual(m.get68('ForgeModernDuck'), 0)
        self.assertEqual(m.state_bytes(), (1, 0, 0, 0, 1))
        m.duck_vint()
        self.assertEqual(len(m.commands), 256)
        print('Duck: paused/handoff VInts frozen; 255 x 1519 then 15FF, counter/flag clear, no track restart')

    def test_native_sfx_progress_under_active_mdplus_without_track_restart(self):
        m = LiveMachine()
        m.start()
        for _ in range(16):
            m.request('SndID_Jump', 'PlaySound')
            m.request('SndID_Ring', 'PlaySound2')
            m.input()
            m.vint_frame()
            self.assertEqual(m.getz('zAbsVar.Queue0'), 0)
            # Stock zCycleQueue returns after the first selected effect.
            # The second request must survive and be consumed next frame.
            self.assertEqual(m.getz('zAbsVar.Queue1'), m.symbols['SndID_Ring'])
            m.vint_frame()
            self.assertEqual(m.getz('zAbsVar.Queue1'), 0)
            self.assertTrue(m.getz('zSFX_PSG1.PlaybackControl') & 0x80)
            self.assertEqual(m.state_bytes(), (1, 0, 0, 0, 1))
            self.assertEqual(m.commands, [])
        print('Active MD+: jump/ring requests consumed for 16 pairs of Z80 VInts, no ownership change or track restart')

    def test_direct_pause_sites_exact_footprint_registers_ccr_and_routing(self):
        m = NativeMachine(modern.MODERN_ROM_PATH.read_bytes())
        for site, request, target in ((0x13AC, 0xFE, 'ForgeModernPauseRequest'),
                                      (0x13F2, 0xFF, 'ForgeModernUnpauseRequest'),
                                      (0x1406, 0xFF, 'ForgeModernUnpauseRequest'),
                                      (0x541A, 0xFF, 'ForgeModernUnpauseRequest')):
            self.assertEqual(bytes(m.cpu.mem_read(site, 6)), bytes.fromhex('4eb9') +
                             modern.ROUTER_ADDRESSES[target].to_bytes(4, 'big'))
            for owner in (0, 1):
                for ccr in range(32):
                    state = {'ForgeModernOwner': owner, 'ForgeModernActive': owner,
                             'ForgeModernPaused': owner if request == 0xFF else 0}
                    q, sr, writes, _ = m.call(0x12345678, 0, 0, ccr, modern.ROUTER_ADDRESSES[target], state)
                    self.assertEqual(sr, 0x2308 | ccr & 16)
                    self.assertEqual(q[0], 0 if owner else request)
                    commands = [v for a, _, v in writes if a == 0x3F7FE]
                    self.assertEqual(commands, [0x1300 if request == 0xFE else 0x1400] if owner else [])
        prepared = (modern.PREPARED_MODERN_DIR / 's2.asm').read_text()
        self.assertIsNone(re.search(r'move\.b\s+#MusID_(?:Pause|Unpause),\(Sound_Queue.Music[01]\)', prepared))
        print('Direct pause sites: 0013AC FE; 0013F2/001406/00541A FF, all six-byte calls, all CCRs/registers preserved')

    def test_cold_warm_and_failed_checksum_first_mdplus_write(self):
        for boot in ('cold', 'warm', 'bad_checksum'):
            with self.subTest(boot=boot):
                m = LiveMachine()
                for name, (_, size) in modern.RAM_STATE.items():
                    m.put(name, (1 << (size * 8)) - 1, size)
                m.put('Sound_Queue.Music0', 0x98, 1)
                m.put('Sound_Queue.Music1', 0xF7, 1)
                m.cpu.reg_write(UC_M68K_REG_SR, 0x2700)
                m.cpu.reg_write(UC_M68K_REG_A7, 0xFFFFFE00)
                if boot == 'warm':
                    m.cpu.mem_write(0xA1000D, b'\x40')
                    m.put('Checksum_fourcc', int.from_bytes(b'init', 'big'), 4)
                if boot == 'bad_checksum':
                    m.cpu.mem_write(0x80000, b'\x00\x01' if m.rom[0x80000:0x80002] != b'\x00\x01' else b'\x00\x02')
                # Bus arbitration model: a request is granted immediately.
                # All checksum, RAM clearing, calls and MD+ stores execute ROM code.
                m.cpu.hook_add(UC_HOOK_MEM_READ, lambda c, a, p, s, v, u: c.mem_write(0xA11100, b'\x00\x00'),
                               begin=0xA11100, end=0xA11101)
                trace = []
                for name in ('ChecksumTest', 'GameInit', 'GameClrRAM', 'ForgeModernInit', 'ForgeModernReset'):
                    address = m.symbols[name]
                    # GameClrRAM executes many times; record its first visit.
                    m.cpu.hook_add(UC_HOOK_CODE,
                                   lambda c, a, s, u, n=name, trace=trace: trace.append(n) if n not in trace else None,
                                   begin=address, end=address)
                first_writes = []
                m.cpu.hook_add(UC_HOOK_MEM_WRITE, lambda c, a, p, s, v, u, writes=first_writes, trace=trace: writes.append((p, v, list(trace))),
                               begin=0x3F7FA, end=0x3F7FF)
                stop = m.symbols['ChecksumFailed_Loop'] if boot == 'bad_checksum' else 0x38A
                m.cpu.emu_start(m.symbols['GameProgram'], stop, count=4_000_000)
                self.assertEqual(m.cpu.reg_read(UC_M68K_REG_PC), stop)
                if boot == 'bad_checksum':
                    self.assertEqual(m.commands, [])
                    self.assertEqual(first_writes, [])
                    self.assertNotIn('GameInit', trace)
                else:
                    self.assertEqual(m.commands, [0x1300])
                    self.assertEqual([p for p, _, _ in first_writes], [0x3F7FA, 0x3F7FE, 0x3F7FA])
                    self.assertEqual(trace[-4:], ['GameInit', 'GameClrRAM', 'ForgeModernInit', 'ForgeModernReset'])
                    self.assertEqual('ChecksumTest' in trace, boot == 'cold')
                    for name, (address, size) in modern.RAM_STATE.items():
                        self.assertEqual(bytes(m.cpu.mem_read(address, size)), bytes(size), name)
                    self.assertEqual(m.snapshot()[1:3], (0, 0))
                print('Startup', boot, trace, 'MD+ commands', m.commands)

    def test_frozen_driver_backend_and_all_extra_life_sites_accounted_for(self):
        m = LiveMachine()
        driver = bytes(m.z80.memory[:m.loaded])
        self.assertEqual(len(driver), 4986)
        self.assertEqual(hashlib.sha256(driver).hexdigest(), modern.Z80_SHA256)
        self.assertEqual(m.rom[0x100000:0x1002B6], modern.expected_modern_extension())
        source = (modern.SOURCE_MODERN_DIR / 's2.asm').read_text()
        self.assertEqual(len(re.findall(r'^\s*move\.w\s+#MusID_ExtraLife,d0', source, re.M)), 6)
        # All six call sites remain byte-identical and target audited wrappers.
        pattern = bytes.fromhex('303c00984ef9')
        sites = [match.start() for match in re.finditer(re.escape(pattern), m.rom)]
        self.assertEqual(sites, [0x12012, 0x1206E, 0x1294A, 0x12960, 0x40D36, 0x40D7E])
        for address in sites:
            self.assertIn(int.from_bytes(m.rom[address + 6:address + 10], 'big'), (0x135E, 0x1376))
        print('Six unchanged extra-life request sites:', [f'{a:06X}' for a in sites])


if __name__ == '__main__':
    unittest.main(verbosity=2)
