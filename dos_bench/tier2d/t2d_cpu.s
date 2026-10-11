.intel_syntax noprefix
.code16
.section .text
.global _start
_start:
 push cs
 pop ds
 cld
 mov dx,offset startmsg
 call say
 call read_tick
 mov word ptr cs:[t_start],ax
 xor bp,bp
next_chunk:
 mov cx,32768
 mov ax,0x12a5
cpu_inner:
 add ax,cx
 xor ax,0x52a9
 rol ax,1
 dec cx
 jnz cpu_inner
 mov word ptr cs:[checksum],ax
 inc bp
 cmp bp,64
 je p64
 cmp bp,128
 je p128
 cmp bp,192
 je p192
 cmp bp,256
 jne next_chunk
 mov dx,offset p256msg
 call say
 jmp finished
p64:
 mov dx,offset p64msg
 call say
 jmp next_chunk
p128:
 mov dx,offset p128msg
 call say
 jmp next_chunk
p192:
 mov dx,offset p192msg
 call say
 jmp next_chunk
finished:
 call read_tick
 sub ax,word ptr cs:[t_start]
 mov word ptr cs:[ticks],ax
 mov dx,offset resultmsg
 call say
 mov ax,bp
 call print_hex
 mov dx,offset tickmsg
 call say
 mov ax,word ptr cs:[ticks]
 call print_hex
 mov dx,offset endmsg
 call say
 mov ax,0x4c00
 int 0x21
read_tick:
 push ds
 mov ax,0x0040
 mov ds,ax
 mov ax,word ptr [0x006c]
 pop ds
 ret
say:
 push ax
 mov ah,9
 int 0x21
 pop ax
 ret
print_hex:
 push ax
 push bx
 push cx
 push dx
 mov bx,ax
 mov cx,4
next_digit:
 rol bx,1
 rol bx,1
 rol bx,1
 rol bx,1
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
startmsg: .ascii "T2D CPU START\r\n$"
p64msg: .ascii "T2D PASS 64\r\n$"
p128msg: .ascii "T2D PASS 128\r\n$"
p192msg: .ascii "T2D PASS 192\r\n$"
p256msg: .ascii "T2D PASS 256\r\n$"
resultmsg: .ascii "T2D CPU CHUNKS=$"
tickmsg: .ascii " TICKS=$"
endmsg: .ascii " (HEX)\r\n$"
t_start: .word 0
ticks: .word 0
checksum: .word 0
