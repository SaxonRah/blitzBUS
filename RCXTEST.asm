.intel_syntax noprefix
.code16
.text
.org 0x100
start:
  push cs
  pop ds
  mov ax, cs
  mov es, ax
  /* Case 1: RCL 8-bit 0x0000 CF=0 -> 0x0000, CF/OF flags 0x054 */
  mov byte ptr [case_tens], 48
  mov byte ptr [case_ones], 49
  mov byte ptr [test_b], 0
  mov ax, 2644
  push ax
  popf
  rcl byte ptr [test_b], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 84
  je okflags_1
  jmp fail
okflags_1:
  cmp byte ptr [test_b], 0
  je okvalue_1
  jmp fail
okvalue_1:
  /* Case 2: RCL 8-bit 0x0000 CF=1 -> 0x0001, CF/OF flags 0x054 */
  mov byte ptr [case_tens], 48
  mov byte ptr [case_ones], 50
  mov byte ptr [test_b], 0
  mov ax, 2645
  push ax
  popf
  rcl byte ptr [test_b], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 84
  je okflags_2
  jmp fail
okflags_2:
  cmp byte ptr [test_b], 1
  je okvalue_2
  jmp fail
okvalue_2:
  /* Case 3: RCL 8-bit 0x0001 CF=0 -> 0x0002, CF/OF flags 0x054 */
  mov byte ptr [case_tens], 48
  mov byte ptr [case_ones], 51
  mov byte ptr [test_b], 1
  mov ax, 2644
  push ax
  popf
  rcl byte ptr [test_b], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 84
  je okflags_3
  jmp fail
okflags_3:
  cmp byte ptr [test_b], 2
  je okvalue_3
  jmp fail
okvalue_3:
  /* Case 4: RCL 8-bit 0x0001 CF=1 -> 0x0003, CF/OF flags 0x054 */
  mov byte ptr [case_tens], 48
  mov byte ptr [case_ones], 52
  mov byte ptr [test_b], 1
  mov ax, 2645
  push ax
  popf
  rcl byte ptr [test_b], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 84
  je okflags_4
  jmp fail
okflags_4:
  cmp byte ptr [test_b], 3
  je okvalue_4
  jmp fail
okvalue_4:
  /* Case 5: RCL 8-bit 0x0002 CF=0 -> 0x0004, CF/OF flags 0x054 */
  mov byte ptr [case_tens], 48
  mov byte ptr [case_ones], 53
  mov byte ptr [test_b], 2
  mov ax, 2644
  push ax
  popf
  rcl byte ptr [test_b], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 84
  je okflags_5
  jmp fail
okflags_5:
  cmp byte ptr [test_b], 4
  je okvalue_5
  jmp fail
okvalue_5:
  /* Case 6: RCL 8-bit 0x0002 CF=1 -> 0x0005, CF/OF flags 0x054 */
  mov byte ptr [case_tens], 48
  mov byte ptr [case_ones], 54
  mov byte ptr [test_b], 2
  mov ax, 2645
  push ax
  popf
  rcl byte ptr [test_b], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 84
  je okflags_6
  jmp fail
okflags_6:
  cmp byte ptr [test_b], 5
  je okvalue_6
  jmp fail
okvalue_6:
  /* Case 7: RCL 8-bit 0x003f CF=0 -> 0x007e, CF/OF flags 0x054 */
  mov byte ptr [case_tens], 48
  mov byte ptr [case_ones], 55
  mov byte ptr [test_b], 63
  mov ax, 2644
  push ax
  popf
  rcl byte ptr [test_b], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 84
  je okflags_7
  jmp fail
okflags_7:
  cmp byte ptr [test_b], 126
  je okvalue_7
  jmp fail
okvalue_7:
  /* Case 8: RCL 8-bit 0x003f CF=1 -> 0x007f, CF/OF flags 0x054 */
  mov byte ptr [case_tens], 48
  mov byte ptr [case_ones], 56
  mov byte ptr [test_b], 63
  mov ax, 2645
  push ax
  popf
  rcl byte ptr [test_b], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 84
  je okflags_8
  jmp fail
okflags_8:
  cmp byte ptr [test_b], 127
  je okvalue_8
  jmp fail
