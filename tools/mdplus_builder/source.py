from __future__ import annotations

import os
import re
import shutil
import stat
from pathlib import Path

from .common import ASSEMBLER_DIR, BUILD, DEPENDENCIES, ROM_PATH, SOURCE_DIR, BuildError, load_json, run, sha256

EXPECTED_ROM_SIZE = 2_129_922
PROVEN_SHA256 = "1866e1a0e07da98b42c7a3d7baf34db28eb1751de388538073a669ff9afc1bd5"
OPEN_PATTERN = bytes.fromhex("33 fc cd 54 00 03 f7 fa")
TRACK03_PATTERN = bytes.fromhex("33 fc 12 03 00 03 f7 fe")


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


def bootstrap(*, local_source: Path | None = None, skip_assembler_build: bool = False) -> None:
    deps = load_json(DEPENDENCIES)
    _clone_at(deps["source"]["url"], deps["source"]["commit"], SOURCE_DIR, local_source)
    _clone_at(deps["assembler"]["url"], deps["assembler"]["commit"], ASSEMBLER_DIR)
    if not skip_assembler_build and not (ASSEMBLER_DIR / "asl").exists():
        shutil.copy2(ASSEMBLER_DIR / "Makefile.def.tmpl", ASSEMBLER_DIR / "Makefile.def")
        run(["make", f"-j{os.cpu_count() or 2}", "binaries"], cwd=ASSEMBLER_DIR)


def apply_mdplus(source_dir: Path = SOURCE_DIR) -> dict[str, int]:
    if not (source_dir / ".git").exists():
        raise BuildError(f"Not a Git source checkout: {source_dir}")
    status = _git_output(source_dir, "status", "--porcelain")
    if status:
        msu_existing = (source_dir / "msu-md.asm").read_text(encoding="utf-8")
        s2_existing = (source_dir / "s2.asm").read_text(encoding="utf-8")
        actual_status = {line.strip() for line in status.splitlines()}
        expected_statuses = (
            {"M msu-md.asm", "M s2.asm"},
            {"M build.sh", "M msu-md.asm", "M s2.asm"},
        )
        already_prepared = (
            actual_status in expected_statuses
            and "MDP_CTRL        = $0003F7FA" in msu_existing
            and "move.w  #$CD54,(MDP_CTRL).l" in msu_existing
            and not re.search(r"\bMCD_[A-Z_]+\b", msu_existing)
            and "MD+ is opened later" in s2_existing
            and 'BINCLUDE  "sound\\msu-drv-loop.bin"' not in s2_existing
        )
        if already_prepared:
            return {"already_prepared": 1}
        raise BuildError(f"Source checkout has unexpected changes: {source_dir}\n{status}")

    s2_path = source_dir / "s2.asm"
    s2_lines = s2_path.read_text(encoding="utf-8").splitlines(keepends=True)
    starts = [i for i, line in enumerate(s2_lines) if "jsr" in line and "MSUMD_DRV" in line]
    if len(starts) != 1:
        raise BuildError(f"Expected one MSUMD_DRV startup call, found {len(starts)}")
    start = starts[0]
    try:
        end = next(i for i in range(start, start + 20) if "bra.s" in s2_lines[i] and "msuOK" in s2_lines[i])
    except StopIteration as exc:
        raise BuildError("Could not locate the end of the MSU-MD startup block") from exc
    s2_lines[start : end + 1] = [
        "    ; MD+ is opened later, after Sonic's startup checksum has completed\n",
        "    bra.s   msuOK\n",
    ]
    driver_labels = [i for i, line in enumerate(s2_lines) if line.strip() == "MSUMD_DRV:"]
    if len(driver_labels) != 1:
        raise BuildError(f"Expected one MSUMD_DRV label, found {len(driver_labels)}")
    label = driver_labels[0]
    try:
        include = next(i for i in range(label + 1, label + 6) if "BINCLUDE" in s2_lines[i] and "msu-drv-loop.bin" in s2_lines[i])
    except StopIteration as exc:
        raise BuildError("Could not locate the obsolete MSU-MD driver include") from exc
    s2_lines[include] = "        rts\n"
    s2_path.write_text("".join(s2_lines), encoding="utf-8", newline="\n")

    msu_path = source_dir / "msu-md.asm"
    text = msu_path.read_text(encoding="utf-8")
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
    play_marker = "PlayMusic:\nPlayMSU:\n"
    if text.count(play_marker) != 1:
        raise BuildError("Expected exactly one PlayMSU entry point")
    text = text.replace(play_marker, play_marker + "    move.w  #$CD54,(MDP_CTRL).l\n", 1)
    leftovers = sorted(set(re.findall(r"\bMCD_[A-Z_]+\b", text)))
    if leftovers:
        raise BuildError(f"Unconverted Mega-CD symbols remain: {', '.join(leftovers)}")

    expected = {"definitions": 1, "polls": 50, "seeks": 31, "clocks": 52, "seamless": 31}
    actual = {
        "definitions": definitions,
        "polls": polls,
        "seeks": seeks,
        "clocks": clocks,
        "seamless": seamless,
        "commands": commands,
    }
    for key, value in expected.items():
        if actual[key] != value:
            raise BuildError(f"Conversion count changed for {key}: got {actual[key]}, expected {value}")
    msu_path.write_text(text, encoding="utf-8", newline="\n")

    build_script = source_dir / "build.sh"
    build_script.chmod(build_script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return actual


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
    track_hits = data.count(TRACK03_PATTERN)
    if open_hits != 1 or track_hits != 1:
        raise BuildError(f"MD+ signature check failed: overlay={open_hits}, track03={track_hits}")
    digest = sha256(path)
    if strict_regression and (len(data) != EXPECTED_ROM_SIZE or digest != PROVEN_SHA256):
        raise BuildError(
            "Built ROM differs from the proven regression target: "
            f"size={len(data)}, sha256={digest}"
        )
    return {
        "size": len(data),
        "sha256": digest,
        "header_checksum": f"{stored:04X}",
        "overlay_signatures": open_hits,
        "track03_signatures": track_hits,
    }


def build_rom(source_dir: Path = SOURCE_DIR, output: Path = ROM_PATH) -> dict[str, str | int]:
    asl = ASSEMBLER_DIR / "asl"
    if not asl.exists():
        raise BuildError("Assembler is not built; run bootstrap first")
    env = os.environ.copy()
    env["PATH"] = str(ASSEMBLER_DIR) + os.pathsep + env.get("PATH", "")
    run(["./build.sh", "-r0"], cwd=source_dir, env=env)
    built = source_dir / "s2built.bin"
    if not built.exists():
        raise BuildError("Source build did not produce s2built.bin")
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(built, output)
    return verify_rom(output, strict_regression=True)
