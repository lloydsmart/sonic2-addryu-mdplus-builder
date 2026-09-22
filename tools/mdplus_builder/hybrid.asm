; Fixed hybrid music policy. Generated track dispatch is inserted by source.py.
MDP_CTRL        = $0003F7FA
MDP_CMD         = $0003F7FE
MusID_HybridStop = $F7 ; unused command, through the existing music queue
HybridAckValue   = $A5 ; separate completion latch; never a queue command
v_MSU_counter   equ $FFF100
v_MSU_1upFlag   equ $FFF108
v_MusicBackend  equ $FFF111 ; 0 native, 1 MD+ (including pending handoff)
v_MDPlusPending equ $FFF112 ; requested Sonic music ID, zero when consumed
v_MDPlusHandoff equ $FFF113 ; 0 idle, 1 stop queued, 2 awaiting ready
v_MDPlusPaused  equ $FFF114 ; explicit pause only; fades cannot be resumed
v_MDPlusActive  equ $FFF115 ; playing/paused track, cleared by stop/fade/reset

PlayMusic:
PlayMSU:
    move.w  sr,-(sp)
    ori.w   #$0700,sr
    bsr.w   HybridRoute
    move.w  (sp)+,sr
    tst.b   d0 ; stock mailbox MOVE flags; all data/address registers preserved
    rts

HybridRoute:
    cmp.b   #MusID_ExtraLife,d0
    beq.w   HybridExtraLife
    cmp.b   #MusID_FadeOut,d0
    beq.w   HybridFade
    cmp.b   #MusID_Stop,d0
    beq.w   HybridStop
    cmp.b   #MusID_Pause,d0
    beq.w   HybridPause
    cmp.b   #MusID_Unpause,d0
    beq.w   HybridResume
    cmp.b   #MusID_SpeedUp,d0
    beq.w   HybridSpeed
    cmp.b   #MusID_SlowDown,d0
    beq.w   HybridSpeed
; @ROUTE@
    cmp.b   #MusID__First,d0
    blo.w   NativePlayMusic
    cmp.b   #MusID__End,d0
    bhs.w   NativePlayMusic ; SFX/other commands do not acquire music ownership
    tst.b   (v_MusicBackend).l
    beq.w   NativePlayMusic
    bsr.w   MDPlusImmediate
    clr.b   (v_MusicBackend).l
    clr.b   (v_MDPlusActive).l
    clr.b   (v_MDPlusPending).l
    clr.b   (v_MDPlusHandoff).l
    clr.b   (v_MDPlusPaused).l
    clr.b   (v_MSU_1upFlag).l
    ; Cancel an undelivered handoff, without discarding the next native cue.
    cmpi.b  #MusID_HybridStop,(Music_to_play).w
    bne.s   HybridCancelSecond
    clr.b   (Music_to_play).w
HybridCancelSecond:
    cmpi.b  #MusID_HybridStop,(Music_to_play_2).w
    bne.w   NativePlayMusic
    clr.b   (Music_to_play_2).w
    bra.w   NativePlayMusic

NativePlayMusic:
    tst.b   (Music_to_play).w
    bne.s   NativePlayMusicSecond
    move.b  d0,(Music_to_play).w
    rts
NativePlayMusicSecond:
    move.b  d0,(Music_to_play_2).w
    rts

HybridRequest:
    move.b  d0,(v_MDPlusPending).l
    clr.b   (v_MDPlusPaused).l
    tst.b   (v_MusicBackend).l
    bne.s   HybridRequestOwned
    move.b  #1,(v_MusicBackend).l
    move.b  #1,(v_MDPlusHandoff).l
    ; Supersede queued BGM/control requests, preserving ordinary queued SFX.
    movem.l d0/a0,-(sp)
    lea     (Music_to_play).w,a0
    bsr.w   HybridDiscardMusic
    lea     (Music_to_play_2).w,a0
    bsr.w   HybridDiscardMusic
    bsr.w   HybridQueueStop
    movem.l (sp)+,d0/a0
    rts
HybridRequestOwned:
    tst.b   (v_MDPlusHandoff).l
    bne.w   HybridReturn
    bra.w   HybridPlayPending

HybridDiscardMusic:
    cmpi.b  #MusID__First,(a0)
    blo.w   HybridReturn
    cmpi.b  #MusID__End,(a0)
    blo.s   HybridDiscard
    cmpi.b  #MusID_FadeOut,(a0)
    blo.w   HybridReturn
    cmpi.b  #SndID_SegaSound,(a0)
    beq.w   HybridReturn
HybridDiscard:
    clr.b   (a0)
HybridReturn:
    rts

; Enqueue in 68K RAM. Only sndDriverInput accesses Z80 RAM, under its bus lock.
HybridQueueStop:
    cmpi.b  #MusID_HybridStop,(Music_to_play).w
    beq.w   HybridReturn
    cmpi.b  #MusID_HybridStop,(Music_to_play_2).w
    beq.w   HybridReturn
    tst.b   (Music_to_play).w
    beq.s   HybridQueueStopFree
    tst.b   (Music_to_play_2).w
    bne.w   HybridReturn ; defer instead of replacing a queued SFX
HybridQueueStopFree:
    move.l  d0,-(sp)
    move.b  #MusID_HybridStop,d0
    bsr.w   NativePlayMusic
    move.l  (sp)+,d0
    rts
