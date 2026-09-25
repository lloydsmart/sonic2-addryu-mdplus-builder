from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_modern

from tools.mdplus_builder import modern
from tools.mdplus_builder.common import BuildError


class ModernHandoffStructureTests(unittest.TestCase):
    def transform(self, fixture, filename, hash_name):
        with patch.object(modern, hash_name, hashlib.sha256(fixture).hexdigest()):
            return modern._prepare_modern_source(fixture, filename).decode()

    def test_each_upstream_file_has_its_own_hash_and_exact_patterns(self):
        for filename, hash_name, fixture, patterns in (
            ('s2.sounddriver.asm', 'UPSTREAM_Z80_SHA256', test_modern.ModernAdapterTests.z80_fixture,
             (modern.Z80_READY, modern.Z80_PAUSE, 'zTracksSaveEnd:\n',
              '\tensure1byteoffset 8\nzVolTLMaskTbl:', "; end of Z80 'ROM'")),
            ('s2.constants.asm', 'UPSTREAM_CONSTANTS_SHA256', test_modern.ModernAdapterTests.constants_fixture,
             (modern.RAM_HOLE,)),
        ):
            with self.subTest(filename=filename):
                with self.assertRaisesRegex(BuildError, 'structure changed'):
                    modern._prepare_modern_source(fixture, filename)
                self.transform(fixture, filename, hash_name)
                for pattern in patterns:
                    for replacement in ('', pattern * 2):
                        bad = fixture.replace(pattern.encode(), replacement.encode())
                        with self.assertRaisesRegex(BuildError, 'exactly one'):
                            self.transform(bad, filename, hash_name)

    def test_private_dispatch_follows_ready_and_precedes_pause(self):
        text = self.transform(test_modern.ModernAdapterTests.z80_fixture, 's2.sounddriver.asm', 'UPSTREAM_Z80_SHA256')
        self.assertEqual(text.count('jp z,zHybridStopMusic'), 1)
        self.assertIn(modern.Z80_READY + '    cp MusID_ForgeStop\n    jp z,zHybridStopMusic\n', text)
        self.assertIn('cp MusID_ForgeStop\n    call z,zPlaySoundByIndex\n' + modern.Z80_PAUSE, text)
        self.assertEqual(text.count('zHybridAck: ds.b 1'), 1)
        self.assertNotIn('F6', text)
        self.assertNotIn('FixDriverBugs = 1', text)
        self.assertNotIn('coordflagLookup', text)

    def test_single_shared_private_value_and_minimal_state(self):
        root = Path(modern.__file__).parent
        asm = (root / 'hybrid_modern_handoff.asm').read_text()
        z80 = (root / 'hybrid_modern_z80.asm').read_text()
        self.assertEqual(asm.count('MusID_ForgeStop = $F7'), 1)
        self.assertNotIn('$F7', z80)
        self.assertNotIn('0F7h', z80)
        self.assertEqual(asm.count('ForgeAckValue = $A5'), 1)
        self.assertIn('ld a,ForgeAckValue', z80)
        self.assertIn('zTracksSaveEnd<>zHybridAck', z80)
        self.assertIn('zHybridAck<>01FF4h', z80)
        self.assertIn('(ForgeModernHandoff>=CrossResetRAM)', asm)
        self.assertIn('(fixBugs<>0)', asm)
        self.assertEqual(modern.RAM_HANDOFF.count('ds.b 1 '), 1)
        self.assertNotIn('MDP_', asm)
        self.assertNotIn('ForgeModernDispatch', asm)
        native = modern._modern_extension_source().split('ForgeModernNativeEnd:')[0]
        self.assertNotIn('Handoff', native)
        self.assertNotIn('MusID_ForgeStop', native)

    def test_sfx_copy_exactly_three_and_delivery_clears_ack_before_queue_store(self):
        asm = Path(modern.__file__).with_name('hybrid_modern_handoff.asm').read_text()
        self.assertEqual(asm.count('moveq   #3-1,d1'), 1)
        self.assertNotIn('#4-1', asm)
        self.assertEqual(asm.count('move.b  d0,zVar.QueueToPlay(a1)'), 1)
        deliver = asm.split('.deliver:\n')[1].split('.sfx:\n')[0]
        self.assertLess(deliver.index('clr.b   (Z80_RAM+zHybridAck)'), deliver.index('move.b  #2'))
        self.assertLess(deliver.index('move.b  #2'), deliver.index('move.b  d0,zVar.QueueToPlay'))
        main = self.transform(test_modern.ModernAdapterTests.fixture, 's2.asm', 'UPSTREAM_S2_SHA256')
        self.assertEqual(main.count('jmp (ForgeModernInput).l'), 1)
        self.assertEqual(main.count('jmp (ForgeModernSaxGetByte).l'), 1)
        self.assertNotIn('fixBugs = 1', main)

    def test_z80_ack_store_is_last_and_sfx_storage_is_not_a_stop_target(self):
        asm = Path(modern.__file__).with_name('hybrid_modern_z80.asm').read_text()
        code = asm.split('zHybridCodeEnd:')[0]
        self.assertTrue(code.rstrip().endswith('ret'))
        self.assertEqual(code.count('ld (zHybridAck),a'), 1)
        self.assertLess(code.index('zHybridStopPSG:'), code.index('ld (zHybridAck),a'))
        for forbidden in ('zTracksSFX', 'zAbsVar.Queue', 'zAbsVar.SFXPriority', 'zClearTrackPlaybackMem'):
            self.assertNotIn(forbidden, code)
        self.assertIn('bit 2,(ix+zTrack.PlaybackControl)', code)
        self.assertIn('call nz,zPSGNoteOff', code)

    def test_build_retains_object_without_disabling_cleanup(self):
        lua = Path(modern.__file__).with_name('modern_build.lua').read_text()
        self.assertIn('return remove(path)', lua)
        self.assertIn('dofile("build.lua")', lua)
        self.assertIn('"forge-" .. path', lua)


class ModernObjectEvidenceTests(unittest.TestCase):
    @staticmethod
    def record(address, data):
        return b'\x51' + address.to_bytes(4, 'little') + len(data).to_bytes(2, 'little') + data

    def test_joins_every_record_and_rejects_missing_overlapping_and_duplicate_segments(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic.p'
            stub = self.record(0x2CA, b'startup')
            first = self.record(0, b'abc')
            second = self.record(3, b'def')
            path.write_bytes(b'\x89\x14' + stub + first + second + b'\x00')
            self.assertEqual(modern.assembled_modern_driver(path), b'abcdef')
            for records, error in ((stub, 'Missing'), (first + first, 'Duplicate'),
                                   (first + self.record(4, b'def'), 'Noncontiguous'),
                                   (first + self.record(2, b'def'), 'Noncontiguous'),
                                   (first + second[:-1], 'Truncated')):
                path.write_bytes(b'\x89\x14' + records)
                with self.assertRaisesRegex(BuildError, error):
                    modern.assembled_modern_driver(path)
