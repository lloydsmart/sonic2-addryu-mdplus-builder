from __future__ import annotations

import re
import unittest
from pathlib import Path
from unittest.mock import patch

from hybrid_machine import MUSIC_IDS, RouterMachine

from tools.mdplus_builder.common import BuildError
from tools.mdplus_builder.source import (
    ADDRYU_TRACKS,
    EXPECTED_CONVERSION_COUNTS,
    _audit_mdplus_transactions,
    _hybrid_msu_source,
    _hybrid_z80_source,
    _replace_exact,
)

EXPECTED = {
    'EHZ': 3, 'CPZ': 5, 'ARZ': 7, 'CNZ': 8, 'HTZ': 9, 'MCZ': 10,
    'OOZ': 11, 'MTZ': 12, 'SCZ': 13, 'WFZ': 14, 'DEZ': 15,
    'SpecStage': 29, 'EHZ_2P': 26, 'CNZ_2P': 27, 'MCZ_2P': 28, 'HPZ': 31,
}


class HybridRouterTests(unittest.TestCase):
    def test_exact_policy_and_every_music_id(self):
        self.assertEqual(dict(ADDRYU_TRACKS), {f'MusID_{k}': v for k, v in EXPECTED.items()})
        self.assertEqual(len(ADDRYU_TRACKS), 16)
        for name in MUSIC_IDS:
            with self.subTest(name=name):
                m = RouterMachine()
                m.call('PlayMusic', f'MusID_{name}')
                if name in EXPECTED:
                    self.assertEqual(m.commands, [])
                    m.handoff()
                    self.assertEqual(m.commands[-1], 0x1200 | EXPECTED[name])
                    self.assertEqual(m.get('v_MusicBackend'), 1)
                else:
                    self.assertEqual(m.commands, [])
                    self.assertEqual(m.get('Music_to_play'), MUSIC_IDS[name])
                    self.assertEqual(m.get('v_MusicBackend'), 0)

    def test_policy_reads_only_the_assembly_template(self):
        original = Path.read_text
        reads = []

        def read(path, *args, **kwargs):
            reads.append(path.name)
            return original(path, *args, **kwargs)

        with patch.object(Path, 'read_text', read), patch.object(Path, 'exists', side_effect=AssertionError):
            first = _hybrid_msu_source()
        self.assertEqual(reads, ['hybrid.asm'])
        self.assertEqual(first, _hybrid_msu_source())
        self.assertNotRegex(first, r'(?i)manifest|\.wav|\.cue|tracks\.json')

    def test_stock_two_mailboxes_preserve_ids_and_latest_second_request(self):
        m = RouterMachine()
        for name in ['Boss', 'Invincible', 'Countdown']:
            m.call('PlayMusic', f'MusID_{name}')
        self.assertEqual(m.get('Music_to_play'), MUSIC_IDS['Boss'])
        self.assertEqual(m.get('Music_to_play_2'), MUSIC_IDS['Countdown'])

    def test_temporary_native_music_returns_through_normal_requests(self):
        for level, temporary in [('EHZ', 'Boss'), ('CPZ', 'Invincible'), ('CPZ', 'Countdown')]:
            m = RouterMachine()
            m.call('PlayMusic', f'MusID_{level}')
            m.handoff()
            offset = len(m.events)
            m.call('PlayMusic', f'MusID_{temporary}')
            self.assertEqual(m.commands[-1], 0x1300)
            events = m.events[offset:]
            stop = next(i for i, e in enumerate(events) if e[:2] == (m.value('MDP_CMD'), 0x1300))
            owner = next(i for i, e in enumerate(events) if e[:2] == (m.value('v_MusicBackend'), 0))
            queue = next(i for i, e in enumerate(events) if e[:2] == (m.value('Music_to_play'), MUSIC_IDS[temporary]))
            self.assertLess(stop, owner)
            self.assertLess(owner, queue)
            m.deliver()
            m.set('Z80_RAM+zAbsVar.QueueToPlay', 0x80)
            m.call('PlayMusic', f'MusID_{level}')
            before = m.commands[:]
            m.call('HybridCheckReady')
            self.assertEqual(m.commands, before)
            m.handoff()
            self.assertEqual(m.commands[-1], 0x1200 | EXPECTED[level])

    def test_ready_without_ack_retries_and_never_starts_mdplus(self):
        m = RouterMachine()
        m.call('PlayMusic', 'MusID_EHZ')
        m.deliver()
        m.call('HybridCheckReady')
        self.assertEqual(m.commands, [])
        m.set('Z80_RAM+zAbsVar.QueueToPlay', 0x80)
        m.call('HybridCheckReady')
        self.assertEqual(m.commands, [])
        self.assertEqual(m.get('Music_to_play'), m.value('MusID_HybridStop'))
        m.handoff()
        self.assertEqual(m.commands[-1], 0x1203)

    def test_pending_track_change_and_native_cancellation(self):
        for delivered in [False, True]:
            m = RouterMachine()
            m.call('PlayMusic', 'MusID_EHZ')
            if delivered:
                m.deliver()
            m.call('PlayMusic', 'MusID_CPZ')
            self.assertEqual(m.get('v_MDPlusPending'), MUSIC_IDS['CPZ'])
            m.call('PlayMusic', 'MusID_Boss')
            if delivered:
                m.set('Z80_RAM+zAbsVar.QueueToPlay', 0x80)
                m.set('Z80_RAM+zHybridAck', m.value('HybridAckValue'))
            m.call('HybridCheckReady')
            self.assertEqual(m.commands, [0x1300])
            self.assertEqual(m.get('Music_to_play'), MUSIC_IDS['Boss'])
            self.assertEqual(m.get('v_MusicBackend'), 0)

    def test_handoff_preserves_two_queued_sound_effects(self):
        m = RouterMachine()
        m.set('Music_to_play', 0xB5)
        m.set('Music_to_play_2', 0xC0)
        m.call('PlayMusic', 'MusID_EHZ')
        self.assertEqual(m.get('Music_to_play'), 0xB5)
        self.assertEqual(m.get('Music_to_play_2'), 0xC0)
        m.call('HybridCheckReady')
        self.assertEqual(m.deliver(), 0xB5)
        m.set('Z80_RAM+zAbsVar.QueueToPlay', 0x80)
        m.call('HybridCheckReady')
        self.assertEqual(m.get('Music_to_play'), m.value('MusID_HybridStop'))
        self.assertEqual(m.get('Music_to_play_2'), 0xC0)
        m.handoff()
        self.assertEqual(m.deliver(), 0xC0)

    def test_controls_by_owner_and_pause_cannot_revive_old_backend(self):
        for control in ['FadeOut', 'Stop', 'Pause', 'Unpause', 'SpeedUp', 'SlowDown']:
            m = RouterMachine()
            m.call('PlayMusic', f'MusID_{control}')
            self.assertEqual(m.get('Music_to_play'), m.value(f'MusID_{control}'))
            self.assertEqual(m.commands, [])
        m = RouterMachine()
        m.call('PlayMusic', 'MusID_EHZ')
        m.handoff()
        m.call('PlayMusic', 'MusID_Pause')
        m.call('PlayMusic', 'MusID_Unpause')
        self.assertEqual(m.commands[-2:], [0x1300, 0x1400])
        self.assertEqual(m.get('Music_to_play'), 0)
        m.call('PlayMusic', 'MusID_Boss')
        before = m.commands[:]
        m.deliver()
        m.call('PlayMusic', 'MusID_Pause')
        m.deliver()
        m.call('PlayMusic', 'MusID_Unpause')
        self.assertEqual(m.commands, before)
        self.assertEqual(m.get('Music_to_play'), 0xFF)

    def test_stop_and_fade_cannot_be_resurrected_by_pause(self):
        for control, command in [('Stop', 0x1300), ('FadeOut', 0x1328)]:
            m = RouterMachine()
            m.call('PlayMusic', 'MusID_EHZ')
            m.handoff()
            m.call('PlayMusic', f'MusID_{control}')
            self.assertEqual(m.commands[-1], command)
            before = m.commands[:]
            m.call('PlayMusic', 'MusID_Pause')
            m.call('PlayMusic', 'MusID_Unpause')
            self.assertEqual(m.commands, before)

    def test_pause_pending_handoff_defers_play_until_unpause(self):
        m = RouterMachine()
        m.call('PlayMusic', 'MusID_EHZ')
        m.call('PlayMusic', 'MusID_Pause')
        m.handoff()
        self.assertEqual(m.commands, [0x1300])
        m.call('PlayMusic', 'MusID_Unpause')
        self.assertEqual(m.commands[-1], 0x1203)

    def test_speed_shoes_never_restart_mdplus_and_native_sfx_keep_ownership(self):
        m = RouterMachine()
        m.call('PlayMusic', 'MusID_CPZ')
        m.handoff()
        before = m.commands[:]
        for request in ['MusID_SpeedUp', 'MusID_SlowDown', 0xB5, 'MusID_StopSFX']:
            m.call('PlayMusic', request)
        self.assertEqual(m.commands, before)
        self.assertEqual(m.get('v_MusicBackend'), 1)
        m.call('PlayMusic', 'MusID_EHZ')
        self.assertEqual(m.commands[-1], 0x1203)
        self.assertEqual(m.get('v_MDPlusHandoff'), 0)

    def test_one_up_ducking_retains_owner_and_restores_volume(self):
        m = RouterMachine()
        m.call('PlayMusic', 'MusID_EHZ')
        m.handoff()
        m.call('PlayMusic', 'MusID_ExtraLife')
        self.assertEqual(m.get('Music_to_play'), MUSIC_IDS['ExtraLife'])
        self.assertEqual(m.get('v_MusicBackend'), 1)
        for _ in range(255):
            m.call('Vint_MSUMD')
        self.assertEqual(m.commands[-2:], [0x1519, 0x15FF])
        self.assertEqual(m.get('v_MSU_1upFlag'), 0)
        m.call('PlayMusic', 'MusID_Boss')
        before = m.commands[:]
        m.call('msuExtraLife')
        m.call('Vint_MSUMD')
        self.assertEqual(m.commands, before)

    def test_reset_clears_all_state(self):
        m = RouterMachine()
        for symbol in ['v_MusicBackend', 'v_MDPlusPending', 'v_MDPlusHandoff',
                       'v_MDPlusPaused', 'v_MDPlusActive', 'v_MSU_1upFlag']:
            m.set(symbol, 255)
        m.call('HybridReset')
        self.assertEqual(m.commands, [0x1300])
        for symbol in ['v_MusicBackend', 'v_MDPlusPending', 'v_MDPlusHandoff',
                       'v_MDPlusPaused', 'v_MDPlusActive', 'v_MSU_1upFlag']:
            self.assertEqual(m.get(symbol), 0)

    def test_transactions_and_only_allowed_play_commands(self):
        text = _hybrid_msu_source()
        counts = _audit_mdplus_transactions(text)
        for name, count in counts.items():
            self.assertEqual(count, EXPECTED_CONVERSION_COUNTS[name])
        self.assertEqual(set(map(int, re.findall(r'#\(\$1200\|(\d+)\)', text))), set(EXPECTED.values()))
        self.assertNotRegex(text, r'findAndPlayFastTrack|msuChangeTrackSpeed|msuRestoreTrackSpeed|\$1100')
        with self.assertRaises(BuildError):
            _audit_mdplus_transactions(text.replace('    move.w  #0,(MDP_CTRL).l\n', '', 1))
        with self.assertRaises(BuildError):
            _replace_exact('wrong source', 'required anchor', 'replacement')

    def test_z80_extension_separates_ack_and_does_not_reset_sfx(self):
        fixture = ('zTracksSaveEnd:\n'
                   '\tcp\tMusID__End\t\t\t; is it music (less than index 20)?\n'
                   '\tld\ta,(zAbsVar.StopMusic)\t; Get pause/unpause flag\n'
                   "; end of Z80 'ROM'")
        text = _hybrid_z80_source(fixture)
        self.assertNotIn('MusID_HybridReady', text)
        self.assertIn('cp MusID_HybridStop\n    jp z,zHybridStopMusic', text)
        self.assertIn('ld (zHybridAck),a', text)
        extension = text[text.index('zHybridStopMusic:'):]
        self.assertNotRegex(extension, r'zStopSoundEffects|zClearTrackPlaybackMem|Z80_Reset|zTracksSFX')
        self.assertIn('bit 2,(ix+zTrack.PlaybackControl)', extension)
        self.assertLess(extension.index('zHybridStopPSG:'), extension.index('ld a,HybridAckValue'))
        self.assertIn('rst zWriteFMIorII', extension)


if __name__ == '__main__':
    unittest.main()
