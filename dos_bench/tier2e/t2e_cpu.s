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
 xor bp,bp
 xor si,si
next_chunk:
 inc bp
 mov ax,bp
 xor ax,0x12a5
 mov cx,32768
cpu_inner:
 add ax,cx
 xor ax,0x52a9
 rol ax,1
 dec cx
 jnz cpu_inner
 xor si,ax
 mov word ptr cs:[checksum],si
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
 mov dx,offset resultmsg
 call say
 mov ax,si
 call print_hex
 mov dx,offset endmsg
 call say
 mov ax,0x4c00
 int 0x21
say:
 push ax
 push bx
 push cx
 push dx
 mov ah,9
 int 0x21
 pop dx
 pop cx
 pop bx
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
startmsg: .ascii "T2E START\r\n$"
p64msg: .ascii "T2E PASS 64\r\n$"
p128msg: .ascii "T2E PASS 128\r\n$"
p192msg: .ascii "T2E PASS 192\r\n$"
p256msg: .ascii "T2E PASS 256\r\n$"
resultmsg: .ascii "T2E CHECKSUM=$"
endmsg: .ascii " T2E END\r\n$"
checksum: .word 0