okvalue_8:
  /* Case 9: RCL 8-bit 0x0040 CF=0 -> 0x0080, CF/OF flags 0x854 */
  mov byte ptr [case_tens], 48
  mov byte ptr [case_ones], 57
  mov byte ptr [test_b], 64
  mov ax, 2644
  push ax
  popf
  rcl byte ptr [test_b], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 2132
  je okflags_9
  jmp fail
okflags_9:
  cmp byte ptr [test_b], 128
  je okvalue_9
  jmp fail
okvalue_9:
  /* Case 10: RCL 8-bit 0x0040 CF=1 -> 0x0081, CF/OF flags 0x854 */
  mov byte ptr [case_tens], 49
  mov byte ptr [case_ones], 48
  mov byte ptr [test_b], 64
  mov ax, 2645
  push ax
  popf
  rcl byte ptr [test_b], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 2132
  je okflags_10
  jmp fail
okflags_10:
  cmp byte ptr [test_b], 129
  je okvalue_10
  jmp fail
okvalue_10:
  /* Case 11: RCL 8-bit 0x007f CF=0 -> 0x00fe, CF/OF flags 0x854 */
  mov byte ptr [case_tens], 49
  mov byte ptr [case_ones], 49
  mov byte ptr [test_b], 127
  mov ax, 2644
  push ax
  popf
  rcl byte ptr [test_b], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 2132
  je okflags_11
  jmp fail
okflags_11:
  cmp byte ptr [test_b], 254
  je okvalue_11
  jmp fail
okvalue_11:
  /* Case 12: RCL 8-bit 0x007f CF=1 -> 0x00ff, CF/OF flags 0x854 */
  mov byte ptr [case_tens], 49
  mov byte ptr [case_ones], 50
  mov byte ptr [test_b], 127
  mov ax, 2645
  push ax
  popf
  rcl byte ptr [test_b], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 2132
  je okflags_12
  jmp fail
okflags_12:
  cmp byte ptr [test_b], 255
  je okvalue_12
  jmp fail
okvalue_12:
  /* Case 13: RCL 8-bit 0x0080 CF=0 -> 0x0000, CF/OF flags 0x855 */
  mov byte ptr [case_tens], 49
  mov byte ptr [case_ones], 51
  mov byte ptr [test_b], 128
  mov ax, 2644
  push ax
  popf
  rcl byte ptr [test_b], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 2133
  je okflags_13
  jmp fail
okflags_13:
  cmp byte ptr [test_b], 0
  je okvalue_13
  jmp fail
okvalue_13:
  /* Case 14: RCL 8-bit 0x0080 CF=1 -> 0x0001, CF/OF flags 0x855 */
  mov byte ptr [case_tens], 49
  mov byte ptr [case_ones], 52
  mov byte ptr [test_b], 128
  mov ax, 2645
  push ax
  popf
  rcl byte ptr [test_b], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 2133
  je okflags_14
  jmp fail
okflags_14:
  cmp byte ptr [test_b], 1
  je okvalue_14
  jmp fail
okvalue_14:
  /* Case 15: RCL 8-bit 0x00ff CF=0 -> 0x00fe, CF/OF flags 0x055 */
  mov byte ptr [case_tens], 49
  mov byte ptr [case_ones], 53
  mov byte ptr [test_b], 255
  mov ax, 2644
  push ax
  popf
  rcl byte ptr [test_b], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 85
  je okflags_15
  jmp fail
okflags_15:
  cmp byte ptr [test_b], 254
  je okvalue_15
  jmp fail
okvalue_15:
  /* Case 16: RCL 8-bit 0x00ff CF=1 -> 0x00ff, CF/OF flags 0x055 */
  mov byte ptr [case_tens], 49
  mov byte ptr [case_ones], 54
  mov byte ptr [test_b], 255
  mov ax, 2645
  push ax
  popf
  rcl byte ptr [test_b], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 85
  je okflags_16
  jmp fail
okflags_16:
  cmp byte ptr [test_b], 255
  je okvalue_16
  jmp fail
