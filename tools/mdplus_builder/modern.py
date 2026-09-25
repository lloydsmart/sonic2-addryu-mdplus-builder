from __future__ import annotations

import hashlib
import re
import shutil
import tempfile
from pathlib import Path

from .common import BUILD, DEPENDENCIES, BuildError, load_json, require_program, run
from .source import ADDRYU_TRACKS, _clone_at, _git_output

SOURCE_MODERN_DIR = BUILD / "source-modern"
STOCK_MODERN_ROM_PATH = BUILD / "sonic2-stock-modern.md"
STOCK_MODERN_LISTING_PATH = BUILD / "sonic2-stock-modern.lst"
STOCK_ROM_SIZE = 1_048_576
STOCK_ROM_MD5 = "9feeb724052c39982d432a7851c98d3e"
STOCK_ROM_SHA256 = "193bc4064ce0daf27ea9e908ed246d87ec576cc294833badebb590b6ad8e8f6b"


def bootstrap_modern(*, local_source: Path | None = None) -> None:
    dependency = load_json(DEPENDENCIES)["source_modern"]
    _clone_at(dependency["url"], dependency["commit"], SOURCE_MODERN_DIR, local_source)


def verify_stock_modern(path: Path) -> dict[str, str | int]:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise BuildError(f"Cannot read stock ROM {path}: {exc}") from exc
    size = len(data)
    md5 = hashlib.md5(data, usedforsecurity=False).hexdigest()
    sha256 = hashlib.sha256(data).hexdigest()
    if (size, md5, sha256) != (STOCK_ROM_SIZE, STOCK_ROM_MD5, STOCK_ROM_SHA256):
        raise BuildError(
            "Modern stock ROM differs from the audited REV01 target: "
            f"size={size}, md5={md5}, sha256={sha256}"
        )
    return {"size": size, "md5": md5, "sha256": sha256}


def build_stock_modern() -> dict[str, str | int]:
    lua = require_program("lua")
    run([lua, "-e", 'local major, minor = _VERSION:match("(%d+)%.(%d+)"); '
         'assert(tonumber(major) > 5 or (tonumber(major) == 5 and tonumber(minor) >= 3), '
         '"Modern stock build requires Lua 5.3 or newer")'])
    if not SOURCE_MODERN_DIR.is_dir():
        raise BuildError("Modern source is not fetched; run bootstrap-modern first")
    dependency = load_json(DEPENDENCIES)["source_modern"]
    head = _git_output(SOURCE_MODERN_DIR, "rev-parse", "HEAD")
    if head != dependency["commit"]:
        raise BuildError(f"{SOURCE_MODERN_DIR} is at {head}, expected {dependency['commit']}")

    # Clone only committed files: local edits and stale generated ROMs cannot
    # affect the build, and upstream's generated files stay out of the input.
    with tempfile.TemporaryDirectory(prefix="stock-modern-", dir=BUILD) as directory:
        work = Path(directory) / "source"
        _clone_at(dependency["url"], dependency["commit"], work, SOURCE_MODERN_DIR)
        run([lua, "build.lua"], cwd=work)
        built = work / "s2built.bin"
        result = verify_stock_modern(built)
        shutil.copy2(built, STOCK_MODERN_ROM_PATH)
        shutil.copy2(work / "s2.lst", STOCK_MODERN_LISTING_PATH)
    return result


# Stage 2 is audited independently of the untouched stock build above.
AUDITED_MODERN_COMMIT = "380f37a731bfc720bb0371a35a593184a7ec5e43"
UPSTREAM_S2_SHA256 = "448630bb22c08b5281d143438296e5b9045f6539699ec3724147a7f945c938b9"
PREPARED_MODERN_DIR = BUILD / "prepared-modern"
MODERN_ROM_PATH = BUILD / "sonic2-modern-scaffold.md"
PLAY_MUSIC_ADDRESS = 0x135E
IMPLEMENTATION_ADDRESS = 0x100000
PREPARED_ROM_SIZE = 0x200000
NATIVE_PLAY_MUSIC = bytes.fromhex("4a38ffe0660611c0ffe04e7511c0ffe44e75")
HOOK_BYTES = bytes.fromhex("4ef9") + IMPLEMENTATION_ADDRESS.to_bytes(4, "big") + bytes.fromhex("4e71") * 6
NATIVE_SOURCE = """PlayMusic:
\ttst.b\t(Sound_Queue.Music0).w
\tbne.s\t+
\tmove.b\td0,(Sound_Queue.Music0).w
\trts
+
\tmove.b\td0,(Sound_Queue.Music1).w
\trts
; End of function PlayMusic
"""
HOOK_SOURCE = """PlayMusic:
\tjmp\t(ForgeModernPlayMusic).l
; Keep the original 18-byte footprint; these six NOPs are unreachable.
\tnop
\tnop
\tnop
\tnop
\tnop
\tnop
    if (PlayMusic<>$135E)||(*-PlayMusic<>18)
\tfatal "Unexpected Stage 2 PlayMusic hook layout"
    endif
; End of function PlayMusic
"""
TAIL_SOURCE = "\tfinishBank\n\n; end of 'ROM'\n"
TAIL_REPLACEMENT = '\tfinishBank\n\n\tinclude "hybrid_modern.asm"\n\n; end of \'ROM\'\n'


