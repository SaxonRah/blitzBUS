#!/usr/bin/env python3
"""Build 8086/286 DOS COM regression test for memory RCL/RCR (D0/D1).
Requires GNU `as --32` and `objcopy`; the output is a normal DOS .COM.
This script never patches user source code.
"""
from pathlib import Path
import subprocess
root=Path(__file__).resolve().parent
MASK=0x8D5
cases=[]
for bits, vals in [(8,[0,1,2,0x3f,0x40,0x7f,0x80,0xff]),(16,[0,1,2,0x3fff,0x4000,0x7fff,0x8000,0xffff])]:
    for ins in ('rcl','rcr'):
        for val in vals:
            for cf in (0,1):
                mask=(1<<bits)-1
                if ins=='rcl':
                    res=((val<<1)|cf)&mask
                    outcf=(val>>(bits-1))&1
                    of=((res>>(bits-1))^outcf)&1
                else:
                    res=((val>>1)|(cf<<(bits-1)))&mask
                    outcf=val&1
                    of=((res>>(bits-1))^(res>>(bits-2)))&1
                expected=0x54|outcf|(of<<11)
                cases.append((bits,ins,val,cf,res,expected))
assert len(cases)==64
s=['.intel_syntax noprefix','.code16','.text','.org 0x100','start:',
   '  push cs','  pop ds','  mov ax, cs','  mov es, ax']
for i,(bits,op,val,cf,res,fl) in enumerate(cases,1):
    kind='byte' if bits==8 else 'word'
    target='test_b' if bits==8 else 'test_w'
    s.extend([
        f'  /* Case {i}: {op.upper()} {bits}-bit {val:#06x} CF={cf} -> {res:#06x}, CF/OF flags {fl:#05x} */',
        f'  mov byte ptr [case_tens], {ord(str(i//10))}',
        f'  mov byte ptr [case_ones], {ord(str(i%10))}',
    ])
    if bits==8:s.append(f'  mov byte ptr [{target}], {val}')
    else:s.extend([f'  mov ax, {val}',f'  mov word ptr [{target}], ax'])
    s.extend([
        f'  mov ax, {0xA54|cf}',
        '  push ax',
        '  popf',
        f'  {op} {kind} ptr [{target}], 1',
        '  pushf',
        '  pop bx',
        f'  and bx, {MASK}',
        f'  cmp bx, {fl}',
        f'  je okflags_{i}',
        '  jmp fail',
        f'okflags_{i}:',
    ])
    if bits==8:s.append(f'  cmp byte ptr [{target}], {res}')
    else:s.append(f'  cmp word ptr [{target}], {res}')
    s.extend([f'  je okvalue_{i}', '  jmp fail', f'okvalue_{i}:'])
s += ['pass:','  mov dx, offset pass_msg','  mov ah, 9','  int 0x21',
      '  mov ax, 0x4c00','  int 0x21',
      'fail:', '  mov dx, offset fail_msg','  mov ah, 9','  int 0x21',
      '  mov ax, 0x4c01','  int 0x21',
      'test_b: .byte 0','test_w: .word 0',
      'pass_msg: .ascii "RCXTEST PASS 64 / 64\\r\\n$"',
      'fail_msg: .ascii "RCXTEST FAIL case "',
      'case_tens: .byte 48','case_ones: .byte 48',
      ' .ascii "\\r\\n$"']
asmp=root/'RCXTEST.asm'; asmp.write_text('\n'.join(s)+'\n')
obj=root/'RCXTEST.o'; raw=root/'RCXTEST.raw';out=root/'RCXTEST.COM'
subprocess.run(['as','--32',str(asmp),'-o',str(obj)],check=True)
subprocess.run(['objcopy','-O','binary','-j','.text',str(obj),str(raw)],check=True)
b=raw.read_bytes()
assert b[:256]==b'\0'*256, 'expected .org 0x100 pad'
b=b[256:]
assert len(b)<65536-256
out.write_bytes(b)
print('Wrote',out,len(b),'bytes;',len(cases),'RCL/RCR byte and word memory+flags cases')
print('Assembled D0/D1 rotate instructions at',sum(x in b for x in (b'\xd0',b'\xd1')),'opcode-byte families (may include immediates)')
obj.unlink();raw.unlink()