okvalue_16:
  /* Case 17: RCR 8-bit 0x0000 CF=0 -> 0x0000, CF/OF flags 0x054 */
  mov byte ptr [case_tens], 49
  mov byte ptr [case_ones], 55
  mov byte ptr [test_b], 0
  mov ax, 2644
  push ax
  popf
  rcr byte ptr [test_b], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 84
  je okflags_17
  jmp fail
okflags_17:
  cmp byte ptr [test_b], 0
  je okvalue_17
  jmp fail
okvalue_17:
  /* Case 18: RCR 8-bit 0x0000 CF=1 -> 0x0080, CF/OF flags 0x854 */
  mov byte ptr [case_tens], 49
  mov byte ptr [case_ones], 56
  mov byte ptr [test_b], 0
  mov ax, 2645
  push ax
  popf
  rcr byte ptr [test_b], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 2132
  je okflags_18
  jmp fail
okflags_18:
  cmp byte ptr [test_b], 128
  je okvalue_18
  jmp fail
okvalue_18:
  /* Case 19: RCR 8-bit 0x0001 CF=0 -> 0x0000, CF/OF flags 0x055 */
  mov byte ptr [case_tens], 49
  mov byte ptr [case_ones], 57
  mov byte ptr [test_b], 1
  mov ax, 2644
  push ax
  popf
  rcr byte ptr [test_b], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 85
  je okflags_19
  jmp fail
okflags_19:
  cmp byte ptr [test_b], 0
  je okvalue_19
  jmp fail
okvalue_19:
  /* Case 20: RCR 8-bit 0x0001 CF=1 -> 0x0080, CF/OF flags 0x855 */
  mov byte ptr [case_tens], 50
  mov byte ptr [case_ones], 48
  mov byte ptr [test_b], 1
  mov ax, 2645
  push ax
  popf
  rcr byte ptr [test_b], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 2133
  je okflags_20
  jmp fail
okflags_20:
  cmp byte ptr [test_b], 128
  je okvalue_20
  jmp fail
okvalue_20:
  /* Case 21: RCR 8-bit 0x0002 CF=0 -> 0x0001, CF/OF flags 0x054 */
  mov byte ptr [case_tens], 50
  mov byte ptr [case_ones], 49
  mov byte ptr [test_b], 2
  mov ax, 2644
  push ax
  popf
  rcr byte ptr [test_b], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 84
  je okflags_21
  jmp fail
okflags_21:
  cmp byte ptr [test_b], 1
  je okvalue_21
  jmp fail
okvalue_21:
  /* Case 22: RCR 8-bit 0x0002 CF=1 -> 0x0081, CF/OF flags 0x854 */
  mov byte ptr [case_tens], 50
  mov byte ptr [case_ones], 50
  mov byte ptr [test_b], 2
  mov ax, 2645
  push ax
  popf
  rcr byte ptr [test_b], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 2132
  je okflags_22
  jmp fail
okflags_22:
  cmp byte ptr [test_b], 129
  je okvalue_22
  jmp fail
okvalue_22:
  /* Case 23: RCR 8-bit 0x003f CF=0 -> 0x001f, CF/OF flags 0x055 */
  mov byte ptr [case_tens], 50
  mov byte ptr [case_ones], 51
  mov byte ptr [test_b], 63
  mov ax, 2644
  push ax
  popf
  rcr byte ptr [test_b], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 85
  je okflags_23
  jmp fail
okflags_23:
  cmp byte ptr [test_b], 31
  je okvalue_23
  jmp fail
okvalue_23:
  /* Case 24: RCR 8-bit 0x003f CF=1 -> 0x009f, CF/OF flags 0x855 */
  mov byte ptr [case_tens], 50
  mov byte ptr [case_ones], 52
  mov byte ptr [test_b], 63
  mov ax, 2645
  push ax
  popf
  rcr byte ptr [test_b], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 2133
  je okflags_24
  jmp fail
okflags_24:
  cmp byte ptr [test_b], 159
  je okvalue_24
  jmp fail
okvalue_24:
  /* Case 25: RCR 8-bit 0x0040 CF=0 -> 0x0020, CF/OF flags 0x054 */
  mov byte ptr [case_tens], 50
  mov byte ptr [case_ones], 53
  mov byte ptr [test_b], 64
  mov ax, 2644
  push ax
  popf
  rcr byte ptr [test_b], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 84
  je okflags_25
  jmp fail
