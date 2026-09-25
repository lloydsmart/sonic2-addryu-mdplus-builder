; Stage 3: native-only gameplay seam plus disconnected MD+ backend. No RAM state.
; Included AFTER the last sound bank, BEFORE upstream padding and EndOfRom.
    if (gameRevision<>1)||(fixBugs<>0)||(padToPowerOfTwo<>1)
        fatal "Forge modern scaffold requires REV01, fixBugs=0 and power-of-two padding"
    endif
    if *<>$FFFEC
        fatal "Unexpected upstream end of sound data"
    endif
    org $100000 ; dedicated appended region; leave stock padding intact

ForgeModernPlayMusic:
    tst.b   (Sound_Queue.Music0).w
    bne.s   ForgeModernPlayMusicSecond
    move.b  d0,(Sound_Queue.Music0).w
    rts
ForgeModernPlayMusicSecond:
    move.b  d0,(Sound_Queue.Music1).w
    rts
ForgeModernNativeEnd:
    ; MOVE.B determines N/Z, clears V/C and preserves X. JMP/RTS do not
    ; change CCR. All data/address registers are preserved; no extra stack.
    if (ForgeModernPlayMusic<>$100000)||(ForgeModernPlayMusicSecond<>$10000C)||(ForgeModernNativeEnd<>$100012)
        fatal "Unexpected Stage 2 implementation layout"
    endif

; Internal backend API only. Stage 4 must provide the music-only Z80 handoff
; before connecting this dispatcher to gameplay. Input d0.b; preserves all
; data/address registers, normal RTS stack effect. CCR is scratch (X preserved).
; Unsupported IDs return without any write. No persistent state is allocated.
MDP_CTRL = $0003F7FA
MDP_CMD  = $0003F7FE
ForgeModernDispatch:
; @DISPATCH@
    rts

; Each primitive preserves registers and X; final MOVE.W #0 gives N=V=C=0,
; Z=1. The three stores must be adjacent, with no persistent overlay opening.
; @COMMANDS@
ForgeModernEnd:
    if (ForgeModernDispatch<>$100012)||(ForgeModernEnd<>$1002B6)
        fatal "Unexpected Stage 3 backend layout"
    endif
    if ForgeModernEnd>$200000
        fatal "Forge modern backend exceeds the appended region"
    endif
