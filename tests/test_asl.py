from __future__ import annotations

import unittest
from unittest.mock import patch

from tools.mdplus_builder.common import BuildError
from tools.mdplus_builder.source import (
    _asl_constants_source,
    _asl_moveq_operands,
    _asl_s2_source,
    _asl_word_operands,
)


class AslCompatibilityTests(unittest.TestCase):
    def test_moveq_signed_operands_preserve_symbols_and_comments(self):
        for operand in ("MusID_Ending", "SndID_Sparkle", "$E6"):
            with self.subTest(operand=operand):
                source = f"\tmoveq\t#{operand},d0 ; keep {operand}\n"
                expected = f"\tmoveq\t#({operand}-$100),d0 ; keep {operand}\n"
                self.assertEqual(_asl_moveq_operands(source), (expected, 1))

    def test_moveq_only_converts_known_operands_and_destination(self):
        source = ("\tmoveq #$7F,d0\n"
                  "\tmoveq #MusID_Unknown,d0\n"
                  "\tmoveq #$FF,d0\n"
                  "\tmoveq #MusID_Ending+1,d0\n"
                  "\tmoveq #MusID_Ending,d1\n"
                  "\tmoveq #(MusID_Ending-$100),d0\n"
                  "; moveq #MusID_Ending,d0\n"
                  "\tmove.w (1).w,d0 ; intentional crash\n")
        self.assertEqual(_asl_moveq_operands(source), (source, 0))

    def test_unexpected_moveq_count_fails_closed(self):
        with patch("tools.mdplus_builder.source._asl_legacy_s2_source", side_effect=lambda text: text):
            for count in (0, 32, 34):
                with self.subTest(count=count), self.assertRaisesRegex(BuildError, "33 signed MOVEQ operands"):
                    _asl_s2_source("\tmoveq #MusID_Ending,d0\n" * count)

    def test_word_addresses_are_explicit_without_changing_long_addresses_or_comments(self):
        source = ("\tcmpa.w #MainCharacter,a1 ; MainCharacter\n"
                  "\tmove.l #MainCharacter,a0\n"
                  "\tmove.w (MainCharacter).w,d0\n"
                  "\tdc.w MainCharacter+x_pos, Sidekick+x_pos, $1B\n")
        converted, count = _asl_word_operands(source)
        self.assertEqual(count, 3)
        self.assertEqual(converted,
                         "\tcmpa.w #((MainCharacter)&$FFFF),a1 ; MainCharacter\n"
                         "\tmove.l #MainCharacter,a0\n"
                         "\tmove.w (MainCharacter).w,d0\n"
                         "\tdc.w ((MainCharacter+x_pos)&$FFFF), ((Sidekick+x_pos)&$FFFF), $1B\n")

    def test_ram_size_arithmetic_and_already_explicit_words_are_unchanged(self):
        source = ("\tmove.w #(Object_RAM_End-Object_RAM)/object_size-1,d7\n"
                  "\tmove.w #(Dynamic_Object_RAM_End-Dynamic_Object_RAM)/object_size-1,d0\n"
                  "\tdc.w MainCharacter&$FFFF, MainCharacter-Sidekick\n")
        self.assertEqual(_asl_word_operands(source), (source, 0))

    def test_word_offset_is_masked_after_addition(self):
        self.assertEqual(_asl_word_operands("\tdc.w Normal_palette+$10\n"),
                         ("\tdc.w ((Normal_palette+$10)&$FFFF)\n", 1))

    def test_unexpected_source_operand_count_fails_closed(self):
        with self.assertRaisesRegex(BuildError, "word-sized RAM operands"):
            _asl_s2_source("\tmove.w #MainCharacter,d0\n")

    def test_replacement_phases_are_balanced_and_ram_limit_retained(self):
        source = ("\tphase\tramaddr($FFFF0000)\nRAM_Start:\n"
                  + "\tphase\tObject_RAM\n" * 12
                  + "\tdephase\n"
                  + "if * > 0\t; Don't declare more space than the RAM can contain!\n"
                  + 'fatal "The RAM variable declarations are too large by $\\{*} bytes."\n')
        converted = _asl_constants_source(source)
        self.assertTrue(converted.startswith("\tphase\tramaddr($FFFF0000)\n"))
        self.assertEqual(converted.count("\tdephase\n"), 13)
        self.assertIn("if (*-RAM_Start) > $10000", converted)
        self.assertIn(r"$\{(*-RAM_Start)-$10000}", converted)

    def test_unexpected_phase_count_fails_closed(self):
        with self.assertRaisesRegex(BuildError, "replacement RAM phases"):
            _asl_constants_source("\tphase\tObject_RAM\n")


if __name__ == "__main__":
    unittest.main()
