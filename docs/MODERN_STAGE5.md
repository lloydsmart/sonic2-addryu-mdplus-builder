# Modern Stage 5 live routing audit

Stage 5 connects live 68000 ownership and control to the existing Stage 3
backend and frozen Stage 4 acknowledged Z80 handoff. This is the first modern
ROM capable of real MD+ playback. **The required Stage 5 MiSTer FPGA hardware
validation gate has passed**, as reported by the maintainer. Local CPU tests and
source/binary audits remain separate evidence; the hardware results below come
from the maintainer's actual MiSTer testing. Missing-WAV testing was not run and
is optional robustness coverage, not an outstanding merge gate.

Production/default `make rom` and `make all` remain legacy. No modern packaging
or default cutover is included.

## Sources and exact changes

Branch: `migration/05-modern-live-routing`, based on
`migration/current-s2disasm`. The modern dependency remains pinned to
`380f37a731bfc720bb0371a35a593184a7ec5e43`. Preparation uses a fresh clone of that
commit, checks each whole-file SHA-256, then requires exact pattern counts.
Dependency checkouts are read-only inputs.

| Upstream input | Pinned SHA-256 |
| --- | --- |
| `s2.asm` | `448630bb22c08b5281d143438296e5b9045f6539699ec3724147a7f945c938b9` |
| `s2.constants.asm` | `8de5f4a4e6abc56ea2504afe2f4d58cc8a7a3bfa80e3f3c9f1372231a3ca16cd` |
| `s2.sounddriver.asm` | `ff34692c633f96d50073c24f6ebb72df5c739892c31be6b19b2ae604e76232c7` |

Locations below refer to the pinned upstream input, before transformation.

| Input location | Change |
| --- | --- |
| `s2.asm:419–420`, GameInit | Replace two BSRs with JSR + NOP; wrapper runs both original calls, then reset |
| `s2.asm:507–510`, VintRet | Fixed ten-byte jump/padding; wrapper services ducking and performs original return |
| `s2.asm:1270`, sndDriverInput | Retain Stage 4 92-byte trampoline/padding and three-slot input service |
| `s2.asm:1520–1528`, PlayMusic | Retain 18-byte footprint; point at live router |
| `s2.asm:1535–1540`, PlaySound | Six-byte jump; centrally classify music/controls |
| `s2.asm:1546–1550`, PlaySound2 | Six-byte jump; extra-life ducking while retaining SFX1 |
| `s2.asm:1593` | One direct pause store becomes a six-byte call |
| `s2.asm:1620,1631,6825` | Three direct unpause stores become six-byte calls |
| `s2.asm:91549`, SaxDec_GetByte | Unchanged Stage 4 ten-byte loader-helper trampoline |
| `s2.asm:91965`, final finishBank | Include appended Forge code before stock padding/EndOfRom |
| `s2.constants.asm:1379` | Split the unused fixBugs=0 reservation around the seven state fields |
| `s2.sounddriver.asm:227,403,1565,3235,4101` | Retain Stage 4 ACK, F7 dispatch, alignment and include |

Stage 5 adds `hybrid_modern_router.asm`, renames the original appended native
helper, and changes only six Stage 4 68000 bytes at `$100300–$100305`: the old
clear-handoff/RTS becomes a JMP to `ForgeModernComplete`. All Stage 4 labels stay
fixed. Completion clears handoff before consulting ownership/pause/pending.
`hybrid_modern_z80.asm`, the Z80 transformations, F7 dispatch, ACK allocation,
loader semantics and SFX correction are unchanged from Stage 4.

No game-mode or historical ArcadeTV per-call-site patches are imported. Every
other stock byte is protected by the verifier. Source pins, track manifest,
legacy source transformer, build defaults and packaging remain unchanged.

## RAM and ownership

All addresses are in the unused `$FFF100–$FFF5FF` reservation under `fixBugs=0`.
`fixBugs=1` is rejected. Each declaration has an assembly assertion for its
exact address, palette/Game_Mode bounds, and cold/warm GameInit clear bounds.
The verifier also checks compiled state-symbol addresses and exact routine bytes.

