; Stage 2: native-only modern seam. No runtime state or MD+ hardware access.
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
ForgeModernEnd:
    ; MOVE.B determines N/Z, clears V/C and preserves X. JMP/RTS do not
    ; change CCR. All data/address registers are preserved; no extra stack.
    if (ForgeModernPlayMusic<>$100000)||(ForgeModernEnd-ForgeModernPlayMusic<>18)
        fatal "Unexpected Stage 2 implementation layout"
    endif
