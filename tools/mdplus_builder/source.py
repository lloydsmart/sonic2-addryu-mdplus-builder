from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
from pathlib import Path

from .common import ASSEMBLER_DIR, BUILD, DEPENDENCIES, ROM_PATH, SOURCE_DIR, BuildError, load_json, run, sha256
from .driver import verify_driver_load

EXPECTED_ROM_SIZE = 2_129_922
REGRESSION_SHA256 = "315c69fb84dbca2a31ceffe3face70b4138317feed53feb7e23c6a5ab009205e"
OPEN_PATTERN = bytes.fromhex("33 fc cd 54 00 03 f7 fa")
CLOSE_PATTERN = bytes.fromhex("33 fc 00 00 00 03 f7 fa")
COMMAND_ADDRESS_PATTERN = bytes.fromhex("00 03 f7 fe")
TRACK03_PATTERN = bytes.fromhex("33 fc 12 03 00 03 f7 fe")

LEGACY_CONVERSION_COUNTS = {
    "definitions": 1,
    "polls": 50,
    "seeks": 31,
    "clocks": 52,
    "seamless": 31,
    "commands": 52,
    "overlay_opens": 52,
    "overlay_closes": 52,
}

OVERLAY_OPEN_LINE = "move.w  #$CD54,(MDP_CTRL).l"
OVERLAY_CLOSE_LINE = "move.w  #0,(MDP_CTRL).l"


def _clone_at(url: str, commit: str, destination: Path, local_source: Path | None = None) -> None:
    if destination.exists():
        head = _git_output(destination, "rev-parse", "HEAD").strip()
        if head != commit:
            raise BuildError(f"{destination} is at {head}, expected {commit}; remove build/ and retry")
        return
    BUILD.mkdir(parents=True, exist_ok=True)
    clone_from = str(local_source) if local_source else url
    run(["git", "clone", "--no-checkout", clone_from, destination])
    run(["git", "checkout", "--detach", commit], cwd=destination)


def _git_output(repo: Path, *args: str) -> str:
    import subprocess

    try:
        return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise BuildError(f"Unable to inspect Git checkout {repo}") from exc


def _audit_mdplus_transactions(text: str) -> dict[str, int]:
    lines = text.splitlines()
    command_lines = [
        index
        for index, line in enumerate(lines)
        if re.match(r"^[ \t]*move\.w\b", line) and re.search(r"\bMDP_CMD\b", line)
    ]
    open_lines = [index for index, line in enumerate(lines) if line.strip() == OVERLAY_OPEN_LINE]
    close_lines = [index for index, line in enumerate(lines) if line.strip() == OVERLAY_CLOSE_LINE]

    for index in command_lines:
        if index == 0 or lines[index - 1].strip() != OVERLAY_OPEN_LINE:
            raise BuildError(f"MD+ command on source line {index + 1} is not preceded by overlay-open")
        if index + 1 >= len(lines) or lines[index + 1].strip() != OVERLAY_CLOSE_LINE:
            raise BuildError(f"MD+ command on source line {index + 1} is not followed by overlay-close")

    if set(open_lines) != {index - 1 for index in command_lines} or set(close_lines) != {
        index + 1 for index in command_lines
    }:
        raise BuildError("Orphan MD+ overlay open/close outside a command transaction")

    play_marker = "PlayMusic:\nPlayMSU:\n"
    if text.count(play_marker) != 1:
        raise BuildError("Expected exactly one PlayMSU entry point")
    if play_marker + "    " + OVERLAY_OPEN_LINE in text:
        raise BuildError("PlayMSU still contains a persistent MD+ overlay-open")

    return {
        "commands": len(command_lines),
        "overlay_opens": len(open_lines),
        "overlay_closes": len(close_lines),
    }