# Audited upstream ID values, not a second routing policy. The assembler uses
# upstream symbols; the independent byte audit detects any numeric ID drift.
MODERN_MUSIC_IDS = dict(zip((
    "MusID_EHZ", "MusID_MCZ_2P", "MusID_OOZ", "MusID_MTZ", "MusID_HTZ",
    "MusID_ARZ", "MusID_CNZ_2P", "MusID_CNZ", "MusID_DEZ", "MusID_MCZ",
    "MusID_EHZ_2P", "MusID_SCZ", "MusID_CPZ", "MusID_WFZ", "MusID_HPZ",
), range(0x82, 0x91), strict=True)) | {"MusID_SpecStage": 0x92}
CONTROL_COMMANDS = (
    ("ForgeModernImmediate", 0x1300), ("ForgeModernFade", 0x1328),
    ("ForgeModernResume", 0x1400), ("ForgeModernVolumeLow", 0x1519),
    ("ForgeModernVolumeNormal", 0x15FF),
)
DISPATCH_ADDRESS = IMPLEMENTATION_ADDRESS + len(NATIVE_PLAY_MUSIC)
PRIMITIVES_ADDRESS = DISPATCH_ADDRESS + 16 * 8 + 2
COMMANDS = CONTROL_COMMANDS + tuple(
    (f"ForgeModernTrack{track:02d}", 0x1200 | track) for _, track in ADDRYU_TRACKS
)
PRIMITIVE_ADDRESSES = {label: PRIMITIVES_ADDRESS + i * 26 for i, (label, _) in enumerate(COMMANDS)}
IMPLEMENTATION_END = PRIMITIVES_ADDRESS + 21 * 26
OVERLAY_OPEN = bytes.fromhex("33fccd540003f7fa")
OVERLAY_CLOSE = bytes.fromhex("33fc00000003f7fa")


def expected_modern_extension() -> bytes:
    """Independent instruction encoding audit: every byte and branch target."""
    code = bytearray(NATIVE_PLAY_MUSIC)
    for symbol, track in ADDRYU_TRACKS:
        # Upstream encodes CMP.B immediate EA, not the CMPI alias.
        code.extend(bytes.fromhex("b03c") + MODERN_MUSIC_IDS[symbol].to_bytes(2, "big"))
        displacement = PRIMITIVE_ADDRESSES[f"ForgeModernTrack{track:02d}"] - (
            IMPLEMENTATION_ADDRESS + len(code) + 2
        )
        code.extend(bytes.fromhex("6700") + displacement.to_bytes(2, "big", signed=True))
    code.extend(bytes.fromhex("4e75"))
    for _, command in COMMANDS:
        code.extend(OVERLAY_OPEN + bytes.fromhex("33fc") + command.to_bytes(2, "big")
                    + bytes.fromhex("0003f7fe") + OVERLAY_CLOSE + bytes.fromhex("4e75"))
    return bytes(code)


def _modern_extension_source() -> str:
    text = Path(__file__).with_name("hybrid_modern.asm").read_text(encoding="utf-8")
    dispatch = "\n".join(
        f"    cmp.b   #{symbol},d0\n    beq.w   ForgeModernTrack{track:02d}"
        for symbol, track in ADDRYU_TRACKS
    )
    commands = "\n".join(
        f'{label}:\n    if {label}<>${PRIMITIVE_ADDRESSES[label]:06X}\n'
        f'        fatal "Unexpected {label} boundary"\n    endif\n'
        f"    move.w  #$CD54,(MDP_CTRL).l\n"
        f"    move.w  #${command:04X},(MDP_CMD).l\n"
        f"    move.w  #0,(MDP_CTRL).l\n    rts\n"
        for label, command in COMMANDS
    )
    for marker, replacement in (("; @DISPATCH@", dispatch), ("; @COMMANDS@", commands)):
        if text.count(marker) != 1:
            raise BuildError(f"Expected exactly one modern include marker: {marker}")
        text = text.replace(marker, replacement)
    return text