| Address | State |
| --- | --- |
| `$FFF100–$FFF103` | Long extra-life duck counter; production increments its low byte |
| `$FFF108` | Duck flag |
| `$FFF111` | Owner: 0 native, 1 MD+ (including pending/silent ownership) |
| `$FFF112` | Pending Sonic music ID, zero when consumed |
| `$FFF113` | Existing handoff: 0 idle, 1 waiting to deliver F7, 2 waiting for A5 |
| `$FFF114` | Explicit MD+ pause |
| `$FFF115` | Active/paused MD+ track |

`$FFF110` is unallocated. No field aliases object or special-stage RAM.
The reservation still ends at `Game_Mode=$FFF600`; its beginning is immediately
after `Underwater_palette+$80`. Stock GameInit clears `$FF0000–$FFFDFF` on both
cold and warm boots. The post-initialization reset also explicitly clears every
field, both music mailboxes, and issues `$1300` to stop stale external audio.

## Routing and controls

PlayMusic saves SR, masks interrupts to level 7, routes, restores SR, then
executes `TST.B d0`. All data/address registers survive. N/Z reflect `d0.b`,
V/C clear, X and the caller's interrupt mask survive. The native helper remains
the original 18 bytes: empty Music0 receives d0; occupied Music0 selects Music1.

Classification uses current upstream symbols. Music is `$81–$9F`, ordinary SFX
`$A0–$F0`, commands start at `$F8`. Extra life is `$98`. The sixteen supported
IDs come from the unchanged `ADDRYU_TRACKS` policy. Every other legitimate music
ID changes ownership to native. Ordinary SFX and invalid bytes cannot acquire
music ownership.

| Request/state | Result |
| --- | --- |
| Supported ID, native owner | Store pending ID, clear explicit pause, acquire MD+, queue F7; no MD+ start |
| Supported ID, handoff pending | Replace pending ID; one handoff remains |
| Supported ID, MD+ owner and idle | Normal volume, dispatch track, set active |
| Matching A5 in state 2 | Clear ACK and handoff; start pending only if owner=MD+ and unpaused |
| Native music, MD+ owner | `$1300`, clear ownership/track/pause/duck, cancel undelivered F7, queue original native ID |
| Extra life | Keep owner; start duck if MD+; queue native jingle on the caller's original queue |
| Fade `$F9`, native | Original native request |
| Fade `$F9`, MD+ | Clear track/pending/pause/duck, `$1328`, retain silent MD+ ownership |
| Stop `$FD`, native | Original native request |
| Stop `$FD`, MD+ | Clear track/pending/pause/duck, `$1300`, retain silent MD+ ownership |
| Pause `$FE`, native | Original native request |
| Pause `$FE`, MD+ | If active/pending, set explicit pause and `$1300`; otherwise no action |
| Unpause `$FF`, native | Original native request |
| Unpause `$FF`, MD+ | Only explicit pause resumes: defer during F7, play pending if any, otherwise `$1400` |
| Speed up/down `$FB/$FC`, native | Original native requests |
| Speed up/down `$FB/$FC`, MD+ | No external transaction or native speed command |

Native-to-MD+ supersedes queued BGM/control requests while retaining ordinary
queued SFX and native SEGA PCM. F7 uses a free music mailbox; it never overwrites
queued SFX. Only input service touches the public Z80 queue/ACK, under the stock
VInt bus lock. `$80` without A5 retries F7. A cancellation removes undelivered F7
from either mailbox. Delivered F7 can finish; its stale ACK cannot start MD+ and
the native request waits in the mailbox until the public queue becomes ready.

Fade/stop during handoff clear the pending track but allow F7 to finish so native
music still becomes silent. Silent MD+ ownership prevents later unpause from
reviving either old backend. Boss, invincibility, drowning, act clear, ending,
title/options and all non-Addryu cues stay native. Recovery uses the game's
existing supported-level request, which starts another acknowledged handoff.
There is no WAV existence probe or file-dependent fallback.