def _convert_msu_source(text: str) -> tuple[str, dict[str, int]]:
    text, definitions = re.subn(
        r"(?m)^MCD_STAT[^\n]*\n^MCD_CMD[^\n]*\n^MCD_ARG[^\n]*\n^MCD_SEEK[^\n]*\n^MCD_CMD_CK[^\n]*\n",
        "MDP_CTRL        = $0003F7FA\nMDP_CMD         = $0003F7FE\n",
        text,
        count=1,
    )
    text, polls = re.subn(r"(?m)^[ \t]*tst\.b[ \t]+MCD_STAT[^\n]*\n^[ \t]*bne\.s[^\n]*\n", "", text)
    text, seeks = re.subn(r"(?m)^[ \t]*move\.l[^\n]*MCD_SEEK[^\n]*\n", "", text)
    text, clocks = re.subn(r"(?m)^[ \t]*addq\.b[ \t]+#1,MCD_CMD_CK[^\n]*\n", "", text)
    text, seamless = re.subn(r"#\(\$1A00\|", "#($1200|", text)
    text, commands = re.subn(r"\bMCD_CMD\b", "MDP_CMD", text)

    command_pattern = re.compile(
        r"(?m)^(?P<indent>[ \t]*)(?P<instruction>move\.w[ \t]+(?P<command>[^,\n]+),[ \t]*)"
        r"MDP_CMD(?P<suffix>[ \t]*(?:;[^\n]*)?)$"
    )

    def transaction(match: re.Match[str]) -> str:
        indent = match.group("indent")
        command_line = (
            indent
            + match.group("instruction")
            + "(MDP_CMD).l"
            + match.group("suffix")
        )
        return "\n".join(
            (
                indent + OVERLAY_OPEN_LINE,
                command_line,
                indent + OVERLAY_CLOSE_LINE,
            )
        )

    text, transactions = command_pattern.subn(transaction, text)
    if transactions != commands:
        raise BuildError(
            "Not every converted MD+ command became a transaction: "
            f"commands={commands}, transactions={transactions}"
        )

    leftovers = sorted(set(re.findall(r"\bMCD_[A-Z_]+\b", text)))
    if leftovers:
        raise BuildError(f"Unconverted Mega-CD symbols remain: {', '.join(leftovers)}")

    actual = {
        "definitions": definitions,
        "polls": polls,
        "seeks": seeks,
        "clocks": clocks,
        "seamless": seamless,
        **_audit_mdplus_transactions(text),
    }
    for key, expected in LEGACY_CONVERSION_COUNTS.items():
        if actual[key] != expected:
            raise BuildError(
                f"Conversion count changed for {key}: got {actual[key]}, expected {expected}"
            )
    return text, actual


def bootstrap(*, local_source: Path | None = None, skip_assembler_build: bool = False) -> None:
    deps = load_json(DEPENDENCIES)
    _clone_at(deps["source"]["url"], deps["source"]["commit"], SOURCE_DIR, local_source)
    _clone_at(deps["assembler"]["url"], deps["assembler"]["commit"], ASSEMBLER_DIR)
    if not skip_assembler_build and not (ASSEMBLER_DIR / "asl").exists():
        shutil.copy2(ASSEMBLER_DIR / "Makefile.def.tmpl", ASSEMBLER_DIR / "Makefile.def")
        run(["make", f"-j{os.cpu_count() or 2}", "binaries"], cwd=ASSEMBLER_DIR)


# This is ROM policy, deliberately independent of manifest/audio/package inputs.
ADDRYU_TRACKS = (
    ("MusID_EHZ", 3), ("MusID_CPZ", 5), ("MusID_ARZ", 7), ("MusID_CNZ", 8),
    ("MusID_HTZ", 9), ("MusID_MCZ", 10), ("MusID_OOZ", 11), ("MusID_MTZ", 12),
    ("MusID_SCZ", 13), ("MusID_WFZ", 14), ("MusID_DEZ", 15), ("MusID_SpecStage", 29),
    ("MusID_EHZ_2P", 26), ("MusID_CNZ_2P", 27), ("MusID_MCZ_2P", 28), ("MusID_HPZ", 31),
)
EXPECTED_CONVERSION_COUNTS = {
    **{key: value for key, value in LEGACY_CONVERSION_COUNTS.items()
       if key not in {"commands", "overlay_opens", "overlay_closes"}},
    "commands": 21, "overlay_opens": 21, "overlay_closes": 21,
}
# Hashes are of UTF-8 source with LF newlines at the immutable dependency pin.
UPSTREAM_HASHES = {
    "s2.macros.asm": "e2d1d1088abf377a6e20b888aab3a1e6815e6aea450884854c8bb5c9a11ffef6",
    "msu-md.asm": "724b846275876b823a59f5f41cc3d38a3976a75c4cecdf8f7f682e91bc73d288",
    "s2.asm": "c8fb277c26965447f5e310bed1187c189b80671620d401a674b9a3f5619d7220",
    "s2.constants.asm": "597b9bca0b9f7f563dbda51d1f7fc1131ab07480d88a5e6d492cc5c2449d139e",
    "s2.sounddriver.asm": "7820f237ba3b4a1b3158341cbd55e5ac7b5073883de1e1c7cbf9f6dcedfa0fb9",
}


