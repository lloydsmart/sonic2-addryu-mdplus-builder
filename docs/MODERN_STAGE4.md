# Modern Stage 4 handoff audit

Stage 4 ports the production native-music-only stop and acknowledgement to pinned
modern `sonicretro/s2disasm`. It is an inert migration stage. Ordinary gameplay
still uses native music, and the sixteen Addryu routes and five MD+ controls
remain disconnected. Stage 5 will add ownership and connect live routing.

Stage 4 currently has CPU/emulator validation but no MiSTer hardware validation.
A short MiSTer native-audio smoke test should be completed before Stage 5
activates live MD+ routing, covering boot, SEGA/title, menu, EHZ, rings/SFX,
pause/resume and basic progression. It checks native driver loading/playback;
there is deliberately no gameplay F7 test hook.

## Audited sources

The branch is `migration/04-modern-z80-handoff`, based on
`migration/current-s2disasm`. The modern pin remains
`380f37a731bfc720bb0371a35a593184a7ec5e43`.

Every mutated upstream file has a whole-file SHA-256 check and exact single
replacement counts. Local dependency edits and old prepared output are excluded.

| Input | Pinned SHA-256 |
| --- | --- |
| `s2.asm` | `448630bb22c08b5281d143438296e5b9045f6539699ec3724147a7f945c938b9` |
| `s2.sounddriver.asm` | `ff34692c633f96d50073c24f6ebb72df5c739892c31be6b19b2ae604e76232c7` |
| `s2.constants.asm` | `8de5f4a4e6abc56ea2504afe2f4d58cc8a7a3bfa80e3f3c9f1372231a3ca16cd` |

`s2.asm` receives the PlayMusic hook, late Forge include, input trampoline and
loader-helper trampoline. The Z80 source receives dispatch after ready, the F7
check before pause, ACK allocation, explicit volume-table alignment and the Z80
include. The constants source splits the unused RAM reservation around one byte.

Forge owns `hybrid_modern.asm`, `hybrid_modern_handoff.asm`,
`hybrid_modern_z80.asm` and `modern_build.lua`. The Lua wrapper copies `s2.p`
and `s2.h` to `forge-s2.p` and `forge-s2.h` before upstream deletes them. It
preserves upstream cleanup and failure detection; no upstream build script is
mutated. Modern AS emits two contiguous driver object records, both included
in the comparison, excluding the earlier console-startup Z80 stub.

The legacy production transformer, `_clone_at`, `_git_output`, dependency pins,
track manifest and CI workflow are unchanged. Existing commands retain their
roles; `build-modern` now contains this inert Stage 4 infrastructure.

## Architecture and compiled addresses

The live path remains `$00135E → $100000`, with second-mailbox code at `$10000C`
and the native return boundary at `$100012`. All 18 native implementation bytes
and all 676 following Stage 3 backend bytes remain unchanged.

| 68000 routine | Address | Purpose |
| --- | --- | --- |
| `ForgeModernBeginHandoff` | `$1002B6` | Set state 1 and attempt enqueue |
| `ForgeModernQueueStop` | `$1002BC` | Use free Music0, otherwise free Music1; defer if full |
| `ForgeModernCheckReady` | `$1002E8` | Consume ACK, discard stale ACK, retry false-ready |
| `ForgeModernInput` | `$10032A` | Stock mailbox/pause transfer plus handoff service and three SFX slots |
| `ForgeModernSaxGetByte` | `$10039C` | Bounded compressed-byte reader |
| `ForgeModernHandoffEnd` | `$1003A8` | End of appended code |

`$001084–$0010DF` retains the input routine's 92-byte footprint: a six-byte jump
and 86 zero bytes. `$0EC0DE–$0EC0E7` retains the loader helper's ten-byte footprint:
a six-byte jump and two NOPs. Every other 68000 code address is unchanged.

| Z80 label | Address |
| --- | --- |
| `zVInt` | `$0038` |
| `zPlaySoundByIndex` | `$06BA` |
| `zCommandIndex` | `$06E4` |
| `zHybridStopMusic` | `$1317` |
| `zHybridStopFM` | `$133D` |
| `zHybridFMNext` | `$1352` |
| `zHybridStopPSG` | `$135C` |
| `zHybridCodeEnd` | `$137A` |
| `zHybridAck` | `$1FF4` |

The 68000 state byte is `$FFF113`: `0 = idle`, `1 = requested/waiting to enqueue`,
`2 = delivered/waiting for ACK`. No other ownership or routing state is added.
Begin/queue operations require interrupts masked, matching production's caller
contract. They preserve registers and use scratch CCR. Input clobbers the same
`d0/d1/a0/a1` as stock. Input/ACK service requires the existing VInt Z80 bus lock;
it does not acquire or reset the Z80 itself.