okflags_25:
  cmp byte ptr [test_b], 32
  je okvalue_25
  jmp fail
okvalue_25:
  /* Case 26: RCR 8-bit 0x0040 CF=1 -> 0x00a0, CF/OF flags 0x854 */
  mov byte ptr [case_tens], 50
  mov byte ptr [case_ones], 54
  mov byte ptr [test_b], 64
  mov ax, 2645
  push ax
  popf
  rcr byte ptr [test_b], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 2132
  je okflags_26
  jmp fail
okflags_26:
  cmp byte ptr [test_b], 160
  je okvalue_26
  jmp fail
okvalue_26:
  /* Case 27: RCR 8-bit 0x007f CF=0 -> 0x003f, CF/OF flags 0x055 */
  mov byte ptr [case_tens], 50
  mov byte ptr [case_ones], 55
  mov byte ptr [test_b], 127
  mov ax, 2644
  push ax
  popf
  rcr byte ptr [test_b], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 85
  je okflags_27
  jmp fail
okflags_27:
  cmp byte ptr [test_b], 63
  je okvalue_27
  jmp fail
okvalue_27:
  /* Case 28: RCR 8-bit 0x007f CF=1 -> 0x00bf, CF/OF flags 0x855 */
  mov byte ptr [case_tens], 50
  mov byte ptr [case_ones], 56
  mov byte ptr [test_b], 127
  mov ax, 2645
  push ax
  popf
  rcr byte ptr [test_b], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 2133
  je okflags_28
  jmp fail
okflags_28:
  cmp byte ptr [test_b], 191
  je okvalue_28
  jmp fail
okvalue_28:
  /* Case 29: RCR 8-bit 0x0080 CF=0 -> 0x0040, CF/OF flags 0x854 */
  mov byte ptr [case_tens], 50
  mov byte ptr [case_ones], 57
  mov byte ptr [test_b], 128
  mov ax, 2644
  push ax
  popf
  rcr byte ptr [test_b], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 2132
  je okflags_29
  jmp fail
okflags_29:
  cmp byte ptr [test_b], 64
  je okvalue_29
  jmp fail
okvalue_29:
  /* Case 30: RCR 8-bit 0x0080 CF=1 -> 0x00c0, CF/OF flags 0x054 */
  mov byte ptr [case_tens], 51
  mov byte ptr [case_ones], 48
  mov byte ptr [test_b], 128
  mov ax, 2645
  push ax
  popf
  rcr byte ptr [test_b], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 84
  je okflags_30
  jmp fail
okflags_30:
  cmp byte ptr [test_b], 192
  je okvalue_30
  jmp fail
okvalue_30:
  /* Case 31: RCR 8-bit 0x00ff CF=0 -> 0x007f, CF/OF flags 0x855 */
  mov byte ptr [case_tens], 51
  mov byte ptr [case_ones], 49
  mov byte ptr [test_b], 255
  mov ax, 2644
  push ax
  popf
  rcr byte ptr [test_b], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 2133
  je okflags_31
  jmp fail
okflags_31:
  cmp byte ptr [test_b], 127
  je okvalue_31
  jmp fail
okvalue_31:
  /* Case 32: RCR 8-bit 0x00ff CF=1 -> 0x00ff, CF/OF flags 0x055 */
  mov byte ptr [case_tens], 51
  mov byte ptr [case_ones], 50
  mov byte ptr [test_b], 255
  mov ax, 2645
  push ax
  popf
  rcr byte ptr [test_b], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 85
  je okflags_32
  jmp fail
okflags_32:
  cmp byte ptr [test_b], 255
  je okvalue_32
  jmp fail
okvalue_32:
  /* Case 33: RCL 16-bit 0x0000 CF=0 -> 0x0000, CF/OF flags 0x054 */
  mov byte ptr [case_tens], 51
  mov byte ptr [case_ones], 51
  mov ax, 0
  mov word ptr [test_w], ax
  mov ax, 2644
  push ax
  popf
  rcl word ptr [test_w], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 84
  je okflags_33
  jmp fail
okflags_33:
  cmp word ptr [test_w], 0
  je okvalue_33
  jmp fail