def _replace_exact(text: str, old: str, new: str, count: int = 1) -> str:
    if text.count(old) != count:
        raise BuildError(f"Expected {count} upstream matches for {old!r}, got {text.count(old)}")
    return text.replace(old, new)


def _hybrid_msu_source() -> str:
    text = Path(__file__).with_name("hybrid.asm").read_text(encoding="utf-8")
    text = _replace_exact(text, "; @ROUTE@", "\n".join(
        f"    cmp.b   #{symbol},d0\n    beq.w   HybridRequest" for symbol, _ in ADDRYU_TRACKS
    ))
    text = _replace_exact(text, "; @DISPATCH@", "\n".join(
        f"    cmp.b   #{symbol},d0\n    beq.w   MDPlusTrack{track:02d}" for symbol, track in ADDRYU_TRACKS
    ))

    def command(label: str, operand: str) -> str:
        return (f"{label}:\n    {OVERLAY_OPEN_LINE}\n"
                f"    move.w  #{operand},(MDP_CMD).l\n    {OVERLAY_CLOSE_LINE}\n    rts\n")

    text = _replace_exact(text, "; @COMMANDS@", "\n".join(
        command(label, operand) for label, operand in (
            ("MDPlusImmediate", "$1300"), ("MDPlusFade", "$1328"), ("MDPlusResume", "$1400"),
            ("MDPlusVolumeLow", "$1519"), ("MDPlusVolumeNormal", "$15FF"),
        )
    ))
    return _replace_exact(text, "; @TRACKS@", "\n".join(
        command(f"MDPlusTrack{track:02d}", f"($1200|{track})") for _, track in ADDRYU_TRACKS
    ))


def _legacy_s2_source(text: str) -> str:
    lines = text.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if "jsr" in line and "MSUMD_DRV" in line]
    if len(starts) != 1:
        raise BuildError(f"Expected one MSUMD_DRV startup call, found {len(starts)}")
    start = starts[0]
    end = next(i for i in range(start, start + 20) if "bra.s" in lines[i] and "msuOK" in lines[i])
    lines[start:end + 1] = [
        "    ; MD+ is opened later, after Sonic's startup checksum has completed\n",
        "    bra.s   msuOK\n",
    ]
    return _replace_exact("".join(lines), '        BINCLUDE  "sound\\msu-drv-loop.bin"', '        rts')