## Stop and acknowledgement

`MusID_ForgeStop = $F7` and `ForgeAckValue = $A5` each have one shared symbolic
definition, used by both CPUs. F6 remains invalid. F8–FD retain all six stock
command meanings and dispatch targets. Script-coordinate F6/F7 still point to
their original handlers in their separate namespace.

The dispatcher first stores public ready `$80`, then checks F7 exactly once.
The private stop clears music pause, fade-in/out, 1-up and Speed Shoes state,
DAC playback and residual DAC enable, and all music active flags. It mutes FM
L/R unless SFX overrides the track, and stops initialized PSG tracks through
the existing override-aware note-off routine. SFX track RAM, queued requests
and priority are preserved. ACK is written only after these operations.

The early VInt F7 check runs before ordinary pause dispatch, allowing a paused
native song to stop. Non-F7 pause/resume retains stock behavior. After ACK, the
public queue remains ready and ordinary SFX can continue without 68000 service.

The full CPU trace is `(state, Music0, Music1, QueueToPlay, ACK)`:

```text
initial       (0, 00, 00, 80, 00)
begin         (1, F7, 00, 80, 00)
68K delivery  (2, 00, 00, F7, 00)
Z80 complete  (2, 00, 00, 80, A5)
68K service   (0, 00, 00, 80, 00)
```

Delivery clears stale ACK before setting state 2 and storing F7 to the Z80
queue. If state 2 sees `$80` without ACK, it retries F7. Ready alone never
completes the handoff. ACK outside state 2 is cleared without granting completion;
a state-1 request still proceeds. Occupied Music0 and Music1 are preserved,
with one queued F7 at most. No handoff routine starts MD+.

The narrowly scoped SFX correction copies exactly three bytes. The stock fourth
iteration consumed Music1 and could overwrite the low byte of Z80 `VoiceTblPtr`.
Tests cover all three SFX slots, occupied destination slots, a busy public queue,
preserved Music1, and an unchanged two-byte voice pointer. Global `fixBugs`
remains zero; this is a prerequisite for reliable two-mailbox handoff.

## RAM boundaries and reset

The stock modern compiled listing independently proves `zTracksSaveEnd=$1FF4`.
The prepared build asserts that exact value and allocates ACK immediately after
it. All ranges below are half-open.

| Range | Use |
| --- | --- |
| `$0000–$137A` | Loaded Z80 code/data |
| `$137A–$1380` | Six bytes of remaining code headroom |
| `$1380–$1B40` | Music decompression buffer |
| `$1B40–$1B80` | Reserved stack headroom; stack grows downward from `$1B80` |
| `$1B80–$1B98` | Driver variables/queues |
| `$1B98–$1D3C` | Music tracks |
| `$1D3C–$1E38` | SFX tracks |
| `$1E38–$1FF4` | 1-up saved variables/music tracks |
| `$1FF4–$1FF5` | ACK |

Driver clear/init ends at music/SFX boundaries; 1-up save/restore copies exactly
`$1BC` bytes. CPU tests show ACK survives both clear/init routines and an actual
native 1-up save/restore over 211 VInts. The frame harness stops at DAC main-loop
entry where a VInt deliberately replaces its return address; it does not model
DAC sample timing.

With `fixBugs=0`, `$FFF100–$FFF600` is an unused reservation. The transformer
splits it into `$13` bytes, the handoff byte, then `$4EC` bytes; following RAM
addresses are unchanged. Assertions check the surrounding palette and Game_Mode
boundaries and reject `fixBugs=1`. The unchanged `GameInit` clear loop covers
`$FF0000–$FFFE00` on both cold and warm boots. Executing that loop with stale
states 1, 2 and FF clears the handoff before input service.

## Loading and ROM layout

The corrected reader decrements/checks remaining length before reading. It
processes the final compressed byte and exits only on the next read request,
without reading beyond declared input. Its unique compiled instruction sequence
is `5347 6504 101E 4E75 584F 4E75`.

Both synthetic final-literal and final-match payloads pass through the actual
compiled modern loader. Read hooks prove every input byte is read once, with no
read beyond the declared end. The whole real driver also passes through that
loader and matches every byte in the complete assembler object segment.

| Measurement | Value |
| --- | --- |
| Compressed start | `$0EC0E8` |
| Compressed size | 4,009 bytes (`$FA9`) |
| Compressed end, exclusive | `$0ED091` |
| Upstream estimated end | `$0ED04C` |
| Fixed DAC start / growth-region limit | `$0ED100` |
| Remaining compression padding | 111 bytes |
| Assembled/decompressed/actually loaded size | 4,986 bytes (`$137A`) |
| Loaded driver SHA-256 | `9f997cc7217dda878297f7359f3314c7876aeb29e8705d63bd4b6db1513db24f` |