PlaySound routes `$81–$9F`, fade and `$FB–$FF` through PlayMusic. Other bytes keep
the native SFX0 store and stock flags/registers. Stop-SFX `$F8` and SEGA `$FA`
remain native SFX requests. PlaySound2 keeps the SFX1 store for every byte;
only `$98` also starts ducking under masked interrupts.

## Hook and routine addresses

Every upstream replacement retains its original length. Tables, following code,
sound banks and fixed DAC start remain at their stock addresses.

| Hook | Bytes | Target |
| --- | ---: | --- |
| `$00135E` PlayMusic | 18 | `$1003A8` ForgeModernPlayMusic; JMP + six NOPs |
| `$000382` | 8 | `$100692` ForgeModernInit |
| `$00045E` | 10 | `$10067C` ForgeModernVintReturn |
| `$001370` | 6 | `$100614` ForgeModernPlaySound |
| `$001376` | 6 | `$100638` ForgeModernPlaySound2 |
| `$0013AC` | 6 | `$100658` ForgeModernPauseRequest |
| `$0013F2` | 6 | `$10066A` ForgeModernUnpauseRequest |
| `$001406` | 6 | `$10066A` ForgeModernUnpauseRequest |
| `$00541A` | 6 | `$10066A` ForgeModernUnpauseRequest |
| `$001084` sndDriverInput | 92 | `$10032A` ForgeModernInput; unchanged Stage 4 |
| `$0EC0DE` SaxDec_GetByte | 10 | `$10039C` ForgeModernSaxGetByte; unchanged Stage 4 |
| `$100300` ACK completion | 6 | `$10050A` ForgeModernComplete |

New appended routines:

| Routine | Address |
| --- | --- |
| `ForgeModernPlayMusic` | `$1003A8` |
| `ForgeModernRoute` | `$1003B8` |
| `ForgeModernRequest` | `$1004B4` |
| `ForgeModernDiscardMusic` | `$1004EE` |
| `ForgeModernReturn` | `$100508` |
| `ForgeModernComplete` | `$10050A` |
| `ForgeModernPlayPending` | `$10051A` |
| `ForgeModernClearTrack` | `$10053C` |
| `ForgeModernRouteFade` | `$100552` |
| `ForgeModernRouteStop` | `$100562` |
| `ForgeModernPause` | `$100572` |
| `ForgeModernUnpause` | `$100592` |
| `ForgeModernSpeed` | `$1005BA` |
| `ForgeModernExtraLife` | `$1005C4` |
| `ForgeModernDuckStart` | `$1005CC` |
| `ForgeModernDuckService` | `$1005DE` |
| `ForgeModernPlaySound` | `$100614` |
| `ForgeModernPlaySound2` | `$100638` |
| `ForgeModernPauseRequest` | `$100658` |
| `ForgeModernUnpauseRequest` | `$10066A` |
| `ForgeModernVintReturn` | `$10067C` |
| `ForgeModernInit` | `$100692` |
| `ForgeModernReset` | `$10069E` |
| `ForgeModernRouterEnd` | `$1006C0` |

The native helper is `$100000`, second-mailbox path `$10000C`, dispatcher
`$100012`. Stage 3 controls remain `$100094/$1000AE/$1000C8/$1000E2/$1000FC`;
sixteen track primitives remain `$100116–$1002B5`. Stage 4 begin/queue/check/input/
loader remain `$1002B6/$1002BC/$1002E8/$10032A/$10039C` respectively.

VintRet at `$00045E` jumps out of line. The wrapper masks interrupts, services
ducking, restores SR, then executes the original count increment, register
restore and RTE. The dispatch table at `$000468` is untouched. CPU tests execute
the wrapper through the original register restore, inspect the intact exception
frame, and stop at the verified RTE opcode; Unicorn does not execute that RTE.
Input/ACK stays at its existing bus-locked call sites. Ducking needs no Z80 bus.

## Call-site audit

