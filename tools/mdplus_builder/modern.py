from __future__ import annotations

import hashlib
import shutil
import tempfile
from pathlib import Path

from .common import BUILD, DEPENDENCIES, BuildError, load_json, require_program, run
from .source import _clone_at, _git_output

SOURCE_MODERN_DIR = BUILD / "source-modern"
STOCK_MODERN_ROM_PATH = BUILD / "sonic2-stock-modern.md"
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


def _prepare_modern_source(data: bytes) -> bytes:
    if hashlib.sha256(data).hexdigest() != UPSTREAM_S2_SHA256:
        raise BuildError("Pinned modern s2.asm source structure changed")
    text = data.decode("utf-8")
    for old, new in ((NATIVE_SOURCE, HOOK_SOURCE), (TAIL_SOURCE, TAIL_REPLACEMENT)):
        if text.count(old) != 1:
            raise BuildError(f"Expected exactly one modern source pattern: {old!r}")
        text = text.replace(old, new)
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
        main = work / "s2.asm"
        prepared = _prepare_modern_source(main.read_bytes())
        extension = Path(__file__).with_name("hybrid_modern.asm")
        if (work / extension.name).exists():
            raise BuildError("Modern source already contains Forge's include filename")
        main.write_bytes(prepared)
        shutil.copy2(extension, work / extension.name)
        # Only this generated output is replaced; dependency checkouts are inputs.
        if PREPARED_MODERN_DIR.exists():
            shutil.rmtree(PREPARED_MODERN_DIR)
        work.rename(PREPARED_MODERN_DIR)
    return {"source_commit": head, "prepared_source": str(PREPARED_MODERN_DIR)}


def verify_modern(path: Path) -> dict[str, str | int]:
    """Prove the entire ROM differs from stock only by the audited Stage 2 seam."""
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
        "overlay_open_signatures": data.count(bytes.fromhex("33fccd540003f7fa")),
        "overlay_close_signatures": data.count(bytes.fromhex("33fc00000003f7fa")),
    }
    if any(signatures.values()):
        raise BuildError(f"Unexpected MD+ signature in modern scaffold: {signatures}")
    if data[PLAY_MUSIC_ADDRESS:PLAY_MUSIC_ADDRESS + 18] != HOOK_BYTES or data.count(HOOK_BYTES) != 1:
        raise BuildError("Modern PlayMusic absolute jump/footprint changed or is duplicated")
    if data[IMPLEMENTATION_ADDRESS:IMPLEMENTATION_ADDRESS + 18] != NATIVE_PLAY_MUSIC:
        raise BuildError("Modern native mailbox implementation changed")
    if any(data[IMPLEMENTATION_ADDRESS + 18:]):
        raise BuildError("Unexpected data after modern implementation (expected zero padding)")

    # Restore the only allowed differences within stock REV01 and require its
    # exact identity. This also protects SFX, Z80, startup and every call site;
    # signature scanning alone cannot prove the absence of arbitrary I/O writes.
    stock = bytearray(data[:STOCK_ROM_SIZE])
    stock[PLAY_MUSIC_ADDRESS:PLAY_MUSIC_ADDRESS + 18] = NATIVE_PLAY_MUSIC
    stock[0x18E:0x190] = bytes.fromhex("d951")
    stock[0x1A4:0x1A8] = (STOCK_ROM_SIZE - 1).to_bytes(4, "big")
    if (hashlib.md5(stock, usedforsecurity=False).hexdigest() != STOCK_ROM_MD5
            or hashlib.sha256(stock).hexdigest() != STOCK_ROM_SHA256):
        raise BuildError("Modern scaffold changed bytes outside the audited stock hook/header")
    return {
        "size": len(data), "header_checksum": f"{stored:04X}",
        "md5": hashlib.md5(data, usedforsecurity=False).hexdigest(),
        "sha256": hashlib.sha256(data).hexdigest(),
        "play_music_address": f"{PLAY_MUSIC_ADDRESS:06X}",
        "implementation_address": f"{IMPLEMENTATION_ADDRESS:06X}",
        "implementation_end": f"{IMPLEMENTATION_ADDRESS + 18:06X}",
        **signatures,
    }


def build_modern() -> dict[str, str | int]:
    lua = require_program("lua")
    run([lua, "-e", 'local major, minor = _VERSION:match("(%d+)%.(%d+)"); '
         'assert(tonumber(major) > 5 or (tonumber(major) == 5 and tonumber(minor) >= 3), '
         '"Modern scaffold build requires Lua 5.3 or newer")'])
    preparation = prepare_modern()
    run([lua, "build.lua"], cwd=PREPARED_MODERN_DIR)
    built = PREPARED_MODERN_DIR / "s2built.bin"
    result = verify_modern(built)
    shutil.copy2(built, MODERN_ROM_PATH)
    return {**preparation, **result}
