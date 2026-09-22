from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.mdplus_builder.common import BuildError
from tools.mdplus_builder.driver import LOADER_READ, assembled_driver, saxman_decode, verify_driver_load


def object_file(driver):
    return b'\x89\x14\x51' + bytes(4) + len(driver).to_bytes(2, 'little') + driver + b'\x00'


class DriverLoaderTests(unittest.TestCase):
    def test_final_literal_is_processed(self):
        self.assertEqual(saxman_decode(b'\x01\xc9'), b'\xc9')
        self.assertEqual(saxman_decode(b'\x01\xc9', stock_loader=True), b'')

    def test_final_backreference_can_drop_the_entire_ack_and_return(self):
        # Synthetic code, no game data: four literals, then a four-byte match.
        code = bytes.fromhex('32881bc9')
        packed = b'\x0f' + code + bytes.fromhex('eef1')
        self.assertEqual(saxman_decode(packed), code * 2)
        self.assertEqual(saxman_decode(packed, stock_loader=True), code)

    def test_zero_fill_does_not_become_a_reference_when_it_crosses_zero(self):
        self.assertEqual(saxman_decode(bytes.fromhex('0141edf0')), b'A' + bytes(3))

    def test_build_audit_rejects_old_loader_and_missing_driver_bytes(self):
        driver = bytes.fromhex('01020304050607c9')
        packed = b'\xff' + driver
        rom = bytearray(32) + packed
        rom[4:8] = bytes.fromhex('4dfa001a')
        rom[8:12] = bytes.fromhex('3e3c') + len(packed).to_bytes(2, 'big')
        rom[12:24] = LOADER_READ
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 's2.h').write_text('#define movewZ80CompSize 0x8\n')
            (root / 's2.p').write_bytes(object_file(driver))
            self.assertEqual(verify_driver_load(root, rom)['z80_loaded_bytes'], len(driver))
            rom[12] = 0
            with self.assertRaisesRegex(BuildError, 'final compressed byte'):
                verify_driver_load(root, rom)
            rom[12:24] = LOADER_READ
            rom[10:12] = (len(packed) - 1).to_bytes(2, 'big')
            with self.assertRaisesRegex(BuildError, 'differs from assembly'):
                verify_driver_load(root, rom)

    def test_object_reader_ignores_embedded_startup_stub_and_rejects_truncation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic.p'
            stub = b'\x51' + (0x200).to_bytes(4, 'little') + b'\x01\x00\xc9'
            path.write_bytes(b'\x89\x14' + stub + object_file(b'\xc9')[2:])
            self.assertEqual(assembled_driver(path), b'\xc9')
            path.write_bytes(object_file(b'\xc9')[:-2])
            with self.assertRaisesRegex(BuildError, 'Truncated'):
                assembled_driver(path)


if __name__ == '__main__':
    unittest.main()
