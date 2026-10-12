.intel_syntax noprefix
.code16
.section .text
.global _start
_start:
 push cs
 pop ds
 cld
 mov dx,offset startmsg
 mov ah,9
 int 0x21
 mov cx,16
 call runloop
 mov dx,offset msg16
 call say
 mov cx,256
 call runloop
 mov dx,offset msg256
 call say
 mov cx,4096
 call runloop
 mov dx,offset msg4096
 call say
 mov cx,32768
 call runloop
 mov dx,offset msg32768
 call say
 mov ax,0x4c00
 int 0x21
runloop:
 mov ax,0x12a5
again:
 add ax,cx
 xor ax,0x52a9
 rol ax,1
 dec cx
 jnz again
 mov word ptr cs:[checksum],ax
 ret
say:
 push ax
 mov ah,9
 int 0x21
 pop ax
 ret
startmsg: .ascii "T2C DIAG START\r\n$"
msg16: .ascii "T2C PASS 16\r\n$"
msg256: .ascii "T2C PASS 256\r\n$"
msg4096: .ascii "T2C PASS 4096\r\n$"
msg32768: .ascii "T2C PASS 32768\r\n$"
checksum: .word 0
