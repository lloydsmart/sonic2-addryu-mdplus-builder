; Stage 4 internal API. Gameplay PlayMusic has no path to BeginHandoff.
; All routines preserve registers unless documented; CCR is scratch.
; BeginHandoff/QueueStop require interrupts masked, as in production routing.
; CheckReady and Input require the caller to hold the Z80 bus (stock VInt).
MusID_ForgeStop = $F7
ForgeAckValue = $A5

    if (fixBugs<>0)||(ForgeModernHandoff<>ramaddr($FFFFF113))
        fatal "Forge handoff requires the unused fixBugs=0 RAM byte"
    endif
    if (Underwater_palette+$80<>ramaddr($FFFFF100))||(Game_Mode<>ramaddr($FFFFF600))
        fatal "Forge handoff RAM reservation changed"
    endif
    if (ForgeModernHandoff<RAM_Start)||(ForgeModernHandoff>=CrossResetRAM)
        fatal "GameInit must clear the handoff on cold and warm boots"
    endif

ForgeModernBeginHandoff:
    move.b  #1,(ForgeModernHandoff).w
    ; Fall through to the first enqueue attempt.

ForgeModernQueueStop:
    cmpi.b  #MusID_ForgeStop,(Sound_Queue.Music0).w
    beq.s   .return
    cmpi.b  #MusID_ForgeStop,(Sound_Queue.Music1).w
    beq.s   .return
    tst.b   (Sound_Queue.Music0).w
    bne.s   .second
    move.b  #MusID_ForgeStop,(Sound_Queue.Music0).w
.return:
    rts
.second:
    tst.b   (Sound_Queue.Music1).w
    bne.s   .return
    move.b  #MusID_ForgeStop,(Sound_Queue.Music1).w
    rts

ForgeModernCheckReady:
    cmpi.b  #ForgeAckValue,(Z80_RAM+zHybridAck).l
    bne.s   .retry
    clr.b   (Z80_RAM+zHybridAck).l
    cmpi.b  #2,(ForgeModernHandoff).w
    bne.s   .retry ; stale ACK must not cancel a waiting request
    clr.b   (ForgeModernHandoff).w
    rts
.retry:
    cmpi.b  #1,(ForgeModernHandoff).w
    beq.s   ForgeModernQueueStop
    cmpi.b  #2,(ForgeModernHandoff).w
    bne.s   .return
    cmpi.b  #$80,(Z80_RAM+zAbsVar.QueueToPlay).l
    bne.s   .return
    ; Ready alone is not completion: music init/1-up can overwrite the request.
    move.b  #1,(ForgeModernHandoff).w
    bra.s   ForgeModernQueueStop
.return:
    rts

; The original sndDriverInput footprint is a trampoline plus inert padding.
; Same queue/pause semantics, with ACK service and exactly three SFX slots.
; Like stock, this routine clobbers d0/d1/a0/a1.
ForgeModernInput:
    bsr.w   ForgeModernCheckReady
    lea     (Sound_Queue&$00FFFFFF).l,a0
    lea     (Z80_RAM+zAbsVar).l,a1
    cmpi.b  #$80,zVar.QueueToPlay(a1)
    bne.s   .sfx
    _move.b SoundQueue.Music0(a0),d0
    beq.s   .second
    _clr.b  SoundQueue.Music0(a0)
    bra.s   .music
.second:
    move.b  SoundQueue.Music1(a0),d0
    beq.s   .sfx
    clr.b   SoundQueue.Music1(a0)
.music:
    move.b  d0,d1
    subi.b  #MusID_Pause,d1
    bcs.s   .deliver
    addi.b  #$7F,d1
    move.b  d1,zVar.StopMusic(a1)
    bra.s   .sfx
.deliver:
    cmpi.b  #MusID_ForgeStop,d0
    bne.s   .normal
    clr.b   (Z80_RAM+zHybridAck).l
    move.b  #2,(ForgeModernHandoff).w
.normal:
    move.b  d0,zVar.QueueToPlay(a1)
.sfx:
    moveq   #3-1,d1
.loop:
    move.b  SoundQueue.SFX0(a0,d1.w),d0
    beq.s   .skip
    tst.b   zVar.Queue0(a1,d1.w)
    bne.s   .skip
    clr.b   SoundQueue.SFX0(a0,d1.w)
    move.b  d0,zVar.Queue0(a1,d1.w)
.skip:
    dbf     d1,.loop
    rts

; Reached by the fixed-footprint SaxDec_GetByte trampoline. The last byte
; returns to its consumer; only the following request unwinds the caller.
ForgeModernSaxGetByte:
    subq.w  #1,d7
    bcs.s   .exit
    move.b  (a6)+,d0
    rts
.exit:
    addq.w  #4,sp
    rts
ForgeModernHandoffEnd:
    if ForgeModernHandoffEnd>$200000
        fatal "Forge handoff exceeds appended ROM region"
    endif
