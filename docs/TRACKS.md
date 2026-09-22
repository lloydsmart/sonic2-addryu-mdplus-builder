# Track mapping and loop workflow

MD+ uses CD sectors for loop metadata: 75 sectors per second and 588 stereo
sample frames per sector at 44.1 kHz. Every looping output is therefore trimmed
to exactly `loop_end_sector * 588` frames, and its CUE entry contains
`REM LOOP loop_start_sector`.

The checked-in manifest enables only loops that have been tested end to end:

| Addryu album track | Sonic/MD+ track | Loop start | Loop end | Result |
| --- | ---: | ---: | ---: | --- |
| 01 Emerald Hill Zone | 03 | 292 | 3892 | Seamless on MiSTer |
| 02 Chemical Plant Zone | 05 | 1900 | 5500 | Seamless on MiSTer |

The remaining album-to-game mappings are recorded in `config/tracks.json`, but
remain disabled with `pending` verification. This prevents an unmeasured or
guessed loop from silently entering a release build.

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

ArcadeTV's mapping reserves tracks 33-48 for faster variants. Do not derive a
fast loop by blindly dividing sector numbers by 1.2: the result often falls
between sectors, and time stretching can alter boundary alignment. Add a
separate manifest entry with `"speed": 1.2`, detect its loop boundaries after
conversion, and verify it independently.