All six upstream `MusID_ExtraLife` sites are unchanged and execute through these
central hooks. Tests execute the enclosing gameplay routines for native and MD+
owners, count exactly one duck-start call, and run the native jingle on the Z80.

| Upstream line | Request address | Gameplay routine | Preserved mailbox |
| --- | --- | --- | --- |
| 25060 | `$012012` | CollectRing_1P | SFX1 via PlaySound2 |
| 25094 | `$01206E` | CollectRing_Tails / 2P rings | SFX1 via PlaySound2 |
| 25846 | `$01294A` | sonic_1up monitor | Music0/Music1 via PlayMusic |
| 25857 | `$012960` | tails_1up monitor | Music0/Music1 via PlayMusic |
| 87819 | `$040D36` | AddPoints | Music0/Music1 via PlayMusic |
| 87854 | `$040D7E` | AddPoints2 | Music0/Music1 via PlayMusic |

The duck flag resets the long counter. Each eligible VInt sends `$1519`, then
increments its low byte. VInt 255 also clears flag/counter and sends `$15FF`.
Explicit pause and handoff freeze the counter. No track restart is issued when
the native jingle restores its saved silent music state. This is the production
255-VInt behavior; it is not derived from WAV duration. The maintainer reports
correct native 1-up/MD+ interaction with no audible problem on MiSTer. Individual
trigger paths and jingle completion during an explicit MD+ pause were not
separately identified in that hardware report; their CPU coverage stays distinct.

All direct pause/unpause stores are replaced, with exact counts of one/three:
`$0013AC` pause, `$0013F2` ordinary resume, `$001406` slow motion,
`$00541A` special-stage resume. Six-byte JSRs preserve surrounding addresses.
Wrappers preserve d0 with MOVEM, so the final flags still match the old immediate
byte store. Native ownership uses the two-mailbox PlayMusic helper.

The PlaySound audit finds music/control requests at these pinned source lines:

- Fade: 4531, 4586, 4762, 12580, 77680, 81441, 82754.
- End-of-level music: 6792; credits: 13192.
- Stop-SFX: 20825, 20836, 21069, 21080, 21177, 21188, 63826.
- Native SEGA PCM: 4187 and 78617.

The central wrapper handles the music and fade sites; Stop-SFX/SEGA stay native.
These caller bytes remain stock. The CPU suite tests all 256 request bytes,
all 32 incoming CCRs, both owners, both sound wrappers, exact native SFX writes,
registers and stack. No ordinary PlaySound2 SFX is sent to the music router.
A live two-CPU test also consumes simultaneous jump/ring requests over successive
VInts, retaining the frozen driver's queue order without restarting MD+.

## Startup/reset evidence

The checksum path begins at `$000328`, sums the expanded ROM using its header
end, compares at `$000344`, and branches to the unchanged error path at `$0003CE`
on failure. Successful cold boot reaches GameInit `$000370`; the existing warm
boot sentinel branch also reaches GameInit. RAM clearing at `$00037C` finishes
before the eight-byte hook at `$000382`.

That hook calls `$100692`: original VDPSetupGame `$001158`, original
JmpTo_SoundDriverLoad `$00130A`, then reset `$10069E`. Reset's first possible MD+
write is the Stage 3 immediate primitive at `$100094`: open `$3F7FA=CD54`,
command `$3F7FE=1300`, close `$3F7FA=0000`. It returns to `$00038A` for the
unchanged JoypadInit call, before SegaScreen is selected.

Actual compiled startup traces:

```text
cold: checksum -> GameInit -> GameClrRAM -> Init wrapper -> Reset -> 1300
warm: existing init sentinel -> GameInit -> GameClrRAM -> Init -> Reset -> 1300
bad checksum: checksum -> error loop; no GameInit and no MD+ write
```

Tests start with stale hybrid state and occupied music mailboxes. Both successful
paths clear every field and mailbox. Bus arbitration is modeled as immediately
granted; checksum summing/comparison, RAM clearing, initialization calls and all
MD+ stores execute actual ROM instructions. The verifier protects all earlier
startup bytes, interrupt dispatch and native SEGA call sites. No external track
32 primitive exists.