def _hybrid_s2_source(text: str) -> str:
    text = _legacy_s2_source(text)
    text = _replace_exact(text, "\tbsr.w\tJmpTo_SoundDriverLoad\n",
                          "\tbsr.w\tJmpTo_SoundDriverLoad\n\tbsr.w\tHybridReset\n")
    text = _replace_exact(text, "sndDriverInput:\n", "sndDriverInput:\n\tbsr.w\tHybridCheckReady\n")
    text = _replace_exact(text, "loc_10C0:\n", """loc_10C0:
    cmpi.b  #MusID_HybridStop,d0
    bne.s   HybridInputNormal
    clr.b   (Z80_RAM+zHybridAck).l
    move.b  #2,(v_MDPlusHandoff).l
HybridInputNormal:
""")
    # The upstream fourth copy slot aliases VoiceTblPtr, not a queue slot.
    # Leave the second music mailbox for the ready-checked path above.
    text = _replace_exact(text, "loc_10C4:\n\tmoveq\t#4-1,d1",
                          "loc_10C4:\n\tmoveq\t#3-1,d1")
    text = _replace_exact(text,
        "\t\t\t\t; FFE4 (Music_to_play_2) goes to 1B8C (zMusicToPlay),\n", "")
    # Preserve native SFX stores, but route music/control IDs that also enter here.
    text = _replace_exact(text, "PlaySound:\n", """PlaySound:
    cmp.b   #MusID__First,d0
    blo.s   HybridSoundEffect
    cmp.b   #MusID__End,d0
    blo.w   PlayMusic
    cmp.b   #MusID_FadeOut,d0
    beq.w   PlayMusic
    cmp.b   #MusID_SpeedUp,d0
    bhs.w   PlayMusic
HybridSoundEffect:
""")
    # Route all four direct pause writes (normal, slow-motion, special stage).
    for control, count in (("Pause", 1), ("Unpause", 3)):
        import_pattern = rf"(?m)^\tmove.b\t#MusID_{control},\(Music_to_play\).w[^\n]*\n"
        text, actual = re.subn(import_pattern,
            f"\tmove.b\t#MusID_{control},d0\n\tbsr.w\tPlayMusic\n", text)
        if actual != count:
            raise BuildError(f"Unexpected direct {control} writes: {actual}")
    for line in (
        "\tjsr \tmsuStop\n", "\tjsr\t\tmsuResume\n",
        "\tjsr \tmsuChangeTrackSpeed ; @todo speed up music\n",
        "\tjsr \tmsuRestoreTrackSpeed ; @todo slow down music\n",
        "\tjsr \tmsuStop\t\t; @todo fade music for return to title\n",
    ):
        text = _replace_exact(text, line, "")
    text = _replace_exact(text, "msuStop ; @todo fade out music with demo", "HybridFadeRequest", 2)
    text = _replace_exact(text, "msuStop ; @todo mute music for return to title", "HybridStopRequest")
    text = _replace_exact(text,
        "\t;move.b\t#MusID_Stop,d0\n\t;bsr.w\tPlayMusic ; stop music\n\tjsr \tmsuPlaySega",
        "\tmove.b\t#MusID_Stop,d0\n\tbsr.w\tPlayMusic ; stop music")
    text = _replace_exact(text,
        '\t;move.b\t#SndID_SegaSound,d0\n\t;bsr.w\tPlaySound\t; play "SEGA" sound',
        '\tmove.b\t#SndID_SegaSound,d0\n\tbsr.w\tPlaySound\t; play "SEGA" sound')
    text = _replace_exact(text, "\t;jsr \tmsuPlaySega ; @todo play sega early\n", "")
    # The default compressor emits no trailing sentinel. The stock loader
    # discards its last byte (potentially an entire match, including ACK/RET).
    # Consume every byte; exit on the NEXT request, without reading past input.
    text = _replace_exact(text, """SaxDec_GetByte:
\tmove.b\t(a6)+,d0
\tsubq.w\t#1,d7\t; Decrement remaining number of bytes
\tbne.s\t+
\taddq.w\t#4,sp\t; Exit the decompressor by meddling with the stack
+
\trts""", """SaxDec_GetByte:
    subq.w  #1,d7
    bcs.s   + ; no bytes remain: return directly to the loader's caller
    move.b  (a6)+,d0
    rts
+
    addq.w  #4,sp
    rts""")
    return text


def _hybrid_z80_source(text: str) -> str:
    text = _replace_exact(text, "\tcp\tMusID__End\t\t\t; is it music (less than index 20)?",
                          "    cp MusID_HybridStop\n    jp z,zHybridStopMusic\n"
                          "\tcp\tMusID__End\t\t\t; is it music (less than index 20)?")
    # A queued handoff can terminate a paused native song too.
    text = _replace_exact(text, "\tld\ta,(zAbsVar.StopMusic)\t; Get pause/unpause flag", """    ld a,(zAbsVar.QueueToPlay)
    cp MusID_HybridStop
    call z,zPlaySoundByIndex
\tld\ta,(zAbsVar.StopMusic)\t; Get pause/unpause flag""")
    text = _replace_exact(text, "zTracksSaveEnd:\n", """zTracksSaveEnd:
zHybridAck: ds.b 1 ; outside stock track memory, including the 1-up backup
    if zHybridAck<>$1FF4
        fatal "Hybrid ACK RAM layout changed"
    endif
""")
    extension = Path(__file__).with_name("hybrid_z80.asm").read_text(encoding="utf-8")
    return _replace_exact(text, "; end of Z80 'ROM'", extension + "\n; end of Z80 'ROM'")