# Every mutated upstream input is locked to the same audited modern commit.
UPSTREAM_Z80_SHA256 = "ff34692c633f96d50073c24f6ebb72df5c739892c31be6b19b2ae604e76232c7"
UPSTREAM_CONSTANTS_SHA256 = "8de5f4a4e6abc56ea2504afe2f4d58cc8a7a3bfa80e3f3c9f1372231a3ca16cd"
INPUT_START = "sndDriverInput:\n"
INPUT_END = "; End of function sndDriverInput\n"
INPUT_HOOK = """sndDriverInput:
    jmp (ForgeModernInput).l
    ds.b $10E0-*
    if (sndDriverInput<>$1084)||(*<>$10E0)
        fatal "Unexpected sndDriverInput footprint"
    endif
; End of function sndDriverInput
"""
LOADER_SOURCE = """SaxDec_GetByte:
\tmove.b\t(a6)+,d0
\tsubq.w\t#1,d7\t; Decrement remaining number of bytes
\tbne.s\t+
\taddq.w\t#4,sp\t; Exit the decompressor by meddling with the stack
+
\trts"""
LOADER_HOOK = """SaxDec_GetByte:
    jmp (ForgeModernSaxGetByte).l
    nop
    nop
    if (SaxDec_GetByte<>$EC0DE)||(*<>$EC0E8)
        fatal "Unexpected Saxman helper footprint"
    endif"""
RAM_HOLE = "\t\t\t\tds.b\t$500\t; $FFFFF100-$FFFFF5FF ; unused, leftover from the Sonic 1 sound driver (and used by it when you port it to Sonic 2)"
RAM_HANDOFF = """    ds.b $13
ForgeModernHandoff: ds.b 1 ; requested=1, delivered/awaiting ACK=2, idle=0
    ds.b $4EC ; preserve the entire unused $F100-$F5FF footprint"""
Z80_READY = "\tld\t(ix+zVar.QueueToPlay),80h\t; Rewrite zComRange+8 flag so we know nothing new is coming in\n"
Z80_PAUSE = "\tld\ta,(zAbsVar.StopMusic)\t; Get pause/unpause flag"


