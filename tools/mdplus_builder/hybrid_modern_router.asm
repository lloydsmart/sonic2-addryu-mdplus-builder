; Live 68000 ownership/control layer. The Stage 4 Z80 image is frozen.
; Public music entry preserves every data/address register and the caller's
; interrupt mask, and returns stock MOVE.B d0 flags (including preserved X).
ForgeModernPlayMusic:
    move.w  sr,-(sp)
    ori.w   #$0700,sr
    bsr.w   ForgeModernRoute
    move.w  (sp)+,sr
    tst.b   d0
    rts

ForgeModernRoute:
    cmp.b   #MusID_ExtraLife,d0
    beq.w   ForgeModernExtraLife
    cmp.b   #MusID_FadeOut,d0
    beq.w   ForgeModernRouteFade
    cmp.b   #MusID_Stop,d0
    beq.w   ForgeModernRouteStop
    cmp.b   #MusID_Pause,d0
    beq.w   ForgeModernPause
    cmp.b   #MusID_Unpause,d0
    beq.w   ForgeModernUnpause
    cmp.b   #MusID_SpeedUp,d0
    beq.w   ForgeModernSpeed
    cmp.b   #MusID_SlowDown,d0
    beq.w   ForgeModernSpeed
; @ROUTE@
    cmp.b   #MusID__First,d0
    blo.w   ForgeModernNativeMusic
    cmp.b   #MusID__End,d0
    bhs.w   ForgeModernNativeMusic
    tst.b   (ForgeModernOwner).w
    beq.w   ForgeModernNativeMusic
    bsr.w   ForgeModernImmediate
    clr.b   (ForgeModernOwner).w
    bsr.w   ForgeModernClearTrack
    ; Cancel undelivered F7 only. A delivered F7 finishes under the Z80;
    ; its ACK is discarded in state 0 and the original native request waits.
    cmpi.b  #MusID_ForgeStop,(Sound_Queue.Music0).w
    bne.s   .second
    clr.b   (Sound_Queue.Music0).w
.second:
    cmpi.b  #MusID_ForgeStop,(Sound_Queue.Music1).w
    bne.s   .done
    clr.b   (Sound_Queue.Music1).w
.done:
    clr.b   (ForgeModernHandoff).w
    bra.w   ForgeModernNativeMusic

ForgeModernRequest:
    move.b  d0,(ForgeModernPending).w
    clr.b   (ForgeModernPaused).w
    tst.b   (ForgeModernOwner).w
    bne.s   .owned
    move.b  #1,(ForgeModernOwner).w
    ; Supersede queued BGM/controls so none can start after the private stop.
    ; Preserve queued ordinary SFX and the native SEGA PCM request.
    movem.l a0,-(sp)
    lea     (Sound_Queue.Music0).w,a0
    bsr.w   ForgeModernDiscardMusic
    lea     (Sound_Queue.Music1).w,a0
    bsr.w   ForgeModernDiscardMusic
    movem.l (sp)+,a0
    bra.w   ForgeModernBeginHandoff
.owned:
    tst.b   (ForgeModernHandoff).w
    bne.s   ForgeModernReturn
    bra.w   ForgeModernPlayPending

ForgeModernDiscardMusic:
    cmpi.b  #MusID__First,(a0)
    blo.s   ForgeModernReturn
    cmpi.b  #MusID__End,(a0)
    blo.s   .discard
    cmpi.b  #MusID_FadeOut,(a0)
    blo.s   ForgeModernReturn
    cmpi.b  #SndID_SegaSound,(a0)
    beq.s   ForgeModernReturn
.discard:
    clr.b   (a0)
ForgeModernReturn:
    rts

; Called only for state 2 + A5, with the stock VInt bus lock held.
; Stage 4 already cleared ACK. No QueueToPlay value grants completion.
ForgeModernComplete:
    clr.b   (ForgeModernHandoff).w
    tst.b   (ForgeModernOwner).w
    beq.s   ForgeModernReturn
    tst.b   (ForgeModernPaused).w
    bne.s   ForgeModernReturn
ForgeModernPlayPending:
    tst.b   (ForgeModernPending).w
    beq.s   ForgeModernReturn
    move.l  d0,-(sp)
    move.b  (ForgeModernPending).w,d0
    clr.b   (ForgeModernPending).w
    bsr.w   ForgeModernVolumeNormal
    bsr.w   ForgeModernDispatch
    move.b  #1,(ForgeModernActive).w
    move.l  (sp)+,d0
    rts

ForgeModernClearTrack:
    clr.b   (ForgeModernActive).w
    clr.b   (ForgeModernPending).w
    clr.b   (ForgeModernPaused).w
    clr.b   (ForgeModernDuck).w
    clr.l   (ForgeModernCounter).w
    rts
ForgeModernRouteFade:
    tst.b   (ForgeModernOwner).w
    beq.w   ForgeModernNativeMusic
    bsr.w   ForgeModernClearTrack
    bra.w   ForgeModernFade