def _asl_constants_source(text: str) -> str:
    # Current ASL nests PHASE; the old source used it to replace the last phase.
    text, count = re.subn(r"(?m)^\tphase\t(?!ramaddr\(\$FFFF0000\))", "\tdephase\n\tphase\t", text)
    if count != 12:
        raise BuildError(f"Expected 12 replacement RAM phases, got {count}")
    text = _replace_exact(text, "if * > 0\t; Don't declare more space than the RAM can contain!",
                          "if (*-RAM_Start) > $10000\t; Don't declare more space than the RAM can contain!")
    return _replace_exact(text, r"large by $\{*} bytes.", r"large by $\{(*-RAM_Start)-$10000} bytes.")


# Only these upstream RAM addresses are intentionally stored/compared as words.
RAM_WORD_SYMBOLS = (
    'CNZ_Visible_bumpers_start',
    'CNZ_Visible_bumpers_start_P2',
    'Camera_BG2_copy',
    'Camera_BG3_copy',
    'Camera_BG_copy',
    'Camera_Min_X_pos',
    'Camera_P2_copy',
    'Camera_RAM_copy',
    'Camera_X_pos',
    'Camera_X_pos_P2',
    'Camera_X_pos_coarse',
    'Camera_X_pos_coarse_P2',
    'Camera_X_pos_diff',
    'Camera_X_pos_diff_P2',
    'Camera_X_pos_last',
    'Camera_X_pos_last_P2',
    'Camera_Y_pos_bias',
    'Camera_Y_pos_bias_P2',
    'Ctrl_1_Held',
    'Ctrl_2_Held',
    'Dynamic_Object_RAM_End',
    'Horiz_block_crossed_flag',
    'Horiz_block_crossed_flag_P2',
    'Horiz_scroll_delay_val',
    'Horiz_scroll_delay_val_P2',
    'MainCharacter',
    'Normal_palette',
    'Obj_load_addr_2',
    'Obj_load_addr_right',
    'Obj_respawn_index',
    'Obj_respawn_index_P2',
    'Object_RAM',
    'Ring_start_addr',
    'Ring_start_addr_P2',
    'SS_Dynamic_Object_RAM_End',
    'Scroll_flags',
    'Scroll_flags_P2',
    'Scroll_flags_copy',
    'Scroll_flags_copy_P2',
    'Sidekick',
    'Sonic_Dust',
    'Sonic_Pos_Record_Buf',
    'Sonic_top_speed',
    'Tails_Min_X_pos',
    'Tails_Pos_Record_Buf',
    'Tails_top_speed',
    'TitleCard_ZoneName',
    'VDP_Command_Buffer_Slot',
)


def _asl_word_operands(text: str) -> tuple[str, int]:
    pattern = re.compile(r"^(\s*)((?:" + "|".join(RAM_WORD_SYMBOLS) + r")(?:\+(?:x_pos|\$10))?)(\s*)$")
    count = 0
    lines = []
    for line in text.splitlines(keepends=True):
        code, separator, comment = line.partition(";")
        if re.search(r"\b(?:dc|cmpa|move|subi)\.w\s", code):
            # Explicit low words preserve legacy 32-bit signed truncation.
            # Restrict instruction changes to immediate operands; DC has none.
            match = re.search(r"\bdc\.w\s+(.+)|#([^,]+)", code)
            if match:
                start, end = match.span(1 if match[1] is not None else 2)
                operands = code[start:end].split(",")
                hits = 0
                for index, operand in enumerate(operands):
                    operands[index], hit = pattern.subn(r"\1((\2)&$FFFF)\3", operand)
                    hits += hit
                operand = ",".join(operands)
                code = code[:start] + operand + code[end:]
                count += hits
        lines.append(code + separator + comment)
    return "".join(lines), count


