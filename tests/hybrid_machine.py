"""Small, strict 68K source executor for the generated router's instruction subset.

This exercises emitted assembly branches and stores, not a second Python router.
It does not emulate the Mega Drive, Z80, sound hardware, or instruction timing.
Unsupported instructions fail rather than silently doing nothing.
"""
from __future__ import annotations

import re

from tools.mdplus_builder.source import _hybrid_msu_source

MUSIC_IDS = dict(zip(
    ['2PResults', 'EHZ', 'MCZ_2P', 'OOZ', 'MTZ', 'HTZ', 'ARZ', 'CNZ_2P', 'CNZ',
     'DEZ', 'MCZ', 'EHZ_2P', 'SCZ', 'CPZ', 'WFZ', 'HPZ', 'Options', 'SpecStage',
     'Boss', 'EndBoss', 'Ending', 'SuperSonic', 'Invincible', 'ExtraLife', 'Title',
     'EndLevel', 'GameOver', 'Continue', 'Emerald', 'Credits', 'Countdown'],
    range(0x81, 0xA0), strict=True))

SYMBOLS = {f'MusID_{name}': value for name, value in MUSIC_IDS.items()}
SYMBOLS.update({
    'MusID__First': 0x81, 'MusID__End': 0xA0, 'MusID_StopSFX': 0xF8,
    'MusID_FadeOut': 0xF9, 'SndID_SegaSound': 0xFA,
    'MusID_SpeedUp': 0xFB, 'MusID_SlowDown': 0xFC, 'MusID_Stop': 0xFD,
    'MusID_Pause': 0xFE, 'MusID_Unpause': 0xFF,
    'Music_to_play': 0xFFFFE0, 'Music_to_play_2': 0xFFFFE4,
    'Z80_RAM': 0xA00000, 'zAbsVar.QueueToPlay': 0x1B88, 'zHybridAck': 0x1FF4,
})


class RouterMachine:
    def __init__(self):
        self.symbols = dict(SYMBOLS)
        self.code = []
        self.labels = {}
        for raw in _hybrid_msu_source().splitlines():
            line = raw.split(';')[0].strip()
            if not line:
                continue
            if line.endswith(':'):
                self.labels[line[:-1]] = len(self.code)
            elif re.match(r'^\w+\s+(equ|=)\s+', line):
                name, _, expr = line.split(maxsplit=2)
                self.symbols[name] = self.value(expr)
            else:
                self.code.append(line)
        self.mem = {}
        self.reg = {'d0': 0, 'a0': 0, 'sr': 0x2300}
        self.events = []
        self.stack = []
        self.z = False
        self.c = False
        self.set('Z80_RAM+zAbsVar.QueueToPlay', 0x80)

    def value(self, expr):
        expr = expr.strip().removeprefix('#')
        if expr.startswith('(') and expr.endswith(')'):
            return self.value(expr[1:-1])
        if '+' in expr:
            return sum(self.value(part) for part in expr.split('+'))
        if '|' in expr:
            left, right = expr.split('|')
            return self.value(left) | self.value(right)
        if expr.startswith('$'):
            return int(expr[1:], 16)
        if expr.isdecimal():
            return int(expr)
        return self.symbols[expr]

    def address(self, operand):
        expr = re.fullmatch(r'\((.+)\)(?:\.[wl])?', operand)[1]
        return self.reg[expr] if expr in self.reg else self.value(expr)

    def get(self, name):
        return self.mem.get(self.value(name), 0)

    def set(self, name, value):
        self.mem[self.value(name)] = value

    def read(self, operand, size):
        if operand == '(sp)+':
            return self.stack.pop()
        if operand.startswith('#'):
            return self.value(operand)
        if operand in self.reg:
            return self.reg[operand] & ((1 << size) - 1)
        addr = self.address(operand)
        return sum(self.mem.get(addr + i, 0) << (size - 8 - 8*i) for i in range(size//8))

    def write(self, operand, value, size):
        value &= (1 << size) - 1
        if operand == '-(sp)':
            self.stack.append(value)
        elif operand in self.reg:
            self.reg[operand] = (self.reg[operand] & ~((1 << size)-1)) | value
        else:
            addr = self.address(operand)
            self.events.append((addr, value, size))
            for i in range(size//8):
                self.mem[addr+i] = (value >> (size-8-8*i)) & 255

    @property
    def commands(self):
        return [value for addr, value, _ in self.events if addr == self.symbols['MDP_CMD']]

    def call(self, label, request=None):
        if request is not None:
            self.reg['d0'] = self.value(request) if isinstance(request, str) else request
        original = dict(self.reg)
        calls = []
        pc = self.labels[label]
        for _ in range(3000):
            instruction = self.code[pc]
            pc += 1
            op, *rest = instruction.split(maxsplit=1)
            args = rest[0].split(',') if rest else []
            name, _, suffix = op.partition('.')
            size = {'b': 8, 'w': 16, 'l': 32}.get(suffix, 32)
            if name in {'beq', 'bne', 'blo', 'bhs', 'bra', 'bsr'}:
                take = {'beq': self.z, 'bne': not self.z, 'blo': self.c,
                        'bhs': not self.c, 'bra': True, 'bsr': True}[name]
                if take:
                    if name == 'bsr':
                        calls.append(pc)
                    pc = self.labels[args[0]]
            elif name == 'rts':
                if not calls:
                    if label in {'PlayMusic', 'HybridCheckReady'}:
                        assert self.reg == original, (label, self.reg, original)
                    return
                pc = calls.pop()
            elif name == 'movem':
                if args[1] == '-(sp)':
                    self.stack.append({r: self.reg[r] for r in args[0].split('/')})
                else:
                    self.reg.update(self.stack.pop())
            elif name == 'lea':
                self.reg[args[1]] = self.address(args[0])
            elif name in {'move', 'clr', 'addq', 'ori'}:
                target = args[-1]
                value = 0 if name == 'clr' else self.read(args[0], size)
                if name == 'addq':
                    value += self.read(target, size)
                elif name == 'ori':
                    value |= self.read(target, size)
                self.write(target, value, size)
                self.z = value & ((1 << size)-1) == 0
                self.c = False
            elif name in {'cmp', 'cmpi', 'tst'}:
                right = self.read(args[-1], size)
                left = 0 if name == 'tst' else self.read(args[0], size)
                self.z, self.c = right == left, right < left
            else:
                raise AssertionError(instruction)
        raise AssertionError('Router did not return')

    def handoff(self):
        """Deliver through the first/second mailbox, then simulate Z80 acknowledgement."""
        self.deliver()
        assert self.get('Z80_RAM+zAbsVar.QueueToPlay') == self.value('MusID_HybridStop')
        self.set('Z80_RAM+zAbsVar.QueueToPlay', 0x80)
        self.set('Z80_RAM+zHybridAck', self.value('HybridAckValue'))
        self.call('HybridCheckReady')

    def deliver(self):
        for slot in ['Music_to_play', 'Music_to_play_2']:
            request = self.get(slot)
            if request:
                self.set(slot, 0)
                self.set('Z80_RAM+zAbsVar.QueueToPlay', request)
                if request == self.value('MusID_HybridStop'):
                    self.set('Z80_RAM+zHybridAck', 0)
                    self.set('v_MDPlusHandoff', 2)
                return request
        return 0