The payload exceeds upstream's estimated compressed allocation by 69 bytes,
using its explicit growth padding before DAC data. No DAC, music-bank or later
ROM addresses move. Inside the decompressed driver, the added dispatch changes
Z80 code addresses and requires two alignment bytes before `zVolTLMaskTbl`.
This alignment preserves upstream's one-byte table-offset constraint.

Verification checks the entire fixed `$0EC0E8–$0ED100` driver/padding region,
the two trampolines, compressed length, exact handoff bytes and exact Stage 3
backend. It reconstructs the original PlayMusic/header, zeroes only those
independently audited changed regions, and compares the SHA-256 of every
remaining stock byte against the value derived from verified REV01. Thus the
extended audit covers every ROM byte; signature counting alone is insufficient.
The original full stock MD5/SHA-256 checks remain unchanged.

## ROM identities and transaction counts

| ROM | Size | Header checksum |
| --- | ---: | --- |
| Prepared Stage 4 | 2,097,152 | `6119` |
| Stock modern REV01 | 1,048,576 | `D951` |
| Legacy production | 2,129,922 | `2911` |

Prepared Stage 4:

- MD5: `22e9005bb8c5242b2e36c8303a9c21ba`
- SHA-256: `97e11fe11b32814ec8ba373e1eb1aa6d3aff3c31fe73eec6e85cdb6edfb75887`

Stock modern REV01:

- MD5: `9feeb724052c39982d432a7851c98d3e`
- SHA-256: `193bc4064ce0daf27ea9e908ed246d87ec576cc294833badebb590b6ad8e8f6b`

Legacy production SHA-256:
`315c69fb84dbca2a31ceffe3face70b4138317feed53feb7e23c6a5ab009205e`.

Stage 3 still has exactly 21 adjacent isolated transactions: 16 track plays and
5 controls, 21 overlay opens, 21 command writes, 21 closes and 42 overlay-address
signatures. The 694-byte native/backend region SHA-256 remains
`a42fecc8e83354d76638f42de8810bbfaa678d54c77b8ae1051a261af26103f1`.

The retained exhaustive PlayMusic suite checks all 256 request bytes, all 32 CCR
inputs, both mailbox paths and all 255 nonempty Music0 values. Every invocation
remains stock-equivalent, with zero MD+ writes and no handoff-state writes.
A caller deliberately passing F7 still gets stock's raw byte-copy behavior;
PlayMusic never invents F7. Ordinary gameplay has no private request call site.

The handoff suite records zero MD+ overlay or command writes throughout the
internal flow, contention, retries, stale ACK handling and paused/unpaused
completion. Delaying 68000 ACK observation for 120 VInts in each pause case
preserves ACK and consumes SFX every frame without queue starvation.

## Validation and limits

Local validation passed:

| Check | Result |
| --- | --- |
| Ruff, Markdownlint, compileall, manifest, diff whitespace | Pass |
| Unit tests | 84 pass |
| Modern bootstrap, stock build, preparation, prepared build | Pass |
| Retained Stage 3 modern CPU suite | 5 pass |
| Stage 4 handoff/loader CPU suite | 14 pass |
| Clean legacy ROM identity | Exact required size/checksum/SHA-256 |
| Legacy hybrid CPU suite | 9 pass |
| Legacy game-mode CPU suite | 8 pass |

Run the normal repository validation, both real modern builds, and both modern
CPU suites listed in the README. The normal unit suite enforces source hashes,
replacement counts, minimal state, dispatch ordering, SFX slot count, object
record handling and rejection of tampered binary ranges. The existing CI real
stock/prepared build executes the full byte audits and assembler comparison.
Unicorn/Z80 CPU suites remain manual under the existing project convention.

Run the clean Linux legacy regression and its nine hybrid and eight game-mode
binary tests against the fresh checkout. Per-run results and review diff are
kept under ignored `build/`; generated ROMs and audio are never review assets.

The Z80 code has only six bytes of headroom. Future additions must preserve the
music buffer and stack, and re-audit compression padding. The internal routines
assume masked interrupts for mailbox changes and an already-held Z80 bus for
ACK service. Their added execution time is bounded, but these CPU tests do not
model console bus timing, audible mixing, or MiSTer playback. The native-audio
hardware smoke test should be completed before Stage 5 activates live MD+
routing; it is not evidence for the still-disconnected F7 handoff.