# Audited high-byte MOVEQ operands in the pinned s2.asm, all targeting d0.
# Keep symbols so their meaning remains visible in the prepared source.
MOVEQ_SIGNED_OPERANDS = (
    "MusID_Ending", "MusID_Credits", "MusID_Title", "MusID_FadeOut",
    "MusID_Boss", "MusID_WFZ", "MusID_EndBoss",
    "SndID_Sparkle", "SndID_Blip", "SndID_Fire", "SndID_MechaSonicBuzz",
    "SndID_SpindashRelease", "SndID_LaserBeam", "SndID_SpikeSwitch",
    "SndID_Scatter", "SndID_Helicopter", "SndID_LargeLaser", "SndID_Rumbling",
    "SndID_Smash", "SndID_Rumbling2", "SndID_Beep", "$E6",
)


def _asl_moveq_operands(text: str) -> tuple[str, int]:
    pattern = re.compile(
        r"(?m)^([ \t]*moveq[ \t]+#)("
        + "|".join(re.escape(operand) for operand in MOVEQ_SIGNED_OPERANDS)
        + r")(?=,d0[ \t]*(?:;[^\n]*)?$)"
    )
    return pattern.subn(r"\1(\2-$100)", text)


def _asl_s2_source(text: str) -> str:
    text = _asl_legacy_s2_source(text)
    text, count = _asl_moveq_operands(text)
    if count != 33:
        raise BuildError(f"Expected 33 signed MOVEQ operands, got {count}")
    return text


def _asl_legacy_s2_source(text: str) -> str:
    text, count = _asl_word_operands(text)
    if count != 85:
        raise BuildError(f"Expected 85 word-sized RAM operands, got {count}")
    text, count = re.subn(r"(?<!\+)(\+{1,2})\(pc,d2\.w\)", r"(\1)(pc,d2.w)", text)
    if count != 5:
        raise BuildError(f"Expected 5 anonymous indexed labels, got {count}")
    return text