okvalue_33:
  /* Case 34: RCL 16-bit 0x0000 CF=1 -> 0x0001, CF/OF flags 0x054 */
  mov byte ptr [case_tens], 51
  mov byte ptr [case_ones], 52
  mov ax, 0
  mov word ptr [test_w], ax
  mov ax, 2645
  push ax
  popf
  rcl word ptr [test_w], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 84
  je okflags_34
  jmp fail
okflags_34:
  cmp word ptr [test_w], 1
  je okvalue_34
  jmp fail
okvalue_34:
  /* Case 35: RCL 16-bit 0x0001 CF=0 -> 0x0002, CF/OF flags 0x054 */
  mov byte ptr [case_tens], 51
  mov byte ptr [case_ones], 53
  mov ax, 1
  mov word ptr [test_w], ax
  mov ax, 2644
  push ax
  popf
  rcl word ptr [test_w], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 84
  je okflags_35
  jmp fail
okflags_35:
  cmp word ptr [test_w], 2
  je okvalue_35
  jmp fail
okvalue_35:
  /* Case 36: RCL 16-bit 0x0001 CF=1 -> 0x0003, CF/OF flags 0x054 */
  mov byte ptr [case_tens], 51
  mov byte ptr [case_ones], 54
  mov ax, 1
  mov word ptr [test_w], ax
  mov ax, 2645
  push ax
  popf
  rcl word ptr [test_w], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 84
  je okflags_36
  jmp fail
okflags_36:
  cmp word ptr [test_w], 3
  je okvalue_36
  jmp fail
okvalue_36:
  /* Case 37: RCL 16-bit 0x0002 CF=0 -> 0x0004, CF/OF flags 0x054 */
  mov byte ptr [case_tens], 51
  mov byte ptr [case_ones], 55
  mov ax, 2
  mov word ptr [test_w], ax
  mov ax, 2644
  push ax
  popf
  rcl word ptr [test_w], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 84
  je okflags_37
  jmp fail
okflags_37:
  cmp word ptr [test_w], 4
  je okvalue_37
  jmp fail
okvalue_37:
  /* Case 38: RCL 16-bit 0x0002 CF=1 -> 0x0005, CF/OF flags 0x054 */
  mov byte ptr [case_tens], 51
  mov byte ptr [case_ones], 56
  mov ax, 2
  mov word ptr [test_w], ax
  mov ax, 2645
  push ax
  popf
  rcl word ptr [test_w], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 84
  je okflags_38
  jmp fail
okflags_38:
  cmp word ptr [test_w], 5
  je okvalue_38
  jmp fail
okvalue_38:
  /* Case 39: RCL 16-bit 0x3fff CF=0 -> 0x7ffe, CF/OF flags 0x054 */
  mov byte ptr [case_tens], 51
  mov byte ptr [case_ones], 57
  mov ax, 16383
  mov word ptr [test_w], ax
  mov ax, 2644
  push ax
  popf
  rcl word ptr [test_w], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 84
  je okflags_39
  jmp fail
okflags_39:
  cmp word ptr [test_w], 32766
  je okvalue_39
  jmp fail
okvalue_39:
  /* Case 40: RCL 16-bit 0x3fff CF=1 -> 0x7fff, CF/OF flags 0x054 */
  mov byte ptr [case_tens], 52
  mov byte ptr [case_ones], 48
  mov ax, 16383
  mov word ptr [test_w], ax
  mov ax, 2645
  push ax
  popf
  rcl word ptr [test_w], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 84
  je okflags_40
  jmp fail
okflags_40:
  cmp word ptr [test_w], 32767
  je okvalue_40
  jmp fail
okvalue_40:
  /* Case 41: RCL 16-bit 0x4000 CF=0 -> 0x8000, CF/OF flags 0x854 */
  mov byte ptr [case_tens], 52
  mov byte ptr [case_ones], 49
  mov ax, 16384
  mov word ptr [test_w], ax
  mov ax, 2644
  push ax
  popf
  rcl word ptr [test_w], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 2132
  je okflags_41
  jmp fail
okflags_41:
  cmp word ptr [test_w], 32768
  je okvalue_41
  jmp fail