ForgeModernRouteStop:
    tst.b   (ForgeModernOwner).w
    beq.w   ForgeModernNativeMusic
    bsr.w   ForgeModernClearTrack
    bra.w   ForgeModernImmediate
ForgeModernPause:
    tst.b   (ForgeModernOwner).w
    beq.w   ForgeModernNativeMusic
    tst.b   (ForgeModernPending).w
    bne.s   .pause
    tst.b   (ForgeModernActive).w
    beq.w   ForgeModernReturn
.pause:
    move.b  #1,(ForgeModernPaused).w
    bra.w   ForgeModernImmediate
ForgeModernUnpause:
    tst.b   (ForgeModernOwner).w
    beq.w   ForgeModernNativeMusic
    tst.b   (ForgeModernPaused).w
    beq.w   ForgeModernReturn
    clr.b   (ForgeModernPaused).w
    tst.b   (ForgeModernHandoff).w
    bne.w   ForgeModernReturn
    tst.b   (ForgeModernPending).w
    bne.w   ForgeModernPlayPending
    bra.w   ForgeModernResume
ForgeModernSpeed:
    tst.b   (ForgeModernOwner).w
    beq.w   ForgeModernNativeMusic
    rts

ForgeModernExtraLife:
    bsr.w   ForgeModernDuckStart
    bra.w   ForgeModernNativeMusic
ForgeModernDuckStart:
    tst.b   (ForgeModernOwner).w
    beq.s   .return
    clr.l   (ForgeModernCounter).w
    move.b  #1,(ForgeModernDuck).w
.return:
    rts
ForgeModernDuckService:
    tst.b   (ForgeModernOwner).w
    beq.s   .return
    tst.b   (ForgeModernDuck).w
    beq.s   .return
    tst.b   (ForgeModernPaused).w
    bne.s   .return
    tst.b   (ForgeModernHandoff).w
    bne.s   .return
    bsr.w   ForgeModernVolumeLow
    addq.b  #1,(ForgeModernCounter+3).w
    cmpi.b  #$FF,(ForgeModernCounter+3).w
    bne.s   .return
    clr.b   (ForgeModernDuck).w
    clr.l   (ForgeModernCounter).w
    bra.w   ForgeModernVolumeNormal
.return:
    rts

ForgeModernPlaySound:
    cmp.b   #MusID__First,d0
    blo.s   .native
    cmp.b   #MusID__End,d0
    blo.w   ForgeModernPlayMusic
    cmp.b   #MusID_FadeOut,d0
    beq.w   ForgeModernPlayMusic
    cmp.b   #MusID_SpeedUp,d0
    bhs.w   ForgeModernPlayMusic ; FB-FF; FA SEGA and F8 stop-SFX stay native
.native:
    move.b  d0,(Sound_Queue.SFX0).w
    rts
ForgeModernPlaySound2:
    cmp.b   #MusID_ExtraLife,d0
    bne.s   .native
    move.w  sr,-(sp)
    ori.w   #$0700,sr
    bsr.w   ForgeModernDuckStart
    move.b  d0,(Sound_Queue.SFX1).w ; retain ring-life's original queue
    move.w  (sp)+,sr
    tst.b   d0
    rts
.native:
    move.b  d0,(Sound_Queue.SFX1).w
    rts

; Six-byte replacements for four ownership-blind immediate mailbox stores.
; MOVEM restores d0 without changing the immediate MOVE.B's CCR contract.
ForgeModernPauseRequest:
    movem.l d0,-(sp)
    move.b  #MusID_Pause,d0
    bsr.w   ForgeModernPlayMusic
    movem.l (sp)+,d0
    rts
ForgeModernUnpauseRequest:
    movem.l d0,-(sp)
    move.b  #MusID_Unpause,d0
    bsr.w   ForgeModernPlayMusic
    movem.l (sp)+,d0
    rts

; VintRet replacement. All upstream dispatch/table bytes stay in place.
; Upstream saved d0-a6 already; restore those and the exception frame exactly.
ForgeModernVintReturn:
    move.w  sr,-(sp)
    ori.w   #$0700,sr
    bsr.w   ForgeModernDuckService
    move.w  (sp)+,sr
    addq.l  #1,(Vint_runcount).w
    movem.l (sp)+,d0-a6
    rte

; GameInit's original two calls, then deterministic reset before JoypadInit.
; Neither this hook nor any MD+ instruction is reachable on checksum failure.
ForgeModernInit:
    jsr     (VDPSetupGame).l
    jsr     (JmpTo_SoundDriverLoad).l
ForgeModernReset:
    move.w  sr,-(sp)
    ori.w   #$0700,sr
    bsr.w   ForgeModernImmediate
    clr.b   (Sound_Queue.Music0).w
    clr.b   (Sound_Queue.Music1).w
    clr.b   (ForgeModernOwner).w
    clr.b   (ForgeModernHandoff).w
    bsr.w   ForgeModernClearTrack
    move.w  (sp)+,sr
    rts
ForgeModernRouterEnd:
    if ForgeModernRouterEnd>$200000
        fatal "Forge router exceeds appended ROM region"
    endif
