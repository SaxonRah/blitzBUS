#!/usr/bin/env python3
"""Rebuild a 360KiB FAT12 DOS A: image containing only COMMAND.COM and DISK.COM.
Always operates on a copy; never modifies source. Stdlib Python 3.9+.
"""
import argparse, pathlib, struct, sys

def u16(b,o):return struct.unpack_from('<H',b,o)[0]
def u32(b,o):return struct.unpack_from('<I',b,o)[0]
def fat12(b,base,cl):
 p=base+(cl*3)//2
 v=u16(b,p)
 return (v>>4) if cl&1 else v&0xFFF

def setfat(b,base,cl,v):
 p=base+(cl*3)//2
 cur=u16(b,p)
 if cl&1:cur=(cur&0x000F)|((v&0xfff)<<4)
 else:cur=(cur&0xf000)|(v&0xfff)
 struct.pack_into('<H',b,p,cur)

def getfile(img,name):
 bps=u16(img,11);spc=img[13];res=u16(img,14);nfat=img[16];spf=u16(img,22);roots=u16(img,17)
 data_sec=res+nfat*spf+(roots*32+bps-1)//bps
 root=(res+nfat*spf)*bps
 fat=res*bps
 wanted=name.upper().split('.');raw=(wanted[0].ljust(8)+((wanted[1] if len(wanted)>1 else '').ljust(3))).encode()
 for j in range(roots):
  e=img[root+j*32:root+(j+1)*32]
  if e[0]==0:break
  if e[0]==0xe5 or e[11]&0x18 or e[:11]!=raw:continue
  size=u32(e,28);c=u16(e,26);buf=bytearray();seen=set()
  while len(buf)<size:
   if c<2 or c>=0xFF8 or c in seen:raise ValueError('Broken '+name+' cluster chain')
   seen.add(c);pos=(data_sec+(c-2)*spc)*bps
   buf.extend(img[pos:pos+spc*bps]);c=fat12(img,fat,c)
  return bytes(buf[:size])
 raise ValueError(name+' missing from source image')

def build(src, command, disk):
 original=bytearray(src);length=len(original)
 if length != 368640:raise ValueError('Expected 360 KiB BOOT.IMG')
 if original[510:512]!=b'\x55\xaa':raise ValueError('Invalid boot signature')
 bps=u16(original,11);spc=original[13];res=u16(original,14);nfat=original[16];spf=u16(original,22);roots=u16(original,17)
 if bps!=512 or not spc or nfat!=2 or u16(original,19)!=720:raise ValueError('Unsupported DOS floppy BPB')
 root_start=(res+nfat*spf)*bps;root_size=roots*32
 data_sec=res+nfat*spf+(root_size+bps-1)//bps
 capacity=(720-data_sec)//spc+2
 out=bytearray(original)
 out[res*bps:]=b'\0'*(length-res*bps)
 for i in range(nfat):
  o=(res+i*spf)*bps
  out[o]=original[o];out[o+1]=0xff;out[o+2]=0xff
 cursor=2
 for index,(name,blob,meta) in enumerate([('COMMAND.COM',command,0x20),('DISK.COM',disk,0x20)]):
  if len(blob)>65535 and name=='DISK.COM':raise ValueError('DISK.COM too large')
  chunks=(len(blob)+spc*bps-1)//(spc*bps)
  if cursor+chunks>capacity:raise ValueError('Minimal A: has insufficient space')
  for k in range(chunks):
   cl=cursor+k
   for n in range(nfat):setfat(out,(res+n*spf)*bps,cl,0xfff if k==chunks-1 else cl+1)
   pos=(data_sec+(cl-2)*spc)*bps
   out[pos:pos+spc*bps]=blob[k*spc*bps:(k+1)*spc*bps].ljust(spc*bps,b'\0')
  ent=root_start+index*32
  base,ext=name.split('.')
  out[ent:ent+11]=(base.ljust(8)+ext.ljust(3)).encode('ascii')
  out[ent+11]=meta
  struct.pack_into('<H',out,ent+26,cursor if chunks else 0)
  struct.pack_into('<I',out,ent+28,len(blob))
  cursor+=chunks
 return bytes(out)

def main():
 p=argparse.ArgumentParser(description='Make a minimal DOS A: floppy WITHOUT modifying original')
 p.add_argument('--source',required=True,help='Original BOOT.IMG')
 p.add_argument('--disk-com',required=True,help='DISK.COM executable (general-path version when available)')
 p.add_argument('--output',required=True,help='NEW output image; must not exist')
 a=p.parse_args();source=pathlib.Path(a.source);out=pathlib.Path(a.output)
 if out.exists():raise ValueError('Output already exists; will not overwrite: '+str(out))
 if out.resolve()==source.resolve():raise ValueError('Source and output must differ')
 original=source.read_bytes();command=getfile(original,'COMMAND.COM');disk=pathlib.Path(a.disk_com).read_bytes()
 if not disk:raise ValueError('Empty DISK.COM')
 image=build(original,command,disk)
 assert getfile(image,'COMMAND.COM')==command and getfile(image,'DISK.COM')==disk
 with out.open('xb') as f:f.write(image)
 print('Created:',out, 'bytes:',len(image));print('A: contains COMMAND.COM',len(command),'and DISK.COM',len(disk));print('Original BOOT.IMG untouched; test as separate image before replacing.')
if __name__=='__main__':
 try:main()
 except Exception as e:print('ERROR:',e,file=sys.stderr);sys.exit(1)