def _replace_modern(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise BuildError(f"Expected exactly one modern source pattern: {old!r}")
    return text.replace(old, new)


def _prepare_modern_source(data: bytes, filename: str = "s2.asm") -> bytes:
    hashes = {"s2.asm": UPSTREAM_S2_SHA256, "s2.sounddriver.asm": UPSTREAM_Z80_SHA256,
              "s2.constants.asm": UPSTREAM_CONSTANTS_SHA256}
    if filename not in hashes or hashlib.sha256(data).hexdigest() != hashes[filename]:
        raise BuildError(f"Pinned modern {filename} source structure changed")
    text = data.decode("utf-8")
    if filename == "s2.asm":
        for marker in (INPUT_START, INPUT_END):
            if text.count(marker) != 1:
                raise BuildError(f"Expected exactly one modern source pattern: {marker!r}")
        start = text.index(INPUT_START)
        end = text.index(INPUT_END, start) + len(INPUT_END)
        replacements = ((NATIVE_SOURCE, HOOK_SOURCE), (TAIL_SOURCE, TAIL_REPLACEMENT),
                        (text[start:end], INPUT_HOOK), (LOADER_SOURCE, LOADER_HOOK))
    elif filename == "s2.constants.asm":
        replacements = ((RAM_HOLE, RAM_HANDOFF),)
    else:
        replacements = (
            (Z80_READY, Z80_READY + "    cp MusID_ForgeStop\n    jp z,zHybridStopMusic\n"),
            (Z80_PAUSE, "    ld a,(zAbsVar.QueueToPlay)\n    cp MusID_ForgeStop\n"
             "    call z,zPlaySoundByIndex\n" + Z80_PAUSE),
            ("zTracksSaveEnd:\n", "zTracksSaveEnd:\nzHybridAck: ds.b 1\n"),
            # The added dispatch crosses the volume table's page boundary.
            # Make its existing two-byte automatic alignment explicit, so
            # upstream's warning-as-failure build still completes normally.
            ("\tensure1byteoffset 8\nzVolTLMaskTbl:",
             "    align 100h\n\tensure1byteoffset 8\nzVolTLMaskTbl:"),
            ("; end of Z80 'ROM'", '    include "hybrid_modern_z80.asm"\n\n; end of Z80 \'ROM\''),
        )
    for old, new in replacements:
        text = _replace_modern(text, old, new)
    return text.encode("utf-8")


def prepare_modern() -> dict[str, str]:
    """Recreate generated preparation from committed inputs, never from old output."""
    dependency = load_json(DEPENDENCIES)["source_modern"]
    if dependency["commit"] != AUDITED_MODERN_COMMIT:
        raise BuildError("Modern adapter requires the audited pinned commit")
    if not SOURCE_MODERN_DIR.is_dir():
        raise BuildError("Modern source is not fetched; run bootstrap-modern first")
    head = _git_output(SOURCE_MODERN_DIR, "rev-parse", "HEAD")
    if head != dependency["commit"]:
        raise BuildError(f"{SOURCE_MODERN_DIR} is at {head}, expected {dependency['commit']}")
    with tempfile.TemporaryDirectory(prefix="prepare-modern-", dir=BUILD) as directory:
        work = Path(directory) / "source"
        _clone_at(dependency["url"], dependency["commit"], work, SOURCE_MODERN_DIR)
        for filename in ("s2.asm", "s2.sounddriver.asm", "s2.constants.asm"):
            path = work / filename
            path.write_bytes(_prepare_modern_source(path.read_bytes(), filename))
        for filename in ("hybrid_modern.asm", "hybrid_modern_handoff.asm",
                         "hybrid_modern_z80.asm", "modern_build.lua"):
            if (work / filename).exists():
                raise BuildError("Modern source already contains Forge's include filename")
            content = (_modern_extension_source() if filename == "hybrid_modern.asm" else
                       Path(__file__).with_name(filename).read_text(encoding="utf-8"))
            (work / filename).write_text(content, encoding="utf-8")
        # Only this generated output is replaced; dependency checkouts are inputs.
        if PREPARED_MODERN_DIR.exists():
            shutil.rmtree(PREPARED_MODERN_DIR)
        work.rename(PREPARED_MODERN_DIR)
    return {"source_commit": head, "prepared_source": str(PREPARED_MODERN_DIR)}


HANDOFF_ADDRESSES = {
    "ForgeModernBeginHandoff": 0x1002B6, "ForgeModernQueueStop": 0x1002BC,
    "ForgeModernCheckReady": 0x1002E8, "ForgeModernInput": 0x10032A,
    "ForgeModernSaxGetByte": 0x10039C, "ForgeModernHandoffEnd": 0x1003A8,
}
HANDOFF_END = HANDOFF_ADDRESSES["ForgeModernHandoffEnd"]
HANDOFF_SHA256 = "40082c3869f23691ccc6a631f794e44652f5c7c6f793b7fe3566de2b0d481759"
DRIVER_START = 0xEC0E8
DRIVER_LIMIT = 0xED100  # fixed DAC start; includes upstream's explicit growth padding
DRIVER_LENGTH_ADDRESS = 0xEC050
Z80_COMPRESSED_SIZE = 4009
Z80_LOADED_SIZE = 0x137A
Z80_SHA256 = "9f997cc7217dda878297f7359f3314c7876aeb29e8705d63bd4b6db1513db24f"
DRIVER_REGION_SHA256 = "d2288f0c731bcefd085782fe372e6d08cac815e127d35a01d885ea5866624812"
STOCK_MASKED_SHA256 = "3bf58d2d8a65599a52e13a7f92518e444c918d1b2edf8b5e7c9ab71fa715a268"
# Exact new-region checks accompany the digest of every unchanged stock byte.
# The whole audited REV01 baseline, with ONLY these regions zeroed, defines it.
STOCK_CHANGED_REGIONS = ((0x1084, 0x10E0), (DRIVER_LENGTH_ADDRESS, DRIVER_LENGTH_ADDRESS + 2),
                         (0xEC0DE, DRIVER_LIMIT))


def modern_symbols(path: Path) -> dict[str, int]:
    """Read AS's complete listing symbol table (including folded long names)."""
    return {key: int(value, 16) & 0xFFFFFF for key, value in re.findall(
        r"([\w.]+)\s*:\s*([0-9A-F]+) [C\-]", path.read_text(errors="replace"))}


def assembled_modern_driver(path: Path) -> bytes:
    """Join modern AS object records, excluding the earlier Z80 startup stub.

    Current upstream AS splits the driver into two contiguous records. Require
    complete records in order: no overlaps, holes, or unaccounted Z80 payload.
    """
    data = path.read_bytes()
    if data[:2] != b"\x89\x14":
        raise BuildError("Invalid modern AS object header")
    position, output, found = 2, bytearray(), False
    while position < len(data):
        kind = data[position]
        position += 1
        if kind == 0:
            break
        if kind == 0x80:
            position += 3
            continue
        cpu = kind
        if kind == 0x81:
            cpu, _, granularity = data[position:position + 3]
            position += 3
            if granularity != 1:
                raise BuildError("Unsupported modern AS object granularity")
        start = int.from_bytes(data[position:position + 4], "little")
        length = int.from_bytes(data[position + 4:position + 6], "little")
        position += 6
        segment = data[position:position + length]
        position += length
        if len(segment) != length:
            raise BuildError("Truncated modern AS object segment")
        if cpu == 0x51:
            if start == 0:
                if found:
                    raise BuildError("Duplicate modern Z80 driver")
                found = True
            if found:
                if start != len(output):
                    raise BuildError("Noncontiguous modern Z80 driver")
                output.extend(segment)
    if not found:
        raise BuildError("Missing modern Z80 driver")
    return bytes(output)


def verify_modern_driver(data: bytes, assembled: bytes | None = None) -> dict[str, int | str]:
    from .driver import LOADER_READ, saxman_decode

    helper = HANDOFF_ADDRESSES["ForgeModernSaxGetByte"]
    if data[helper:helper + len(LOADER_READ)] != LOADER_READ or data.count(LOADER_READ) != 1:
        raise BuildError("Modern loader fix changed or is duplicated")
    if data[0xEC0DE:DRIVER_START] != bytes.fromhex("4ef9") + helper.to_bytes(4, "big") + bytes.fromhex("4e714e71"):
        raise BuildError("Modern loader trampoline changed")
    length = int.from_bytes(data[DRIVER_LENGTH_ADDRESS:DRIVER_LENGTH_ADDRESS + 2], "big")
    if length != Z80_COMPRESSED_SIZE or DRIVER_START + length > DRIVER_LIMIT:
        raise BuildError("Modern compressed driver exceeds its audited reserved region/length")
    packed = data[DRIVER_START:DRIVER_LIMIT]
    if hashlib.sha256(packed).hexdigest() != DRIVER_REGION_SHA256:
        raise BuildError("Modern compressed driver/padding differs from audited bytes")
    loaded = saxman_decode(packed[:length])
    if len(loaded) != Z80_LOADED_SIZE or hashlib.sha256(loaded).hexdigest() != Z80_SHA256:
        raise BuildError("Modern loaded Z80 bytes differ from audited driver")
    if assembled is not None and loaded != assembled:
        raise BuildError("Modern loaded Z80 bytes differ from assembler object")
    return {"z80_compressed_bytes": length, "z80_loaded_bytes": len(loaded),
            "z80_loaded_sha256": hashlib.sha256(loaded).hexdigest()}


def verify_modern(path: Path) -> dict[str, str | int]:
    """Audit the native seam, inert backend, and reconstructed upstream identity."""
    from .source import genesis_checksum

    try:
        data = path.read_bytes()
    except OSError as exc:
        raise BuildError(f"Cannot read modern scaffold ROM {path}: {exc}") from exc
    if len(data) != PREPARED_ROM_SIZE:
        raise BuildError(f"Modern scaffold ROM size is {len(data)}, expected {PREPARED_ROM_SIZE}")
    stored, calculated = genesis_checksum(data)
    if stored != calculated:
        raise BuildError(f"Modern checksum mismatch: stored {stored:04X}, calculated {calculated:04X}")
    if int.from_bytes(data[0x1A4:0x1A8], "big") != len(data) - 1:
        raise BuildError("Modern ROM header end does not cover the appended code and padding")
    signatures = {
        "overlay_address_signatures": data.count(bytes.fromhex("0003f7fa")),
        "command_address_signatures": data.count(bytes.fromhex("0003f7fe")),
        "command_write_signatures": sum(data.count(bytes.fromhex("33fc") + command.to_bytes(2, "big")
                                                     + bytes.fromhex("0003f7fe")) for _, command in COMMANDS),
        "overlay_open_signatures": data.count(bytes.fromhex("33fccd540003f7fa")),
        "overlay_close_signatures": data.count(bytes.fromhex("33fc00000003f7fa")),
    }
    if signatures != {
        "overlay_address_signatures": 42, "command_address_signatures": 21,
        "command_write_signatures": 21, "overlay_open_signatures": 21,
        "overlay_close_signatures": 21,
    }:
        raise BuildError(f"Unexpected MD+ signature in modern scaffold: {signatures}")
    if data[PLAY_MUSIC_ADDRESS:PLAY_MUSIC_ADDRESS + 18] != HOOK_BYTES or data.count(HOOK_BYTES) != 1:
        raise BuildError("Modern PlayMusic absolute jump/footprint changed or is duplicated")
    if data[IMPLEMENTATION_ADDRESS:IMPLEMENTATION_ADDRESS + 18] != NATIVE_PLAY_MUSIC:
        raise BuildError("Modern native mailbox implementation changed")
    extension = data[IMPLEMENTATION_ADDRESS:IMPLEMENTATION_END]
    if extension != expected_modern_extension():
        raise BuildError("Modern backend differs from exact audited instructions/transactions")
    if hashlib.sha256(data[IMPLEMENTATION_END:HANDOFF_END]).hexdigest() != HANDOFF_SHA256:
        raise BuildError("Modern handoff differs from audited instructions")
    input_hook = bytes.fromhex("4ef9") + HANDOFF_ADDRESSES["ForgeModernInput"].to_bytes(4, "big")
    if data[0x1084:0x10E0] != input_hook + bytes(0x10E0 - 0x1084 - len(input_hook)):
        raise BuildError("Modern input trampoline/footprint changed")
    driver = verify_modern_driver(data)
    if any(data[HANDOFF_END:]):
        raise BuildError("Unexpected data after modern implementation (expected zero padding)")

    # Reconstruct the stock hook/header, then normalize only the EXACTLY audited
    # input/loader/driver regions above. Require the digest of all remaining
    # stock bytes, including both sides of the driver growth padding. No broad
    # range is ignored: each normalized byte was already checked independently.
    stock = bytearray(data[:STOCK_ROM_SIZE])
    stock[PLAY_MUSIC_ADDRESS:PLAY_MUSIC_ADDRESS + 18] = NATIVE_PLAY_MUSIC
    stock[0x18E:0x190] = bytes.fromhex("d951")
    stock[0x1A4:0x1A8] = (STOCK_ROM_SIZE - 1).to_bytes(4, "big")
    for start, end in STOCK_CHANGED_REGIONS:
        stock[start:end] = bytes(end - start)
    if hashlib.sha256(stock).hexdigest() != STOCK_MASKED_SHA256:
        raise BuildError("Modern scaffold changed bytes outside the audited stock regions")
    return {
        "size": len(data), "header_checksum": f"{stored:04X}",
        "md5": hashlib.md5(data, usedforsecurity=False).hexdigest(),
        "sha256": hashlib.sha256(data).hexdigest(),
        "play_music_address": f"{PLAY_MUSIC_ADDRESS:06X}",
        "implementation_address": f"{IMPLEMENTATION_ADDRESS:06X}",
        "native_implementation_end": f"{DISPATCH_ADDRESS:06X}",
        "dispatch_address": f"{DISPATCH_ADDRESS:06X}",
        "implementation_end": f"{IMPLEMENTATION_END:06X}",
        "extension_sha256": hashlib.sha256(extension).hexdigest(),
        "command_transactions": 21,
        "handoff_end": f"{HANDOFF_END:06X}",
        **driver, **signatures,
    }


def build_modern() -> dict[str, str | int]:
    lua = require_program("lua")
    run([lua, "-e", 'local major, minor = _VERSION:match("(%d+)%.(%d+)"); '
         'assert(tonumber(major) > 5 or (tonumber(major) == 5 and tonumber(minor) >= 3), '
         '"Modern scaffold build requires Lua 5.3 or newer")'])
    preparation = prepare_modern()
    run([lua, "modern_build.lua"], cwd=PREPARED_MODERN_DIR)
    built = PREPARED_MODERN_DIR / "s2built.bin"
    result = verify_modern(built)
    verify_modern_driver(built.read_bytes(), assembled_modern_driver(PREPARED_MODERN_DIR / "forge-s2.p"))
    symbols = modern_symbols(PREPARED_MODERN_DIR / "s2.lst")
    for name, address in HANDOFF_ADDRESSES.items():
        if symbols.get(name) != address:
            raise BuildError(f"Modern handoff symbol moved: {name}")
    shutil.copy2(built, MODERN_ROM_PATH)
    return {**preparation, **result}
