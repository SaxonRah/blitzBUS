.intel_syntax noprefix
.code16
.section .text
.global _start
_start:
  push cs
  pop ds
  cld
  mov ax,0x0040
  mov es,ax
  mov ax,0xb800
  mov word ptr cs:[vga_seg],ax
  .ifdef VGA
    mov ax,0x0013
    int 0x10
    mov ax,0xa000
    mov word ptr cs:[vga_seg],ax
  .endif
  mov bx,word ptr es:[0x006c]
  xor bp,bp
loop_chunk:
  .ifdef VGA
    push es
    mov ax,word ptr cs:[vga_seg]
    mov es,ax
    xor di,di
    mov cx,0x8000
    mov al,byte ptr cs:[pattern]
    rep stosb
    inc byte ptr cs:[pattern]
    pop es
  .else
    mov cx,0x8000
    mov ax,0x12a5
cpu_inner:
    add ax,cx
    xor ax,0x52a9
    rol ax,1
    dec cx
    jnz cpu_inner
    mov word ptr cs:[checksum],ax
  .endif
  inc bp
  mov ax,word ptr es:[0x006c]
  sub ax,bx
  cmp ax,36
  jb loop_chunk
  mov word ptr cs:[ticks],ax
  .ifdef VGA
    mov ax,0x0003
    int 0x10
  .endif
  push cs
  pop ds
  mov dx,offset msg
  mov ah,0x09
  int 0x21
  mov ax,bp
  call print_hex
  mov dx,offset msg2
  mov ah,0x09
  int 0x21
  mov ax,word ptr [ticks]
  call print_hex
  mov dx,offset msg3
  mov ah,0x09
  int 0x21
  mov ax,0x4c00
  int 0x21
print_hex:
  push ax
  push bx
  push cx
  push dx
  mov bx,ax
  mov cx,4
next_digit:
  rol bx,4
  mov dl,bl
  and dl,15
  cmp dl,9
  jbe digit
  add dl,7
digit:
  add dl,48
  mov ah,2
  int 0x21
  loop next_digit
  pop dx
  pop cx
  pop bx
  pop ax
  ret
msg:
  .ifdef VGA
  .ascii "T2C VGA CHUNKS=$"
  .else
  .ascii "T2C CPU CHUNKS=$"
  .endif
msg2: .ascii " TICKS=$"
msg3: .ascii " (HEX)\r\n$"
vga_seg: .word 0
checksum: .word 0
ticks: .word 0
pattern: .byte 0x5a