## Compiled CPU traces

Values below are hexadecimal unless described as counts. State tuple is
`(owner,pending,handoff,pause,active)`. A5 is written only after the Z80 has
cleared all music active flags, stopped DAC and performed override-aware FM/PSG
muting. Tests break immediately before the actual ACK store to prove ordering.

```text
title/native       (0,00,0,0,0)  native FM active
request EHZ        (1,82,1,0,0)  Music0=F7; no MD+ transaction
68K delivery       (1,82,2,0,0)  Queue=F7, ACK=00; no MD+ transaction
Z80 before ACK     (1,82,2,0,0)  Queue=80, ACK=00; music silent; no MD+ start
Z80 after ACK      (1,82,2,0,0)  Queue=80, ACK=A5; no MD+ start yet
68K ACK service    (1,00,0,0,1)  ACK=00; 15FF -> 1203

EHZ -> CPZ owned   no F7; 15FF -> 1205
EHZ -> boss        1300 -> owner=0; native 93 preserved, delivered, played
boss -> EHZ        F7 -> A5 -> 15FF -> 1203
cancel before F7   1300; remove F7 from Music0 or Music1; boss 93 queued
cancel after F7    1300; boss 93 waits for public queue; late A5 discarded
cancel then CPZ    old A5 discarded; fresh F7; fresh A5 -> 15FF -> 1205
false ready        Queue=80, ACK=00 -> retry F7; no external start
pending EHZ->CPZ   one F7; pending=8E; A5 -> 15FF -> 1205 only
pause during F7    1300; A5 clears handoff, pending remains; unpause -> 15FF/1203
unpause before A5  clears pause only; external start still waits for A5
active pause       1300; no native pause command
active resume      1400; a second unrelated unpause does nothing
fade/stop          1328/1300; silent owner retained; pending/active/pause/duck clear
later unpause      no command after fade/stop
speed FB/FC        MD+ owner: no writes; native owner: original queue commands
extra life         original queue=98; owner retained; counter=0, duck=1
eligible VInt      1519, counter++; pause/handoff freeze timer
VInt 255           1519 -> 15FF; counter=0, duck=0; no MD+ track restart
```

Representative sequences execute both CPUs, checking native FM activity during
temporary cues and silence before every supported-route start:

```text
title/native -> EHZ/MD+ -> invincibility/native -> EHZ/MD+
EHZ/MD+ -> boss/native -> EHZ/MD+
EHZ/MD+ -> act clear/native
CPZ/MD+ -> drowning/native -> CPZ/MD+
```

## Byte identity and verifier

| Measurement | Stage 5 result |
| --- | --- |
| Prepared ROM size | 2,097,152 bytes |
| Header checksum | `BE41` |
| Prepared MD5 | `9eb40c0601a7c424a0d1ce168b5f40f2` |
| Prepared SHA-256 | `bd12138cd478596e4d294a06f573a98a6d37747dfe58d726ca62cf50dc3a8c44` |
| Stock modern size/checksum | 1,048,576 bytes / `D951` |
| Stock modern MD5 | `9feeb724052c39982d432a7851c98d3e` |
| Stock modern SHA-256 | `193bc4064ce0daf27ea9e908ed246d87ec576cc294833badebb590b6ad8e8f6b` |
| Compressed Z80 | 4,009 bytes, unchanged |
| Assembled/actually loaded Z80 | 4,986 bytes, unchanged |
| Z80 code end / music start | `$137A` / `$1380`; six bytes headroom untouched |
| Z80 loaded SHA-256 | `9f997cc7217dda878297f7359f3314c7876aeb29e8705d63bd4b6db1513db24f` |
| Stage 3 region SHA-256 | `a42fecc8e83354d76638f42de8810bbfaa678d54c77b8ae1051a261af26103f1` |
| Live router SHA-256 | `4fb3350a48a1bf210e740fe694f9b6023240bf8cb6d1ecb95fd2be76b7e60f83` |
| Legacy size/checksum | 2,129,922 bytes / `2911` |
| Legacy SHA-256 | `315c69fb84dbca2a31ceffe3face70b4138317feed53feb7e23c6a5ab009205e` |