HybridCheckReady:
    cmpi.b  #HybridAckValue,(Z80_RAM+zHybridAck).l
    bne.s   HybridCheckRetry
    clr.b   (Z80_RAM+zHybridAck).l
    cmpi.b  #2,(v_MDPlusHandoff).l
    bne.w   HybridReturn ; discard completion of a cancelled handoff
    clr.b   (v_MDPlusHandoff).l
    tst.b   (v_MusicBackend).l
    beq.w   HybridReturn
    tst.b   (v_MDPlusPaused).l
    bne.w   HybridReturn
    bra.w   HybridPlayPending
HybridCheckRetry:
    cmpi.b  #1,(v_MDPlusHandoff).l
    beq.w   HybridQueueStop
    cmpi.b  #2,(v_MDPlusHandoff).l
    bne.w   HybridReturn
    cmpi.b  #$80,(Z80_RAM+zAbsVar.QueueToPlay).l
    bne.w   HybridReturn
    ; Stock song init/1-up restore can overwrite a request after early-ready.
    ; A plain $80 is NOT proof of silence: retry until the separate ACK arrives.
    bra.w   HybridQueueStop
HybridPlayPending:
    tst.b   (v_MDPlusPending).l
    beq.w   HybridReturn
    move.l  d0,-(sp)
    move.b  (v_MDPlusPending).l,d0
    clr.b   (v_MDPlusPending).l
    bsr.w   MDPlusVolumeNormal
    bsr.w   HybridDispatch
    move.b  #1,(v_MDPlusActive).l
    move.l  (sp)+,d0
    rts

HybridFade:
    tst.b   (v_MusicBackend).l
    beq.w   NativePlayMusic
    clr.b   (v_MDPlusActive).l
    clr.b   (v_MDPlusPending).l
    clr.b   (v_MDPlusPaused).l
    clr.b   (v_MSU_1upFlag).l
    bra.w   MDPlusFade
HybridStop:
    tst.b   (v_MusicBackend).l
    beq.w   NativePlayMusic
    clr.b   (v_MDPlusActive).l
    clr.b   (v_MDPlusPending).l
    clr.b   (v_MDPlusPaused).l
    clr.b   (v_MSU_1upFlag).l
    ; Retain silent MD+ ownership: unpause must not touch the old native BGM.
    bra.w   MDPlusImmediate
HybridPause:
    tst.b   (v_MusicBackend).l
    beq.w   NativePlayMusic
    tst.b   (v_MDPlusPending).l
    bne.s   HybridPauseActive
    tst.b   (v_MDPlusActive).l
    beq.w   HybridReturn
HybridPauseActive:
    move.b  #1,(v_MDPlusPaused).l
    bra.w   MDPlusImmediate
HybridResume:
    tst.b   (v_MusicBackend).l
    beq.w   NativePlayMusic
    tst.b   (v_MDPlusPaused).l
    beq.w   HybridReturn
    clr.b   (v_MDPlusPaused).l
    tst.b   (v_MDPlusHandoff).l
    bne.w   HybridReturn
    tst.b   (v_MDPlusPending).l
    bne.w   HybridPlayPending
    bra.w   MDPlusResume
HybridSpeed:
    tst.b   (v_MusicBackend).l
    beq.w   NativePlayMusic
    rts ; speed shoes alter physics; Addryu audio continues at normal speed

HybridExtraLife:
    bsr.w   msuExtraLife
    bra.w   NativePlayMusic
msuExtraLife:
    tst.b   (v_MusicBackend).l
    beq.s   HybridExtraReturn
    clr.l   (v_MSU_counter).l
    move.b  #1,(v_MSU_1upFlag).l
HybridExtraReturn:
    rts
Vint_MSUMD:
    tst.b   (v_MusicBackend).l
    beq.s   HybridExtraReturn
    tst.b   (v_MSU_1upFlag).l
    beq.s   HybridExtraReturn
    tst.b   (v_MDPlusPaused).l
    bne.s   HybridExtraReturn
    tst.b   (v_MDPlusHandoff).l
    bne.s   HybridExtraReturn
    bsr.w   MDPlusVolumeLow
    addq.b  #1,(v_MSU_counter+3).l
    cmpi.b  #$FF,(v_MSU_counter+3).l
    bne.s   HybridExtraReturn
    clr.b   (v_MSU_1upFlag).l
    clr.l   (v_MSU_counter).l
    bra.w   MDPlusVolumeNormal

; Wrappers preserve d0 at ArcadeTV's former direct-call sites.
HybridFadeRequest:
    move.l  d0,-(sp)
    move.b  #MusID_FadeOut,d0
    bsr.w   PlayMusic
    move.l  (sp)+,d0
    rts
HybridStopRequest:
    move.l  d0,-(sp)
    move.b  #MusID_Stop,d0
    bsr.w   PlayMusic
    move.l  (sp)+,d0
    rts
HybridReset:
    bsr.w   MDPlusImmediate ; called AFTER startup checksum and RAM clear
    clr.b   (Music_to_play).w
    clr.b   (Music_to_play_2).w
    clr.b   (v_MusicBackend).l
    clr.b   (v_MDPlusActive).l
    clr.b   (v_MDPlusPending).l
    clr.b   (v_MDPlusHandoff).l
    clr.b   (v_MDPlusPaused).l
    clr.b   (v_MSU_1upFlag).l
    clr.l   (v_MSU_counter).l
    rts

; @COMMANDS@
HybridDispatch:
; @DISPATCH@
    rts
; @TRACKS@
