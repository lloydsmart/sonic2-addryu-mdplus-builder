# Track mapping and loop workflow

MD+ uses CD sectors for loop metadata: 75 sectors per second and 588 stereo
sample frames per sector at 44.1 kHz. Every looping output is therefore trimmed
to exactly `loop_end_sector * 588` frames, and its CUE entry contains
`REM LOOP loop_start_sector`.

All 16 Addryu cues are enabled in the default package and marked
`mister-hardware`: every cue and loop has passed end-to-end MiSTer testing.

| Addryu cue | Sonic/MD+ track | Loop start | Loop end | Result |
| --- | ---: | ---: | ---: | --- |
| Emerald Hill Zone | 03 | 292 | 3892 | Verified on MiSTer |
| Chemical Plant Zone | 05 | 1900 | 5500 | Verified on MiSTer |
| Aquatic Ruin Zone | 07 | 828 | 4284 | Verified on MiSTer |
| Casino Night Zone | 08 | 1137 | 5137 | Verified on MiSTer |
| Hill Top Zone | 09 | 1063 | 4557 | Verified on MiSTer |
| Mystic Cave Zone | 10 | 1202 | 4802 | Verified on MiSTer |
| Oil Ocean Zone | 11 | 3541 | 6639 | Verified on MiSTer |
| Metropolis Zone | 12 | 1645 | 5245 | Verified on MiSTer |
| Sky Chase Zone | 13 | 11113 | 14082 | Verified on MiSTer |
| Wing Fortress Zone | 14 | 1874 | 5474 | Verified on MiSTer |
| Death Egg Zone | 15 | 1829 | 5641 | Verified on MiSTer |
| Emerald Hill Zone (2P) | 26 | 1364 | 4160 | Verified on MiSTer |
| Casino Night Zone (2P) | 27 | 1984 | 7573 | Verified on MiSTer |
| Mystic Cave Zone (2P) | 28 | 1592 | 9592 | Verified on MiSTer |
| Special Stage | 29 | 864 | 10642 | Verified on MiSTer |
| Hidden Palace Zone | 31 | 3410 | 7267 | Verified on MiSTer |

Hidden Palace was verified via Sound Test `10`. Sky Chase track 13 loops
correctly and is hardware-verified; its long first-play intro may be trimmed
in a separate future audio-polish change. Its audio and loop points are unchanged.

For future additions, `mister-hardware` is reserved for the final end-to-end
MiSTer pass. Do not enable unmeasured or guessed loops in the default manifest.

## Fixed ROM routing

Exactly these music IDs use Addryu MD+ playback. The manifest controls which
WAVs are prepared, not which backend the ROM selects.

| Sonic music ID | MD+ track |
| --- | ---: |
| `MusID_EHZ` | 03 |
| `MusID_CPZ` | 05 |
| `MusID_ARZ` | 07 |
| `MusID_CNZ` | 08 |
| `MusID_HTZ` | 09 |
| `MusID_MCZ` | 10 |
| `MusID_OOZ` | 11 |
| `MusID_MTZ` | 12 |
| `MusID_SCZ` | 13 |
| `MusID_WFZ` | 14 |
| `MusID_DEZ` | 15 |
| `MusID_SpecStage` | 29 |
| `MusID_EHZ_2P` | 26 |
| `MusID_CNZ_2P` | 27 |
| `MusID_MCZ_2P` | 28 |
| `MusID_HPZ` | 31 |

All other music uses the original Sonic 2 Mega Drive soundtrack, including
bosses, title/options, act clear, invincibility, drowning, Super Sonic, ending,
credits, game over, continue, and the emerald cue. SFX always remain native.
The native 1-up jingle ducks MD+ without changing music ownership.

An absent WAV for any of the sixteen IDs is an incomplete-package error and
never triggers native fallback. Disabled entries remain MD+-owned in the ROM;
the default package includes all sixteen hardware-verified Addryu cues.

## Finding the next loop

First normalize a working copy, then search a bounded region for repeated
sector-aligned boundaries. The conversion command accepts the original source
audio and applies the policy documented in the README: native 44.1 kHz,
16-bit stereo PCM is copied without resampling, while other rates use SoXR at
precision 33 and bit-depth reduction uses explicit high-pass triangular
dithering. Sector alignment is calculated in the final 44.1 kHz domain. For
example:

```sh
python3 -m tools.mdplus_builder convert-audio \
  "inputs/audio/Addryu source.wav" build/candidate.wav

python3 -m tools.mdplus_builder detect-loop build/candidate.wav \
  --start-range 0:15 --end-range 40:90 --top 12
```

The command ranks candidates by normalized waveform error. It does not decide
that a candidate is musically correct. Audition the best candidates, set the
selected start/end sectors in a copy of the manifest, run `prepare-audio`, and
then use `validate-audio --end-sector N`.

Score the selected repeated boundary as an additional mechanical check:

```sh
python3 -m tools.mdplus_builder validate-loop build/candidate.wav \
  --start-sector 292 --end-sector 3892
```

Final verification must be performed in game on MiSTer for multiple loops.
Only after that should `verification` be changed to `mister-hardware` and the
entry enabled in the default manifest.

## Speed-shoes tracks

ArcadeTV reserved tracks 33-48 for faster variants. **This hybrid ROM cannot
request them.** MD+ SpeedUp and SlowDown leave the current track running at
normal speed, without restarting it. Native music retains the original tempo
controls; Sonic's speed-shoes physics are unchanged.

Enabling fast MD+ variants would require a separate ROM-policy change and
independent audio preparation, measured loops, listening tests, and MiSTer
verification. Do not derive fast loops by dividing sector numbers by 1.2.