Stage 3 retains exactly 16 track primitives, five controls, 21 transactions,
21 overlay opens, 21 command writes, 21 closes and 42 overlay-address signatures.
There are no tracks 33–48. Its entire 694-byte native/helper/backend region is
byte-identical, including every primitive and dispatcher branch.

`verify_modern()` checks the full router and each routine digest, each exact
hook/padding byte, the six-byte ACK callback, frozen Stage 4 remainder, every
Stage 3 instruction, loader, compressed payload/padding and all Z80 bytes.
The build additionally compares the actual ROM-decompressed driver to the
complete assembler object and checks all new routine/RAM symbols.

Each new stock hook is first compared in full, then restored to its exact stock
bytes. Only the already-audited Stage 4 ranges are normalized for the remaining
stock digest. No broad new ignored range is introduced. Everything after the
appended code must be zero padding. Unit tests mutate hooks, callback, router,
backend, payload, padding and protected stock bytes while repairing checksums;
those mutations are rejected.

## Local validation

Run the repository checks and all build/CPU commands documented in the README.
The local evidence logs and complete review diff are under ignored `build/`.
The complete suite was rerun for the documentation/evidence finalization pass.
Fresh commands, exit codes and logs are under `build/stage5-finalization/`.
Hardware observations are recorded separately below and are not inferred from
these local results. No implementation or test file changed during this pass.

| Check | Result |
| --- | --- |
| Ruff / Markdownlint / compileall / manifest / git diff --check | Pass |
| Unit suite | 88 pass |
| Modern bootstrap / stock build / prepare / prepared build | Pass |
| Modern backend, native/CCR and wrapper suite | 7 pass |
| Stage 4 loader/handoff suite | 14 pass |
| Actual assembly with fixBugs=1 | Rejected by the earlier input-layout assertion |
| Stage 5 live two-CPU suite | 15 pass |
| Clean legacy identity | Exact size/checksum/SHA-256 above |
| Legacy hybrid CPU suite | 9 pass |
| Legacy game-mode CPU suite | 8 pass |

## MiSTer hardware results

**Required Stage 5 hardware gate: PASSED.** The following records the
maintainer's actual MiSTer FPGA results supplied for this finalization pass.
It is hardware evidence, separate from the source/binary audits and compiled CPU
traces above. The referenced Stage 5 ROM is the `BE41` build with SHA-256
`bd12138cd478596e4d294a06f573a98a6d37747dfe58d726ca62cf50dc3a8c44`;
the local rebuild independently verifies that identity. The test date, core
version, region and pack hash were not supplied and are not inferred.

| Hardware check | Reported result | Status |
| --- | --- | --- |
| Boot | Game boots normally | Passed |
| SEGA PCM | Sounds normal | Passed |
| Title/menu | Native music, BGM and SFX work normally | Passed |
| Initial EHZ handoff | Clean transition to Addryu track03; no native EHZ BGM underneath | Passed |
| SFX over MD+ | All effects listed below work; none lost or corrupted | Passed |
| EHZ music | Loops correctly | Passed |
| EHZ progression | Act 1 completion and Act 2 work correctly | Passed |
| CPZ | Routed MD+ playback works | Passed |
| Death Egg | Routed MD+ playback works | Passed |
| Special Stage | Entry, BGM and SFX work; played through to completion | Passed |
| Pause/resume | Both work during active MD+; correct playback, no audible glitch | Passed |
| Speed Shoes | Physics speed up; MD+ music stays at normal speed | Passed |
| Extra life | Native 1-up audio/MD+ interaction works as intended; no audible problem | Passed |
| Invincibility | MD+ level -> native invincibility -> MD+ level | Passed |
| Boss, EHZ and CPZ | MD+ level -> native boss -> MD+ level | Passed |
| Drowning | MD+ level -> native drowning -> MD+ level | Passed |
| Warm reset | Works correctly while MD+ is active | Passed |
| Level select | Cheat works correctly | Passed |
| Late-game/ending | Full sequence below works correctly | Passed |