okvalue_41:
  /* Case 42: RCL 16-bit 0x4000 CF=1 -> 0x8001, CF/OF flags 0x854 */
  mov byte ptr [case_tens], 52
  mov byte ptr [case_ones], 50
  mov ax, 16384
  mov word ptr [test_w], ax
  mov ax, 2645
  push ax
  popf
  rcl word ptr [test_w], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 2132
  je okflags_42
  jmp fail
okflags_42:
  cmp word ptr [test_w], 32769
  je okvalue_42
  jmp fail
okvalue_42:
  /* Case 43: RCL 16-bit 0x7fff CF=0 -> 0xfffe, CF/OF flags 0x854 */
  mov byte ptr [case_tens], 52
  mov byte ptr [case_ones], 51
  mov ax, 32767
  mov word ptr [test_w], ax
  mov ax, 2644
  push ax
  popf
  rcl word ptr [test_w], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 2132
  je okflags_43
  jmp fail
okflags_43:
  cmp word ptr [test_w], 65534
  je okvalue_43
  jmp fail
okvalue_43:
  /* Case 44: RCL 16-bit 0x7fff CF=1 -> 0xffff, CF/OF flags 0x854 */
  mov byte ptr [case_tens], 52
  mov byte ptr [case_ones], 52
  mov ax, 32767
  mov word ptr [test_w], ax
  mov ax, 2645
  push ax
  popf
  rcl word ptr [test_w], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 2132
  je okflags_44
  jmp fail
okflags_44:
  cmp word ptr [test_w], 65535
  je okvalue_44
  jmp fail
okvalue_44:
  /* Case 45: RCL 16-bit 0x8000 CF=0 -> 0x0000, CF/OF flags 0x855 */
  mov byte ptr [case_tens], 52
  mov byte ptr [case_ones], 53
  mov ax, 32768
  mov word ptr [test_w], ax
  mov ax, 2644
  push ax
  popf
  rcl word ptr [test_w], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 2133
  je okflags_45
  jmp fail
okflags_45:
  cmp word ptr [test_w], 0
  je okvalue_45
  jmp fail
okvalue_45:
  /* Case 46: RCL 16-bit 0x8000 CF=1 -> 0x0001, CF/OF flags 0x855 */
  mov byte ptr [case_tens], 52
  mov byte ptr [case_ones], 54
  mov ax, 32768
  mov word ptr [test_w], ax
  mov ax, 2645
  push ax
  popf
  rcl word ptr [test_w], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 2133
  je okflags_46
  jmp fail
okflags_46:
  cmp word ptr [test_w], 1
  je okvalue_46
  jmp fail
okvalue_46:
  /* Case 47: RCL 16-bit 0xffff CF=0 -> 0xfffe, CF/OF flags 0x055 */
  mov byte ptr [case_tens], 52
  mov byte ptr [case_ones], 55
  mov ax, 65535
  mov word ptr [test_w], ax
  mov ax, 2644
  push ax
  popf
  rcl word ptr [test_w], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 85
  je okflags_47
  jmp fail
okflags_47:
  cmp word ptr [test_w], 65534
  je okvalue_47
  jmp fail
okvalue_47:
  /* Case 48: RCL 16-bit 0xffff CF=1 -> 0xffff, CF/OF flags 0x055 */
  mov byte ptr [case_tens], 52
  mov byte ptr [case_ones], 56
  mov ax, 65535
  mov word ptr [test_w], ax
  mov ax, 2645
  push ax
  popf
  rcl word ptr [test_w], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 85
  je okflags_48
  jmp fail
okflags_48:
  cmp word ptr [test_w], 65535
  je okvalue_48
  jmp fail
okvalue_48:
  /* Case 49: RCR 16-bit 0x0000 CF=0 -> 0x0000, CF/OF flags 0x054 */
  mov byte ptr [case_tens], 52
  mov byte ptr [case_ones], 57
  mov ax, 0
  mov word ptr [test_w], ax
  mov ax, 2644
  push ax
  popf
  rcr word ptr [test_w], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 84
  je okflags_49
  jmp fail
okflags_49:
  cmp word ptr [test_w], 0
  je okvalue_49
  jmp fail