def apply_mdplus(source_dir: Path = SOURCE_DIR) -> dict[str, int]:
    if not (source_dir / ".git").exists():
        raise BuildError(f"Not a Git source checkout: {source_dir}")
    pin = load_json(DEPENDENCIES)["source"]["commit"]
    if _git_output(source_dir, "rev-parse", "HEAD") != pin:
        raise BuildError("Source checkout is not at the pinned commit")
    import subprocess

    originals = {}
    for name, expected in UPSTREAM_HASHES.items():
        original = subprocess.check_output(
            ["git", "show", f"HEAD:{name}"], cwd=source_dir, text=True
        )
        if hashlib.sha256(original.encode()).hexdigest() != expected:
            raise BuildError(f"Pinned upstream source structure changed: {name}")
        originals[name] = original
    legacy_msu, legacy_counts = _convert_msu_source(originals["msu-md.asm"])
    outputs = {
        "msu-md.asm": _hybrid_msu_source(),
        "s2.asm": _asl_s2_source(_hybrid_s2_source(originals["s2.asm"])),
        "s2.constants.asm": _asl_constants_source(originals["s2.constants.asm"]),
        "s2.macros.asm": _replace_exact(originals["s2.macros.asm"],
                                        "dc.ATTRIBUTE ptr-current_offset_table",
                                        "dc.ATTRIBUTE (ptr)-current_offset_table"),
        "s2.sounddriver.asm": _hybrid_z80_source(originals["s2.sounddriver.asm"]),
    }
    counts = {**legacy_counts, **_audit_mdplus_transactions(outputs["msu-md.asm"])}
    if counts != EXPECTED_CONVERSION_COUNTS:
        raise BuildError(f"Unexpected hybrid transformation counts: {counts}")
    allowed = {*outputs, "build.sh"}
    status = _git_output(source_dir, "status", "--porcelain")
    if any(line.strip()[2:] not in allowed for line in status.splitlines()):
        raise BuildError(f"Source checkout has unexpected changes: {source_dir}\n{status}")
    # Validate every input before writing anything. Recognise the exact previous
    # production conversion for upgrades; arbitrary prepared edits are rejected.
    for name in UPSTREAM_HASHES:
        current = (source_dir / name).read_text(encoding="utf-8")
        accepted = {originals[name], outputs.get(name, originals[name])}
        if name == "msu-md.asm":
            accepted.add(legacy_msu)
        if name == "s2.asm":
            accepted.add(_legacy_s2_source(originals[name]))
            accepted.add(_hybrid_s2_source(originals[name]))
            accepted.add(_asl_legacy_s2_source(_hybrid_s2_source(originals[name])))
        if current not in accepted:
            raise BuildError(f"Source checkout has unexpected content: {name}")
    script = source_dir / "build.sh"
    original_script = subprocess.check_output(["git", "show", "HEAD:build.sh"], cwd=source_dir, text=True)
    if script.read_text() != original_script:
        raise BuildError("Source checkout has unexpected build.sh content")
    for name, output in outputs.items():
        (source_dir / name).write_text(output, encoding="utf-8", newline="\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return counts


def genesis_checksum(data: bytes) -> tuple[int, int]:
    if len(data) < 0x200:
        raise BuildError("File is too small to be a Mega Drive ROM")
    stored = int.from_bytes(data[0x18E:0x190], "big")
    calculated = 0
    for offset in range(0x200, len(data), 2):
        calculated = (calculated + int.from_bytes(data[offset : offset + 2].ljust(2, b"\0"), "big")) & 0xFFFF
    return stored, calculated


def verify_rom(path: Path, *, strict_regression: bool = False) -> dict[str, str | int]:
    data = path.read_bytes()
    stored, calculated = genesis_checksum(data)
    if stored != calculated:
        raise BuildError(f"Mega Drive checksum mismatch: stored {stored:04X}, calculated {calculated:04X}")
    open_hits = data.count(OPEN_PATTERN)
    command_hits = data.count(COMMAND_ADDRESS_PATTERN)
    close_hits = data.count(CLOSE_PATTERN)
    track_hits = data.count(TRACK03_PATTERN)
    if (open_hits != EXPECTED_CONVERSION_COUNTS["commands"]
            or command_hits != open_hits or close_hits != open_hits or track_hits != 1):
        raise BuildError(
            "MD+ signature check failed: "
            f"open={open_hits}, command={command_hits}, close={close_hits}, track03={track_hits}"
        )
    for match in re.finditer(re.escape(COMMAND_ADDRESS_PATTERN), data):
        start = match.start() - 4
        if (data[start - 8:start] != OPEN_PATTERN
                or data[start:start + 2] != bytes.fromhex("33 fc")
                or data[start + 8:start + 16] != CLOSE_PATTERN):
            raise BuildError(f"Non-consecutive MD+ transaction at ROM offset {start:#x}")
    digest = sha256(path)
    if strict_regression and (len(data) != EXPECTED_ROM_SIZE or digest != REGRESSION_SHA256):
        raise BuildError(
            "Built ROM differs from the audited regression target: "
            f"size={len(data)}, sha256={digest}"
        )
    return {
        "size": len(data),
        "sha256": digest,
        "header_checksum": f"{stored:04X}",
        "overlay_open_signatures": open_hits,
        "command_signatures": command_hits,
        "overlay_close_signatures": close_hits,
        "track03_signatures": track_hits,
    }


def build_rom(source_dir: Path = SOURCE_DIR, output: Path = ROM_PATH) -> dict[str, str | int]:
    asl = ASSEMBLER_DIR / "asl"
    if not asl.exists():
        raise BuildError("Assembler is not built; run bootstrap first")
    env = os.environ.copy()
    env["PATH"] = str(ASSEMBLER_DIR) + os.pathsep + env.get("PATH", "")
    run(["./build.sh", "-r1", "-ds"], cwd=source_dir, env=env)
    built = source_dir / "s2built.bin"
    if not built.exists():
        raise BuildError("Source build did not produce s2built.bin")
    driver = verify_driver_load(source_dir, built.read_bytes())
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(built, output)
    return {**verify_rom(output, strict_regression=True), **driver}
