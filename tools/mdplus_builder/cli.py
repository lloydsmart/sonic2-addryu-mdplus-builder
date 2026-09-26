from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from .audio import (
    check_ffmpeg_audio_capabilities,
    convert_audio_file,
    detect_loops,
    prepare_audio,
    score_loop,
    validate_manifest,
    validate_wave,
)
from .common import (
    BUILD,
    DEFAULT_MANIFEST,
    DIST,
    LEGACY_ROM_PATH,
    PREPARED_LEGACY_DIR,
    ROM_PATH,
    BuildError,
    crc32,
    require_program,
)
from .modern import bootstrap_modern, build_modern, build_stock_modern, prepare_modern, verify_modern
from .package import assemble, cue_text
from .source import apply_mdplus, bootstrap, build_rom, prepare_legacy, verify_rom

CLEAN_ROM_REVISIONS = {
    "24AB4C3A": "World Rev 0",
    "7B905383": "World Rev 1",
}


def _path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def _clean_rom_revision(value: str) -> str:
    try:
        return CLEAN_ROM_REVISIONS[value]
    except KeyError as exc:
        expected = ", ".join(
            f"{crc} ({revision})"
            for crc, revision in CLEAN_ROM_REVISIONS.items()
        )
        raise BuildError(
            f"CRC32 is {value}; expected one of: {expected}"
        ) from exc


def _legacy_option(command: argparse.ArgumentParser) -> None:
    command.add_argument("--legacy", action="store_true", help="select the previous msu-md-sonic2 fallback")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="sonic2-mdplus",
        description="Build legal, reproducible Sonic the Hedgehog 2 MD+ variants from user-supplied inputs.",
    )
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="check required host programs")

    p = commands.add_parser("bootstrap", help="fetch pinned production s2disasm source (legacy: source and ASL)")
    p.add_argument("--local-source", type=_path, help="clone the Sonic source from an existing local checkout")
    p.add_argument("--skip-assembler-build", action="store_true", help="legacy only: fetch ASL without building")
    _legacy_option(p)

    p = commands.add_parser("bootstrap-modern", help="compatibility alias for bootstrap")
    p.add_argument("--local-source", type=_path, help="clone s2disasm from an existing local checkout")
    commands.add_parser("build-stock-modern", help="build and verify stock REV01 with upstream Lua (no MD+)")

    commands.add_parser("prepare-modern", help="compatibility alias for prepare-source")
    commands.add_parser("build-modern", help="compatibility alias for build-rom (same canonical output)")

    p = commands.add_parser("prepare-source", help="prepare the pinned production MD+ source")
    p.add_argument("--source-dir", type=_path, help="legacy only: use a disposable source checkout")
    _legacy_option(p)

    p = commands.add_parser("build-rom", help="prepare, build and verify the production REV01 MD+ ROM")
    p.add_argument("--source-dir", type=_path, help="legacy only: use a disposable source checkout")
    _legacy_option(p)
    p.add_argument("--output", type=_path, help="ROM output (default: build/sonic2-mdplus.md; legacy: build/sonic2-legacy-mdplus.md)")

    p = commands.add_parser("verify-rom", help="verify a generated ROM's checksum and MD+ signatures")
    p.add_argument("rom", type=_path)
    p.add_argument("--strict-regression", action="store_true")
    _legacy_option(p)

    p = commands.add_parser("verify-clean-rom", help="identify a supported clean Sonic 2 World ROM revision")
    p.add_argument("rom", type=_path)

    p = commands.add_parser("validate-manifest", help="validate track definitions and print the CUE")
    p.add_argument("--manifest", type=_path, default=DEFAULT_MANIFEST)

    p = commands.add_parser("prepare-audio", help="convert enabled user WAVs to MD+ format")
    p.add_argument("--manifest", type=_path, default=DEFAULT_MANIFEST)
    p.add_argument("--input-dir", type=_path, required=True)
    p.add_argument("--output-dir", type=_path, default=BUILD / "audio")

    p = commands.add_parser("convert-audio", help="normalize one WAV for loop analysis")
    p.add_argument("input", type=_path)
    p.add_argument("output", type=_path)
    p.add_argument("--end-sector", type=int)
    p.add_argument("--speed", type=float, default=1.0)

    p = commands.add_parser("validate-audio", help="validate PCM format and optional sector length")
    p.add_argument("wav", type=_path)
    p.add_argument("--end-sector", type=int)

    p = commands.add_parser("detect-loop", help="rank sector-aligned repeated-boundary candidates")
    p.add_argument("wav", type=_path)
    p.add_argument("--start-range", required=True, help="candidate start range in seconds, START:END")
    p.add_argument("--end-range", required=True, help="candidate end range in seconds, START:END")
    p.add_argument("--top", type=int, default=10)
    p.add_argument("--window-ms", type=int, default=300)

    p = commands.add_parser("validate-loop", help="score a defined sector-aligned loop boundary")
    p.add_argument("wav", type=_path)
    p.add_argument("--start-sector", type=int, required=True)
    p.add_argument("--end-sector", type=int, required=True)
    p.add_argument("--window-ms", type=int, default=300)
    p.add_argument("--max-score", type=float, help="fail when normalized RMS score exceeds this value")

    p = commands.add_parser("package", help="assemble the MiSTer-ready directory")
    p.add_argument("--manifest", type=_path, default=DEFAULT_MANIFEST)
    p.add_argument("--rom", type=_path, help="verified ROM to package (defaults to the selected implementation)")
    _legacy_option(p)
    p.add_argument("--audio-dir", type=_path, default=BUILD / "audio")

    p = commands.add_parser("all", help="bootstrap, convert, build, prepare audio, and package")
    p.add_argument("--manifest", type=_path, default=DEFAULT_MANIFEST)
    p.add_argument("--input-dir", type=_path, required=True)
    p.add_argument("--local-source", type=_path)
    _legacy_option(p)

    commands.add_parser("clean", help="remove ignored build and dist outputs")
    return root


