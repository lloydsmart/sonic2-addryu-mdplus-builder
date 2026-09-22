"""Check the compressed Z80 driver against what the 68000 loader actually loads."""
from __future__ import annotations

import re
from pathlib import Path

from .common import BuildError

# SUBQ.W #1,D7 / BCS.S exit / MOVE.B (A6)+,D0 / RTS / ADDQ.W #4,SP / RTS.
# Unlike the stock loader, this processes the final byte before returning.
LOADER_READ = bytes.fromhex('5347 6504 101e 4e75 584f 4e75')


def saxman_decode(data: bytes, *, stock_loader: bool = False) -> bytes:
    """Decode bounded Saxman data; optionally reproduce the stock loader's EOF bug."""
    position = 0
    output = bytearray()

    def read() -> int:
        nonlocal position
        if position >= len(data):
            raise EOFError
        value = data[position]
        position += 1
        if stock_loader and position == len(data):
            raise EOFError
        return value

    try:
        while True:
            descriptor = read()
            for bit in range(8):
                if descriptor & (1 << bit):
                    output.append(read())
                else:
                    low, high = read(), read()
                    offset = ((low | ((high & 0xF0) << 4)) + 0x12) & 0xFFF
                    offset |= len(output) & ~0xFFF
                    if offset > len(output):
                        offset -= 0x1000
                    if offset < 0:
                        output.extend(bytes((high & 15) + 3))
                        continue
                    for _ in range((high & 15) + 3):
                        if offset >= len(output):
                            raise BuildError('Saxman reference is outside loaded driver')
                        output.append(output[offset])
                        offset += 1
                if len(output) > 0x10000:
                    raise BuildError('Saxman output exceeds Z80 address space')
    except EOFError:
        return bytes(output)


def assembled_driver(path: Path) -> bytes:
    """Extract the single Z80 segment from AS's generated .p file."""
    data = path.read_bytes()
    if data[:2] != b'\x89\x14':
        raise BuildError('Invalid AS object header')
    position = 2
    segments = []
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
                raise BuildError('Unsupported AS object granularity')
        start = int.from_bytes(data[position:position + 4], 'little')
        length = int.from_bytes(data[position + 4:position + 6], 'little')
        position += 6
        segment = data[position:position + length]
        position += length
        if len(segment) != length:
            raise BuildError('Truncated AS object segment')
        # The 68K startup also embeds a short Z80 reset program at a ROM
        # address. Only the segment at zero is compressed as the sound driver.
        if cpu == 0x51 and start == 0:
            segments.append(segment)
    if len(segments) != 1:
        raise BuildError('Expected exactly one assembled Z80 driver')
    return segments[0]


def verify_driver_load(source_dir: Path, rom: bytes) -> dict[str, int]:
    header = (source_dir / 's2.h').read_text(errors='replace')
    match = re.search(r'#define movewZ80CompSize 0x([0-9A-Fa-f]+)', header)
    if match is None:
        raise BuildError('Missing compressed driver length location')
    length_instruction = int(match[1], 16)
    if rom[length_instruction - 4:length_instruction - 2] != bytes.fromhex('4dfa'):
        raise BuildError('Unexpected sound driver loader address instruction')
    if rom[length_instruction:length_instruction + 2] != bytes.fromhex('3e3c'):
        raise BuildError('Unexpected sound driver length instruction')
    start = length_instruction - 2 + int.from_bytes(
        rom[length_instruction - 2:length_instruction], 'big', signed=True)
    length = int.from_bytes(rom[length_instruction + 2:length_instruction + 4], 'big')
    if rom[length_instruction:start].count(LOADER_READ) != 1:
        raise BuildError('Sound driver loader does not process the final compressed byte')
    loaded = saxman_decode(rom[start:start + length])
    assembled = assembled_driver(source_dir / 's2.p')
    if loaded != assembled:
        raise BuildError(f'Loaded Z80 driver differs from assembly: {len(loaded)} vs {len(assembled)} bytes')
    if len(loaded) > 0x1380:
        raise BuildError('Loaded Z80 driver overlaps music data')
    return {'z80_compressed_bytes': length, 'z80_loaded_bytes': len(loaded)}
