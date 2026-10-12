from pathlib import Path
# Tiny DOS 8086 COM binary. Uses INT F6 AH=B1, DS:DX -> DOS command-tail path.
code=bytearray();labels={};fixups=[]
def emit(*b):code.extend(b)
def mark(n):labels[n]=len(code)
def rel8(op,target):emit(op,0);fixups.append((len(code)-1,target,'rel8'))
def jmp(target):emit(0xE9,0,0);fixups.append((len(code)-2,target,'rel16'))
def addr(op,target):emit(*op,0,0);fixups.append((len(code)-2,target,'addr'))
# command tail begins at 81h; strip leading spaces
emit(0xBE,0x81,0x00)
mark('spaces');emit(0x8A,0x04,0x3C,0x20);rel8(0x75,'found');emit(0x46);rel8(0xEB,'spaces')
mark('found');emit(0x3C,0x0D);rel8(0x74,'usage');emit(0x89,0xF2) # mov dx,si
mark('scan');emit(0x8A,0x04,0x3C,0x0D);rel8(0x74,'terminate');emit(0x46);rel8(0xEB,'scan')
mark('terminate');emit(0xC6,0x04,0);emit(0xB4,0xB1,0xCD,0xF6);emit(0x80,0xFC,0);rel8(0x75,'failed')
addr((0xBA,),'ok');emit(0xB4,0x09,0xCD,0x21,0xB8,0x00,0x4C,0xCD,0x21)
mark('failed');addr((0xBA,),'bad');emit(0xB4,0x09,0xCD,0x21,0xB8,0x01,0x4C,0xCD,0x21)
mark('usage');addr((0xBA,),'help');emit(0xB4,0x09,0xCD,0x21,0xB8,0x02,0x4C,0xCD,0x21)
mark('ok');emit(*b'B: disk mounted.\r\n$')
mark('bad');emit(*b'DISK: mount failed.\r\n$')
mark('help');emit(*b'Usage: DISK SD:\\DIR\\FLOPPY.IMG or DISK C:\\DIR\\FLOPPY.IMG\r\n$')
for pos,target,kind in fixups:
 if kind=='rel8':
  n=labels[target]-(pos+1)
  if not -128<=n<=127:raise ValueError(target)
  code[pos]=n&255
 else:
  v=labels[target]+(0x100 if kind=='addr' else -(pos+2))
  code[pos:pos+2]=(v&0xffff).to_bytes(2,'little')
p=Path(__file__).with_name('DISK.COM');p.write_bytes(code);print(p,len(code))