okvalue_49:
  /* Case 50: RCR 16-bit 0x0000 CF=1 -> 0x8000, CF/OF flags 0x854 */
  mov byte ptr [case_tens], 53
  mov byte ptr [case_ones], 48
  mov ax, 0
  mov word ptr [test_w], ax
  mov ax, 2645
  push ax
  popf
  rcr word ptr [test_w], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 2132
  je okflags_50
  jmp fail
okflags_50:
  cmp word ptr [test_w], 32768
  je okvalue_50
  jmp fail
okvalue_50:
  /* Case 51: RCR 16-bit 0x0001 CF=0 -> 0x0000, CF/OF flags 0x055 */
  mov byte ptr [case_tens], 53
  mov byte ptr [case_ones], 49
  mov ax, 1
  mov word ptr [test_w], ax
  mov ax, 2644
  push ax
  popf
  rcr word ptr [test_w], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 85
  je okflags_51
  jmp fail
okflags_51:
  cmp word ptr [test_w], 0
  je okvalue_51
  jmp fail
okvalue_51:
  /* Case 52: RCR 16-bit 0x0001 CF=1 -> 0x8000, CF/OF flags 0x855 */
  mov byte ptr [case_tens], 53
  mov byte ptr [case_ones], 50
  mov ax, 1
  mov word ptr [test_w], ax
  mov ax, 2645
  push ax
  popf
  rcr word ptr [test_w], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 2133
  je okflags_52
  jmp fail
okflags_52:
  cmp word ptr [test_w], 32768
  je okvalue_52
  jmp fail
okvalue_52:
  /* Case 53: RCR 16-bit 0x0002 CF=0 -> 0x0001, CF/OF flags 0x054 */
  mov byte ptr [case_tens], 53
  mov byte ptr [case_ones], 51
  mov ax, 2
  mov word ptr [test_w], ax
  mov ax, 2644
  push ax
  popf
  rcr word ptr [test_w], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 84
  je okflags_53
  jmp fail
okflags_53:
  cmp word ptr [test_w], 1
  je okvalue_53
  jmp fail
okvalue_53:
  /* Case 54: RCR 16-bit 0x0002 CF=1 -> 0x8001, CF/OF flags 0x854 */
  mov byte ptr [case_tens], 53
  mov byte ptr [case_ones], 52
  mov ax, 2
  mov word ptr [test_w], ax
  mov ax, 2645
  push ax
  popf
  rcr word ptr [test_w], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 2132
  je okflags_54
  jmp fail
okflags_54:
  cmp word ptr [test_w], 32769
  je okvalue_54
  jmp fail
okvalue_54:
  /* Case 55: RCR 16-bit 0x3fff CF=0 -> 0x1fff, CF/OF flags 0x055 */
  mov byte ptr [case_tens], 53
  mov byte ptr [case_ones], 53
  mov ax, 16383
  mov word ptr [test_w], ax
  mov ax, 2644
  push ax
  popf
  rcr word ptr [test_w], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 85
  je okflags_55
  jmp fail
okflags_55:
  cmp word ptr [test_w], 8191
  je okvalue_55
  jmp fail
okvalue_55:
  /* Case 56: RCR 16-bit 0x3fff CF=1 -> 0x9fff, CF/OF flags 0x855 */
  mov byte ptr [case_tens], 53
  mov byte ptr [case_ones], 54
  mov ax, 16383
  mov word ptr [test_w], ax
  mov ax, 2645
  push ax
  popf
  rcr word ptr [test_w], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 2133
  je okflags_56
  jmp fail
okflags_56:
  cmp word ptr [test_w], 40959
  je okvalue_56
  jmp fail
okvalue_56:
  /* Case 57: RCR 16-bit 0x4000 CF=0 -> 0x2000, CF/OF flags 0x054 */
  mov byte ptr [case_tens], 53
  mov byte ptr [case_ones], 55
  mov ax, 16384
  mov word ptr [test_w], ax
  mov ax, 2644
  push ax
  popf
  rcr word ptr [test_w], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 84
  je okflags_57
  jmp fail
okflags_57:
  cmp word ptr [test_w], 8192
  je okvalue_57
  jmp fail
