; Private BGM-only stop, dispatched through the existing QueueToPlay mailbox.
; The normal dispatcher has already returned QueueToPlay to 80h.
; Completion lives outside all track clear/save/restore ranges.
zHybridStopMusic:
    xor a
    ld (zAbsVar.StopMusic),a
    ld (zPaused),a
    ld (zAbsVar.FadeOutCounter),a
    ld (zAbsVar.FadeInFlag),a
    ld (zAbsVar.1upPlaying),a
    ld (zAbsVar.SpeedUpFlag),a
    ld (zSongDAC.PlaybackControl),a
    ld (zCurDAC),a
    ld (zAbsVar.DACEnabled),a
    ld c,a
    ld a,2Bh
    rst zWriteFMI ; disable residual DAC sample output (SFX use FM/PSG)
    ld ix,zSongFM1
    ld b,MUSIC_FM_TRACK_COUNT
zHybridStopFM:
    res 7,(ix+zTrack.PlaybackControl)
    push bc
    bit 2,(ix+zTrack.PlaybackControl)
    jr nz,zHybridFMNext
    ld a,(ix+zTrack.VoiceControl)
    and 3
    add a,0B4h
    ld c,0
    rst zWriteFMIorII ; mute L/R too, so release envelopes cannot overlap MD+
zHybridFMNext:
    pop bc
    ld de,zTrack.len
    add ix,de
    djnz zHybridStopFM
    ld b,MUSIC_PSG_TRACK_COUNT
zHybridStopPSG:
    res 7,(ix+zTrack.PlaybackControl)
    push bc
    bit 7,(ix+zTrack.VoiceControl)
    call nz,zPSGNoteOff ; skip uninitialised channels; respect SFX override
    pop bc
    ld de,zTrack.len
    add ix,de
    djnz zHybridStopPSG
    ld ix,zAbsVar
    ld a,HybridAckValue
    ld (zHybridAck),a ; acknowledge only after music channels are silent
    ret