def _print_json(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "doctor":
            result: dict[str, object] = {
                name: require_program(name) for name in ("git", "make", "gcc", "python3", "lua")
            }
            capabilities = check_ffmpeg_audio_capabilities()
            result["ffmpeg"] = capabilities.pop("ffmpeg")
            result["ffprobe"] = capabilities.pop("ffprobe")
            result["audio_conversion"] = capabilities
            _print_json(result)
        elif args.command == "bootstrap":
            if args.legacy:
                bootstrap(local_source=args.local_source, skip_assembler_build=args.skip_assembler_build)
            else:
                if args.skip_assembler_build:
                    raise BuildError("--skip-assembler-build requires --legacy")
                bootstrap_modern(local_source=args.local_source)
        elif args.command == "bootstrap-modern":
            bootstrap_modern(local_source=args.local_source)
        elif args.command == "build-stock-modern":
            _print_json(build_stock_modern())
        elif args.command == "prepare-modern":
            _print_json(prepare_modern())
        elif args.command == "build-modern":
            _print_json(build_modern())
        elif args.command in {"prepare-source", "build-rom"}:
            if args.source_dir and not args.legacy:
                raise BuildError("--source-dir requires --legacy; production always uses clean pinned source")
            if args.command == "prepare-source":
                _print_json((apply_mdplus(args.source_dir) if args.source_dir else prepare_legacy())
                            if args.legacy else prepare_modern())
            elif args.legacy:
                if not args.source_dir:
                    prepare_legacy()
                _print_json(build_rom(args.source_dir or PREPARED_LEGACY_DIR, args.output or LEGACY_ROM_PATH))
            else:
                _print_json(build_modern(args.output or ROM_PATH))
        elif args.command == "verify-rom":
            verifier = verify_rom if args.legacy else verify_modern
            _print_json(verifier(args.rom, strict_regression=args.strict_regression))
        elif args.command == "verify-clean-rom":
            value = crc32(args.rom)
            revision = _clean_rom_revision(value)
            _print_json({"path": str(args.rom), "crc32": value, "revision": revision})
        elif args.command == "validate-manifest":
            manifest = validate_manifest(args.manifest)
            print(cue_text(manifest), end="")
        elif args.command == "prepare-audio":
            _print_json(prepare_audio(args.manifest, args.input_dir, args.output_dir))
        elif args.command == "convert-audio":
            _print_json(
                convert_audio_file(
                    args.input,
                    args.output,
                    end_sector=args.end_sector,
                    speed=args.speed,
                )
            )
        elif args.command == "validate-audio":
            _print_json(validate_wave(args.wav, end_sector=args.end_sector))
        elif args.command == "detect-loop":
            rows = detect_loops(
                args.wav,
                args.start_range,
                args.end_range,
                top=args.top,
                window_ms=args.window_ms,
            )
            _print_json(
                [
                    {
                        "score": round(score, 8),
                        "start_sector": start,
                        "start_seconds": start / 75,
                        "end_sector": end,
                        "end_seconds": end / 75,
                        "loop_seconds": (end - start) / 75,
                    }
                    for score, start, end in rows
                ]
            )
        elif args.command == "validate-loop":
            score = score_loop(
                args.wav,
                args.start_sector,
                args.end_sector,
                window_ms=args.window_ms,
            )
            _print_json({"normalized_rms_score": score, "lower_is_better": True})
            if args.max_score is not None and score > args.max_score:
                raise BuildError(f"Loop score {score:.8f} exceeds limit {args.max_score:.8f}")
        elif args.command == "package":
            print(assemble(args.manifest, rom_path=args.rom, audio_dir=args.audio_dir, legacy=args.legacy))
        elif args.command == "all":
            if args.legacy:
                bootstrap(local_source=args.local_source)
                prepare_legacy()
                build_rom()
            else:
                bootstrap_modern(local_source=args.local_source)
                build_modern()
            prepare_audio(args.manifest, args.input_dir)
            print(assemble(args.manifest, legacy=args.legacy))
        elif args.command == "clean":
            for directory in (BUILD, DIST):
                if directory.exists():
                    shutil.rmtree(directory)
                    print(f"removed {directory}")
        else:
            raise AssertionError(args.command)
        return 0
    except BuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
