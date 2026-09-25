"""Execute the actual stock and prepared-modern PlayMusic bytes with Unicorn.

Usage: PYTHONPATH=. build/emulation-venv/bin/python tests/check_modern_binary.py
Requires make build-stock-modern and make build-modern. No game data fixtures.
This executes mailbox/routing/CCR contracts, without console or audio timing.
"""
from __future__ import annotations

import unittest

from unicorn import UC_ARCH_M68K, UC_HOOK_MEM_WRITE, UC_MODE_BIG_ENDIAN, Uc
from unicorn.m68k_const import (
    UC_CPU_M68K_M68000,
    UC_M68K_REG_A0,
    UC_M68K_REG_A6,
    UC_M68K_REG_A7,
    UC_M68K_REG_D0,
    UC_M68K_REG_PC,
    UC_M68K_REG_SR,
)

from tools.mdplus_builder import modern


class NativeMachine:
    RETURN = 0x300000
    STACK = 0xFFFFEF00
    SNAPSHOT = 0xFFFFE000
    QUEUE = 0xFFFFFFE0
    REGISTERS = [UC_M68K_REG_D0 + i for i in range(8)] + [UC_M68K_REG_A0 + i for i in range(8)]

    def __init__(self, rom):
        self.cpu = Uc(UC_ARCH_M68K, UC_MODE_BIG_ENDIAN)
        self.cpu.ctl_set_cpu_model(UC_CPU_M68K_M68000)
        self.cpu.mem_map(0, 0x200000)
        self.cpu.mem_write(0, rom)
        # Absolute-short RAM operands are sign-extended by Unicorn. The actual
        # 68000 bus ignores that high byte; normalize addresses in write records.
        self.cpu.mem_map(0xFFFF0000, 0x10000)
        self.cpu.mem_map(self.RETURN, 0x1000)
        # Materialize lazy flags through a real MOVE SR,(a6), after RTS.
        self.cpu.mem_write(self.RETURN, bytes.fromhex('40d6'))
        self.writes = []
        self.masks = []
        self.cpu.hook_add(UC_HOOK_MEM_WRITE, self.write)

    def write(self, cpu, access, address, size, value, user):
        physical = address & 0xFFFFFF
        # Stack traffic is expected in wrappers; stack balance/registers are
        # checked independently. Retain every observable RAM and I/O write.
        if not 0xFFEE00 <= physical <= 0xFFEF04:
            self.writes.append((physical, size, value))
            self.masks.append((physical, self.cpu.reg_read(UC_M68K_REG_SR) & 0x700))

    def call(self, d0, music0, music1, ccr, entry=modern.PLAY_MUSIC_ADDRESS,
             state=None, mask=3):
        self.cpu.mem_write(0xFFFFF100, bytes(0x16))
        for name, value in (state or {}).items():
            address, size = modern.RAM_STATE[name]
            self.cpu.mem_write(address | 0xFF000000, value.to_bytes(size, 'big'))
        self.cpu.reg_write(UC_M68K_REG_SR, 0x2000 | mask << 8 | ccr)
        for index, register in enumerate(self.REGISTERS):
            self.cpu.reg_write(register, 0x12340000 + index * 0x101)
        self.cpu.reg_write(UC_M68K_REG_D0, d0)
        self.cpu.reg_write(UC_M68K_REG_A6, self.SNAPSHOT)
        self.cpu.reg_write(UC_M68K_REG_A7, self.STACK)
        before = [self.cpu.reg_read(r) for r in self.REGISTERS]
        self.cpu.mem_write(self.QUEUE, bytes([music0, 0x42, 0x81, 0xF7, music1]))
        self.cpu.mem_write(self.STACK, self.RETURN.to_bytes(4, 'big'))
        self.writes.clear()
        self.masks.clear()
        self.cpu.emu_start(entry, self.RETURN + 2, count=256)
        if self.cpu.reg_read(UC_M68K_REG_PC) != self.RETURN + 2:
            raise AssertionError(f'Entry {entry:06X} failed to return directly to its caller')
        after = [self.cpu.reg_read(r) for r in self.REGISTERS]
        expected = before[:-1] + [self.STACK + 4]
        if after != expected:
            raise AssertionError(f'Register or stack corruption: {after} != {expected}')
        sr = int.from_bytes(self.cpu.mem_read(self.SNAPSHOT, 2), 'big')
        return bytes(self.cpu.mem_read(self.QUEUE, 5)), sr, list(self.writes), after


class ModernPlayMusicBinaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        modern.verify_stock_modern(modern.STOCK_MODERN_ROM_PATH)
        modern.verify_modern(modern.MODERN_ROM_PATH)
        cls.stock = NativeMachine(modern.STOCK_MODERN_ROM_PATH.read_bytes())
        cls.prepared = NativeMachine(modern.MODERN_ROM_PATH.read_bytes())

    def test_native_requests_and_raw_helper_exhaustively_match_stock(self):
        for request in range(256):
            for music0 in (0, 0x85):
                for ccr in range(32):
                    with self.subTest(request=request, music0=music0, ccr=ccr):
                        d0 = 0xA5C30000 | request
                        expected_sr = 0x2300 | (ccr & 0x10) | (8 if request & 0x80 else 4 if request == 0 else 0)
                        expected_queue = bytes([
                            request if music0 == 0 else music0, 0x42, 0x81, 0xF7,
                            request if music0 else 0x99,
                        ])
                        expected_writes = [
                            (0xFFFFE0 if music0 == 0 else 0xFFFFE4, 1, request),
                            (NativeMachine.SNAPSHOT & 0xFFFFFF, 2, expected_sr),
                        ]
                        stock = self.stock.call(d0, music0, 0x99, ccr)
                        raw = self.prepared.call(d0, music0, 0x99, ccr, modern.IMPLEMENTATION_ADDRESS)
                        self.assertEqual(raw, stock)
                        if request not in modern.MODERN_MUSIC_IDS.values():
                            prepared = self.prepared.call(d0, music0, 0x99, ccr)
                            self.assertEqual(prepared, stock)
                            self.assertEqual(prepared[:3], (expected_queue, expected_sr, expected_writes))
                            self.assertEqual(self.prepared.masks[0][1], 0x700)

    def test_all_nonempty_first_mailboxes_choose_second_even_for_private_command_value(self):
        for music0 in range(1, 256):
            with self.subTest(music0=music0):
                stock = self.stock.call(0xDEADBEF7, music0, 0, 0x1F)
                prepared = self.prepared.call(0xDEADBEF7, music0, 0, 0x1F)
                self.assertEqual(prepared, stock)
                self.assertEqual(prepared[0], bytes([music0, 0x42, 0x81, 0xF7, 0xF7]))
                self.assertEqual(prepared[2][0], (0xFFFFE4, 1, 0xF7))

    def test_all_requests_ccrs_and_interrupt_masks_in_native_and_mdplus_states(self):
        states = ({}, {'ForgeModernOwner': 1, 'ForgeModernActive': 1},
                  {'ForgeModernOwner': 1, 'ForgeModernPending': 0x82, 'ForgeModernHandoff': 1},
                  {'ForgeModernOwner': 1, 'ForgeModernPending': 0x82, 'ForgeModernHandoff': 2,
                   'ForgeModernPaused': 1},
                  {'ForgeModernOwner': 1})
        for state in states:
            for request in range(256):
                for ccr in range(32):
                    # Sweep every interrupt mask across the full request/CCR grid.
                    mask = ccr % 8
                    _, sr, _, _ = self.prepared.call(
                        0xA5C30000 | request, 0, 0, ccr, state=state, mask=mask)
                    expected = 0x2000 | mask << 8 | ccr & 16
                    expected |= 8 if request & 128 else 4 if request == 0 else 0
                    self.assertEqual(sr, expected, (state, request, ccr))
                    self.assertTrue(all(mask == 0x700 for a, mask in self.prepared.masks
                                        if a != NativeMachine.SNAPSHOT & 0xFFFFFF))

    def test_sound_wrappers_all_bytes_ccrs_and_owners(self):
        for entry, slot in ((0x1370, 1), (0x1376, 2)):
            for owner in (0, 1):
                for request in range(256):
                    for ccr in range(32):
                        state = {'ForgeModernOwner': owner, 'ForgeModernActive': owner}
                        args = (0xABCD0000 | request, 0, 0, ccr)
                        actual = self.prepared.call(*args, entry, state=state)
                        routed = entry == 0x1370 and (0x81 <= request < 0xA0 or
                                                     request in (0xF9, 0xFB, 0xFC, 0xFD, 0xFE, 0xFF))
                        if routed:
                            expected = self.prepared.call(*args, state=state)
                            self.assertEqual(actual, expected)
                        else:
                            expected = self.stock.call(*args, entry)
                            self.assertEqual(actual[0:2], expected[0:2])
                            self.assertEqual(actual[3], expected[3])
                            if entry == 0x1376 and request == 0x98 and owner:
                                self.assertEqual(actual[0][slot], request)
                                self.assertEqual([w for w in actual[2] if w[0] == 0xFFF108],
                                                 [(0xFFF108, 1, 1)])
                            else:
                                self.assertEqual(actual, expected)
        print('PlaySound/PlaySound2: all 256 bytes x 32 CCRs x both owners, exact queue/register/CCR contracts')


class ModernBackendBinaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        modern.verify_modern(modern.MODERN_ROM_PATH)
        cls.machine = NativeMachine(modern.MODERN_ROM_PATH.read_bytes())

    def check_command(self, entry, request, command, ccr):
        queue, sr, writes, _ = self.machine.call(0xA5C30000 | request, 0x85, 0x99, ccr, entry)
        expected_sr = 0x2304 | (ccr & 0x10)
        transaction = [(0x3F7FA, 2, 0xCD54), (0x3F7FE, 2, command), (0x3F7FA, 2, 0)]
        self.assertEqual(queue, bytes([0x85, 0x42, 0x81, 0xF7, 0x99]))
        self.assertEqual(sr, expected_sr)
        self.assertEqual(writes, transaction + [(NativeMachine.SNAPSHOT & 0xFFFFFF, 2, expected_sr)])
        return transaction

    def test_dispatch_all_supported_ids_and_ccr_inputs(self):
        # Explicit independent request/track oracle; verifies compiled compares
        # and branch targets, rather than reusing the source generator's policy.
        routes = {0x82: 3, 0x8E: 5, 0x87: 7, 0x89: 8, 0x86: 9, 0x8B: 10,
                  0x84: 11, 0x85: 12, 0x8D: 13, 0x8F: 14, 0x8A: 15,
                  0x92: 29, 0x8C: 26, 0x88: 27, 0x83: 28, 0x90: 31}
        for request, track in routes.items():
            for ccr in range(32):
                with self.subTest(request=request, ccr=ccr):
                    self.check_command(modern.DISPATCH_ADDRESS, request, 0x1200 | track, ccr)
            print(f'Dispatch ${request:02X} -> track {track:02d}: CD54 -> {0x1200 | track:04X} -> 0000')

    def test_every_unsupported_byte_has_no_mdplus_or_mailbox_writes(self):
        supported = {0x82, 0x8E, 0x87, 0x89, 0x86, 0x8B, 0x84, 0x85,
                     0x8D, 0x8F, 0x8A, 0x92, 0x8C, 0x88, 0x83, 0x90}
        for request in set(range(256)) - supported:
            for ccr in range(32):
                with self.subTest(request=request, ccr=ccr):
                    queue, sr, writes, _ = self.machine.call(
                        0xDEADBE00 | request, 0x85, 0x99, ccr, modern.DISPATCH_ADDRESS)
                    self.assertEqual(queue, bytes([0x85, 0x42, 0x81, 0xF7, 0x99]))
                    self.assertEqual(sr & 0x10, ccr & 0x10)
                    self.assertEqual(writes, [(NativeMachine.SNAPSHOT & 0xFFFFFF, 2, sr)])

    def test_control_primitives_exact_traces_and_ccr(self):
        for index, command in enumerate((0x1300, 0x1328, 0x1400, 0x1519, 0x15FF)):
            entry = 0x100094 + index * 26
            for ccr in range(32):
                with self.subTest(command=command, ccr=ccr):
                    self.check_command(entry, 0xF7, command, ccr)
            print(f'Control ${entry:06X}: CD54 -> {command:04X} -> 0000')


if __name__ == '__main__':
    unittest.main()
