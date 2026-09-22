from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.mdplus_builder.source import (
    CLOSE_PATTERN,
    COMMAND_ADDRESS_PATTERN,
    EXPECTED_CONVERSION_COUNTS,
    OPEN_PATTERN,
    OVERLAY_CLOSE_LINE,
    OVERLAY_OPEN_LINE,
    TRACK03_PATTERN,
    _convert_msu_source,
    genesis_checksum,
    verify_rom,
)


def _msu_source_fixture() -> str:
    lines = [
        "MCD_STAT = $A12020\n",
        "MCD_CMD = $A12010\n",
        "MCD_ARG = $A12011\n",
        "MCD_SEEK = $A12012\n",
        "MCD_CMD_CK = $A1201F\n",
        "\n",
        "PlayMusic:\n",
        "PlayMSU:\n",
        "    jsr     findAndPlayTrack\n",
        "    rts\n",
    ]
    for index in range(52):
        track = index + 1
        lines.append(f"track_{track}:\n")
        if index < 50:
            lines.extend(("    tst.b   MCD_STAT\n", f"    bne.s   track_{track}\n"))
        command = "$1A00" if index < 31 else "$1100"
        lines.append(
            f"    move.w  #({command}|{track}),MCD_CMD"
            f"    ; command expression {track}\n"
        )
        if index < 31:
            lines.append(f"    move.l  #({track}),MCD_SEEK\n")
        lines.extend(("    addq.b  #1,MCD_CMD_CK\n", "    rts\n"))
    return "".join(lines)


class SourceConversionTests(unittest.TestCase):
    def test_every_command_is_a_self_contained_overlay_transaction(self) -> None:
        converted, counts = _convert_msu_source(_msu_source_fixture())

        self.assertEqual(counts, EXPECTED_CONVERSION_COUNTS)
        self.assertNotIn("MCD_", converted)
        self.assertNotIn(
            "PlayMusic:\nPlayMSU:\n    " + OVERLAY_OPEN_LINE,
            converted,
        )

        lines = converted.splitlines()
        commands = [
            index
            for index, line in enumerate(lines)
            if "move.w" in line and "MDP_CMD" in line
        ]
        self.assertEqual(len(commands), 52)
        self.assertEqual(sum(line.strip() == OVERLAY_OPEN_LINE for line in lines), 52)
        self.assertEqual(sum(line.strip() == OVERLAY_CLOSE_LINE for line in lines), 52)
        for index in commands:
            self.assertEqual(lines[index - 1].strip(), OVERLAY_OPEN_LINE)
            self.assertEqual(lines[index + 1].strip(), OVERLAY_CLOSE_LINE)

        self.assertIn(
            "move.w  #($1200|1),(MDP_CMD).l    ; command expression 1",
            converted,
        )
        self.assertIn(
            "move.w  #($1100|52),(MDP_CMD).l    ; command expression 52",
            converted,
        )

    def test_rom_verification_counts_all_transaction_signatures(self) -> None:
        data = bytearray(0x200)
        for index in range(52):
            data.extend(OPEN_PATTERN)
            data.extend(TRACK03_PATTERN if index == 2 else b"\x33\xfc\x11\x01" + COMMAND_ADDRESS_PATTERN)
            data.extend(CLOSE_PATTERN)
        checksum = genesis_checksum(bytes(data))[1]
        data[0x18E:0x190] = checksum.to_bytes(2, "big")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.md"
            path.write_bytes(data)
            result = verify_rom(path)

        self.assertEqual(result["overlay_open_signatures"], 52)
        self.assertEqual(result["command_signatures"], 52)
        self.assertEqual(result["overlay_close_signatures"], 52)
        self.assertEqual(result["track03_signatures"], 1)


if __name__ == "__main__":
    unittest.main()