Ordinary effects confirmed over MD+ were jump, rings, spin dash, monitor, badnik
hit, ring loss, checkpoint and checkpoint/special-stage entry. No lost or
corrupted ordinary SFX were observed.

The initial native-to-EHZ handoff had no observed pop, click, abnormal silence,
delay, stutter or lock-up. Across all reported tests, there were no observed
pops, clicks, abnormal silences, unexplained delays, stutters, lost SFX, native
level BGM overlapping underneath MD+, or lock-ups.

The hardware-confirmed late-game sequence was:

```text
Death Egg MD+
-> native Robotnik BGM for the Metal Sonic fight
-> Death Egg MD+
-> native Final Boss BGM
-> ending cinematic
```

All transitions worked correctly. The invincibility, boss and drowning round
trips were also confirmed on hardware; boss transitions were tested in both EHZ
and CPZ. Speed Shoes confirms the intended normal-speed MD+ policy without fast
MD+ tracks.

Source/static routing evidence maps `MusID_SpecStage` (`$92`) to MD+ track29.
Hardware testing confirmed that checkpoint/Special Stage entry worked, the
Special Stage BGM and SFX sounded correct, and the stage was played through to
completion successfully. The hardware test did not independently instrument or
prove audio ownership/source identity. No native-audio attribution is made for
that observation; the track29 routing policy is unchanged.

The report confirms extra-life behavior generally; it does not individually
identify all six trigger paths or extra life during pause/handoff. Likewise,
pause specifically during an F7 handoff, cold reset while MD+ was already active,
and separate PAL/NTSC runs were not separately reported. Their existing source
and CPU evidence must not be presented as additional hardware observations.
These coverage limits do not reopen the maintainer-confirmed required gate.

## Optional missing-WAV robustness test

**Not run; not hardware-validated; not a Stage 5 merge blocker.** No missing-WAV
outcome is inferred from the successful normal-pack tests. Fixed ROM routing
and the absence of a file-existence probe remain source/CPU evidence.

For a future optional check, use a disposable copy of the pack and move
`track03.wav` out of it, keeping the cue entry and all other tracks unchanged.
Check for silence on the missing routed music, continued native SFX and no
file-dependent native fallback. Restore the file afterward. If the core refuses
to load the incomplete pack, record that outcome rather than claiming a ROM
fallback test passed.

## Hardware retest procedure and evidence limits

The required test has passed. This procedure remains available for reproducing
it after future changes; it does not introduce another outstanding merge gate.

1. Build `build/sonic2-modern-mdplus.md` with `make build-modern`. Confirm its
   SHA-256 matches the table above. Keep the production pack as the baseline.
2. Make a separate local test copy of the existing working Addryu pack. Replace
   only that copy's ROM with `build/sonic2-modern-mdplus.md`, naming it exactly
   like the ROM already in that copy (normally
   `Sonic 2 - Addryu Mega-CD Remix MD+.md`). Keep its matching `.cue` basename and
   every track filename/loop entry unchanged. Old package checksum metadata no
   longer describes the replaced ROM; record the test hash separately. This is
   manual hardware-test setup, not a modern packaging command.
3. Copy that test directory to MiSTer's usual MD+ location and load its ROM with
   the same core/settings used for the working production pack. Record the date,
   core version, region and pack identity when available.
4. Repeat the reported cases above, checking transitions and sustained playback,
   including warm reset during MD+, the level-select cheat and Death Egg/ending.
   Record any additional stress cases separately from the established results.

Emulator limitations remain: it grants bus requests immediately, records MD+
stores without SD/FPGA playback, and stops Z80 DAC execution at the sample
main-loop handoff. ACK-service transactions extend the VInt bus hold; the duck
service runs after stock dispatch without needing that bus. The supplied MiSTer
observations establish successful playback, mixing and progression for the
reported cases, not measured bus-cycle margins or every possible timing case.
Missing-file behavior remains untested on hardware.