okvalue_57:
  /* Case 58: RCR 16-bit 0x4000 CF=1 -> 0xa000, CF/OF flags 0x854 */
  mov byte ptr [case_tens], 53
  mov byte ptr [case_ones], 56
  mov ax, 16384
  mov word ptr [test_w], ax
  mov ax, 2645
  push ax
  popf
  rcr word ptr [test_w], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 2132
  je okflags_58
  jmp fail
okflags_58:
  cmp word ptr [test_w], 40960
  je okvalue_58
  jmp fail
okvalue_58:
  /* Case 59: RCR 16-bit 0x7fff CF=0 -> 0x3fff, CF/OF flags 0x055 */
  mov byte ptr [case_tens], 53
  mov byte ptr [case_ones], 57
  mov ax, 32767
  mov word ptr [test_w], ax
  mov ax, 2644
  push ax
  popf
  rcr word ptr [test_w], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 85
  je okflags_59
  jmp fail
okflags_59:
  cmp word ptr [test_w], 16383
  je okvalue_59
  jmp fail
okvalue_59:
  /* Case 60: RCR 16-bit 0x7fff CF=1 -> 0xbfff, CF/OF flags 0x855 */
  mov byte ptr [case_tens], 54
  mov byte ptr [case_ones], 48
  mov ax, 32767
  mov word ptr [test_w], ax
  mov ax, 2645
  push ax
  popf
  rcr word ptr [test_w], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 2133
  je okflags_60
  jmp fail
okflags_60:
  cmp word ptr [test_w], 49151
  je okvalue_60
  jmp fail
okvalue_60:
  /* Case 61: RCR 16-bit 0x8000 CF=0 -> 0x4000, CF/OF flags 0x854 */
  mov byte ptr [case_tens], 54
  mov byte ptr [case_ones], 49
  mov ax, 32768
  mov word ptr [test_w], ax
  mov ax, 2644
  push ax
  popf
  rcr word ptr [test_w], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 2132
  je okflags_61
  jmp fail
okflags_61:
  cmp word ptr [test_w], 16384
  je okvalue_61
  jmp fail
okvalue_61:
  /* Case 62: RCR 16-bit 0x8000 CF=1 -> 0xc000, CF/OF flags 0x054 */
  mov byte ptr [case_tens], 54
  mov byte ptr [case_ones], 50
  mov ax, 32768
  mov word ptr [test_w], ax
  mov ax, 2645
  push ax
  popf
  rcr word ptr [test_w], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 84
  je okflags_62
  jmp fail
okflags_62:
  cmp word ptr [test_w], 49152
  je okvalue_62
  jmp fail
okvalue_62:
  /* Case 63: RCR 16-bit 0xffff CF=0 -> 0x7fff, CF/OF flags 0x855 */
  mov byte ptr [case_tens], 54
  mov byte ptr [case_ones], 51
  mov ax, 65535
  mov word ptr [test_w], ax
  mov ax, 2644
  push ax
  popf
  rcr word ptr [test_w], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 2133
  je okflags_63
  jmp fail
okflags_63:
  cmp word ptr [test_w], 32767
  je okvalue_63
  jmp fail
okvalue_63:
  /* Case 64: RCR 16-bit 0xffff CF=1 -> 0xffff, CF/OF flags 0x055 */
  mov byte ptr [case_tens], 54
  mov byte ptr [case_ones], 52
  mov ax, 65535
  mov word ptr [test_w], ax
  mov ax, 2645
  push ax
  popf
  rcr word ptr [test_w], 1
  pushf
  pop bx
  and bx, 2261
  cmp bx, 85
  je okflags_64
  jmp fail
okflags_64:
  cmp word ptr [test_w], 65535
  je okvalue_64
  jmp fail
okvalue_64:
pass:
  mov dx, offset pass_msg
  mov ah, 9
  int 0x21
  mov ax, 0x4c00
  int 0x21
fail:
  mov dx, offset fail_msg
  mov ah, 9
  int 0x21
  mov ax, 0x4c01
  int 0x21
test_b: .byte 0
test_w: .word 0
pass_msg: .ascii "RCXTEST PASS 64 / 64\r\n$"
fail_msg: .ascii "RCXTEST FAIL case "
case_tens: .byte 48
case_ones: .byte 48
 .ascii "\r\n$"
