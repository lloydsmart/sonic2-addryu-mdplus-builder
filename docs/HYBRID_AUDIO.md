# Hybrid music architecture

The ROM owns the [fixed sixteen-cue routing policy](TRACKS.md#fixed-rom-routing).
The manifest, CUE and WAV files cannot change it. The corrected hybrid ROM has
been verified on MiSTer across native and MD+ transitions, pause/resume, fades,
native SFX, and a deliberately missing Addryu-owned WAV.

## Source checkpoint and native semantics

The transformation audits ArcadeTV commit
`23d24dda3758a1fd341c01e7f7e94e11780a2608`. Whole-file hashes and exact replacement
counts guard `s2.asm`, `s2.constants.asm`, `s2.sounddriver.asm` and `msu-md.asm`.
The earlier disassembly commit `ee1fc176dbf5a3e5f33129dd4b31f2893ebd1eb1`, present
in the dependency's Git history, confirms the stock PlayMusic implementation:
store d0 in the first mailbox if empty; otherwise replace the second mailbox.
The native routine preserves this policy and the original ID and registers.
PlayMusic returns the byte-move condition codes, preserving the caller's X bit.

`sndDriverInput` runs with the existing VInt Z80 bus lock held. It consumes the
first mailbox when `QueueToPlay` is `$80`, otherwise the second if the first is
empty. FE/FF become `$7F`/`$80` in `zAbsVar.StopMusic`; the Z80 pause routine
freezes music and SFX. Other IDs enter `QueueToPlay` unchanged.

One pinned-source defect requires correction: its four-entry SFX copy loop
also consumes the second music mailbox into `$1B8C`, which is actually
`zAbsVar.VoiceTblPtr`, not a music queue slot. The hybrid build copies only the
three real SFX slots and leaves both music mailboxes to the ready-checked path.

Stock FD (`MusID_Stop`) clears all playback memory, including SFX. F9 starts
40 fade steps, spaced four driver updates apart; DAC stops immediately, and
fade completion also clears all playback memory. FE/FF are whole-driver pause
controls. FB/FC update the native tempo and speed flag, or the saved song's
state while a 1-up plays. `$80` is the driver's idle sentinel, not a native
music-stop command. These facts rule out simply queuing FD, F9, FE or `$80` as
a music-only backend handoff.

## Ownership and handoff

`PlayMusic` serializes routing and MD+ transactions against VInt, preserves
registers, and distinguishes music, controls and SFX. `PlaySound` also routes
music/control requests because the game sends some fades through that entry.
Ordinary SFX stores and stereo/local SFX routines retain their native paths.

MD+ to native sends immediate `$1300` before clearing MD+ ownership and queuing
the unchanged native ID. It cancels pending external playback and stale ducking
or pause state. Repeated native requests use the normal two mailboxes.

Native to MD+ queues a private music-only stop, F7, through those same mailboxes
and `sndDriverInput`. A small extension to the existing Z80 driver disables
music DAC output, clears music playing flags and fade/1-up state, mutes FM L/R
output, and silences initialized PSG music channels. It respects SFX override
bits and leaves SFX track RAM and queues intact. No Z80 reset, replacement
driver or new queue is introduced. A separate Z80 RAM byte holds completion.

The normal `zPlaySoundByIndex` ready store returns `QueueToPlay` to `$80`
before dispatching F7 to the music-only stop. The extension writes `$A5` to
`zHybridAck` only after silencing music, then returns. The 68000 clears this
separate ACK immediately before delivering F7, with the Z80 bus held. A later
`sndDriverInput` observes it, clears it and starts pending MD+ playback. Neither
CPU holds `$F6` in the queue. Stock F1–F7 are invalid command IDs; F7 is caught
before the invalid-gap return. F6 again follows that normal invalid-ID path,
and the F8–FD command table is unchanged. Music-script F6/F7 flags are a
separate namespace and are unchanged.

Stock song initialization and 1-up restoration can overwrite a request after
the driver's early ready store; plain `$80` therefore causes a retry, never
MD+ playback. Queued SFX are retained even if both music mailboxes hold sound
effects. Once the Z80 has consumed F7, an arbitrarily delayed 68000 ACK read
does not block `zCycleQueue`: the queue remains available to ordinary SFX.

The Z80 VInt entry checks for F7 before its pause branch and calls the same
normal dispatcher, allowing handoff from paused native music. On the 68000,
`sndDriverInput` calls `HybridCheckReady` first. `Vint_Level` (via `loc_748`)
and `Vint_TitleCard` (via `loc_BD6`) both call this service between `stopZ80`
and `startZ80`. Lag-frame, controller/palette, special-stage and pause paths
also service it. `Vint_MSUMD` only handles ducking; handoff does not depend on
that hook. The SEGA PCM-only VInt path does not service music requests.

Ownership becomes MD+ when its request is accepted, while a separate handoff
state delays playback. Later MD+ requests replace the pending track. A native
request cancels it; a later acknowledgement is discarded after cancellation. No WAV-existence probe is involved.

Boss recovery already calls `PlayLevelMusic`. Invincibility expiry requests
`Level_Music` unless a boss or drowning takes priority. Drowning recovery uses
`ResumeMusic`, selecting level, invincibility, Super Sonic or boss music as
appropriate. Those existing decisions now pass through the router unchanged.

## Controls and 1-up

MD+ immediate stop/pause uses `$1300`, fade uses `$1328`, and explicit unpause
uses `$1400`. A stopped/faded track cannot be revived by later pause/unpause.
Pause during a handoff defers playback until unpause. Native controls retain
the original driver behavior. Normal pause, slow-motion pause and special-stage
unpause all use the same ownership-aware router.

All fast-track routines and speed-selection branches are removed. MD+ FB/FC
are no-ops; native FB/FC pass through unchanged. The handoff clears stale native
speed state. Speed controls received while MD+ owns the music are not replayed
onto later native cues.

The existing native 1-up jingle and 255-VInt MD+ ducking remain. Ducking runs
only for MD+ ownership and pauses its counter while MD+ is paused or awaiting
handoff. A backend change clears ducking; new MD+ playback restores full volume.
The original driver still suppresses SFX during its 1-up and fade-in sequence,
and with `FixDriverBugs=0` native song loading stops existing SFX as its stock
workaround. These inherited behaviors are not redesigned. During MD+ pause,
the native 1-up can finish because MD+ ownership does not pause the native
SFX driver; the retained duck timer is approximate rather than jingle-driven.
The original SEGA PCM cue is restored instead of requesting external track 32.

## RAM and reset

| Address | Meaning |
| --- | --- |
| `$FFF111` | Music owner: 0 native, 1 MD+ |
| `$FFF112` | Pending Sonic music ID |
| `$FFF113` | Handoff: 0 idle, 1 stop queued/deferred, 2 awaiting acknowledgement |
| `$FFF114` | Explicit MD+ pause flag |
| `$FFF115` | Active MD+ track flag, cleared by stop/fade/reset |
| Z80 `$1FF4` / 68000 `$A01FF4` | Handoff ACK: `$A5` complete, zero otherwise |

These five new bytes lie in the `$FFF100`–`$FFF5FF` area documented as unused
Sonic 1 driver RAM in `s2.constants.asm`. ArcadeTV used only `$FFF100`–`$FFF103`
(counter), `$FFF108` (1-up flag), and `$FFF110` (last track). The counter and
1-up flag remain; the last-track byte is no longer used. Source references and
the assembler map show no overlapping allocation. The separate `MSU_RAM`
symbol is `$FFD500`, overlapping alternate game-mode buffers, and is not used.

`zHybridAck` is allocated at `zTracksSaveEnd`, with an assembly assertion fixing
its address at `$1FF4`. Stock music tracks end at `$1D3C`, SFX at `$1E38`, and
the 1-up backup occupies `$1E38`–`$1FF3` inclusive. Clear/init routines stop at
the music/SFX boundaries; save and restore use the exclusive backup end.
The stack starts at `$1B80` and grows downward, and music data starts at `$1380`.
The final twelve bytes of the 8 KiB Z80 RAM were unallocated; the new latch uses
one. No pinned-source raw-address or aliased allocation overlaps it.

`zVar.Communication` at `$1B86` is **not unused by the actual music**. Its only
explicit driver writer is `cfSetCommunication`, reached through script flag
E2. Native `Mus_EL_FM2` (extra life), `MusGOver_FM4` (game over),
`MusEmeraldPSG1` and `MusEmeraldDAC` contain executable `E2,01` commands. There
is no gameplay reader in the pinned source, but initialization clears this byte
and the 1-up backup/restore copies it. It cannot serve as an independent,
persistent completion latch. The separate byte avoids all these writes.

Cold initialization clears all RAM, and `GameInit` clears through `$FFFDFF`
on warm initialization too. `HybridReset`, after the startup checksum and sound
driver load, also stops external playback and explicitly clears ownership,
pending state, both music mailboxes and ducking state.

## First hardware failure

The first hybrid ROM (`a7a9f6e69bad6028da1e1e9b4213209d94d5846d4c97ca1ae88ba0434133c792`,
checksum `812E`) failed twice on MiSTer: title/menu music worked, then entering
EHZ silenced all audio. The hardware result supersedes its earlier unit tests.

Its `SaxDec_GetByte` read a compressed byte, decremented the remaining length,
and returned directly out of decompression when that length reached zero.
Thus the caller never processed the last byte. The default `s2p2bin` compressor
emits exactly the payload, whereas its alternate accurate mode appends a
sentinel byte. In this ROM, the last byte completes a four-byte dictionary
match. The 68000 loads `$1376` bytes, although the assembler emits `$137A`:

| Missing Z80 address | Bytes | Instruction |
| --- | --- | --- |
| `$1376`–`$1378` | `32 88 1B` | `ld (zAbsVar.QueueToPlay),a` |
| `$1379` | `C9` | `ret` |

The routine therefore silences BGM, loads A with F6, then falls into memory
that is not its intended code. It cannot execute its intended ACK store or
return. `HybridCheckReady` never receives proof of completion and never sends
track03; subsequent Z80 execution is uncontrolled. Executing the failed ROM's
actual 68000 loader in Unicorn (M68000 mode) confirms the exact truncation and
all preceding bytes. This is a loader/code-integrity failure, not a missing
VInt hook or a timing delay.

The held-F6 hypothesis identifies a real architectural starvation bug:
`zCycleQueue` returns immediately for every queue value except `$80`. A CPU
regression reproduces that behavior. However, **a held F6 was not produced by
the intended path in this failed ROM**, because the store itself was missing.
Changing the handshake alone would have left the truncated return defect.

The corrected byte-reader decrements the count before reading and exits only
on underflow. It processes all declared compressed bytes without reading past
the input. Every build now checks this instruction sequence, decompresses the
ROM payload and compares every loaded byte with AS's original Z80 segment.
No checksum, signature or ROM regression check has been relaxed.

## Audits and tests

The legacy input audit still accounts for 1 register-definition group, 50
polls, 31 seeks, 52 command clocks and 31 seamless conversions. The replacement
router emits 21 commands: 16 track plays, immediate stop, fade, resume and two
volume commands. Every command has an immediately adjacent overlay open and
close. Source and ROM-byte validation both enforce adjacency and counts.
No command can select tracks 33–48.

The focused test executor follows the actual generated 68000 assembly branches
and stores, including mailbox contention, cancellation, retries and pause
ordering. It is deliberately not a Mega Drive or Z80 emulator. The additional
`tests/check_hybrid_binary.py` suite uses pinned Unicorn and Z80 CPU emulators
to execute the compiled ROM, including actual decompression and both CPUs'
handoff code. It checks title → EHZ → native boss → CPZ, paused native handoff,
stale ACK clearing, exact MD+ transaction writes, SFX consumption during 120
withheld ACK observations, 60 complete Z80 VInts without 68000 service, SFX RAM
preservation and ACK survival across native clear/init. The title-card/level
VInt bus-lock call sites are checked against generated source.

Synthetic unit tests reproduce both final-literal and final-match truncation
and require the build audit to reject an old loader or incomplete driver.
These checks establish code/build properties. Sound-chip busy reads are modeled
as ready, and MD+ writes are recorded rather than playing audio. Extended MiSTer
testing additionally confirmed native title/menu audio; Addryu EHZ and CPZ;
native invincibility, extra-life, Robotnik, level-complete and drowning cues;
return to Addryu music after temporary native cues; native SFX under MD+;
fade, pause and resume behavior; and progression to Aquatic Ruin. With
`track07.wav` deliberately absent, Aquatic Ruin was silent while native SFX
continued, confirming that package contents do not alter ROM routing.
