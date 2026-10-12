#!/usr/bin/env python3
"""Import the contents of five DOS floppy images into a FAT16 drive image.

All-or-nothing destination update; read-only access to floppy images.
Python 3.9+, stdlib only. Requires ../BB_FAT16_TOOL/fat16tool.py.
"""
import argparse
import importlib.util
import os
import struct
import sys
from pathlib import Path

class FloppyError(ValueError): pass

def u16(b,p):return struct.unpack_from('<H',b,p)[0]
def u32(b,p):return struct.unpack_from('<I',b,p)[0]

class DOSFloppy:
    def __init__(self,path):
        self.path=Path(path)
        self.data=self.path.read_bytes()
        b=self.data
        if len(b)<512 or b[510:512]!=b'\x55\xaa':raise FloppyError(f'{path}: missing DOS boot sector signature')
        self.bps=u16(b,11);self.spc=b[13];self.res=u16(b,14);self.nfat=b[16];self.roots=u16(b,17)
        self.total=u16(b,19) or u32(b,32);self.fatsz=u16(b,22)
        if self.bps!=512 or self.spc==0 or self.spc&(self.spc-1) or self.res==0 or self.nfat not in (1,2) or self.fatsz==0 or self.roots==0:
            raise FloppyError(f'{path}: unsupported BPB; expected FAT12/16 raw floppy image')
        self.rootsecs=(self.roots*32+511)//512
        self.data0=self.res+self.nfat*self.fatsz+self.rootsecs
        if self.total*512!=len(b) or self.data0>=self.total:raise FloppyError(f'{path}: invalid image size/geometry; got {len(b)}, BPB expects {self.total*512}')
        self.clusters=(self.total-self.data0)//self.spc
        if self.clusters<4085:self.bits=12
        elif self.clusters<65525:self.bits=16
        else:raise FloppyError(f'{path}: unsupported filesystem cluster count {self.clusters}')
        self.fat_off=self.res*512
        self.root_off=(self.res+self.nfat*self.fatsz)*512
    def fat(self,c):
        if self.bits==16:return u16(self.data,self.fat_off+2*c)
        off=self.fat_off+(3*c)//2
        v=u16(self.data,off)
        return (v>>4 if c&1 else v&0xfff)
    def chain(self,c):
        seen=set()
        while 2<=c<self.clusters+2:
            if c in seen:raise FloppyError(f'{self.path}: FAT chain cycle at {c}')
            seen.add(c);yield c
            c=self.fat(c)
            if c >= (0xff8 if self.bits==12 else 0xfff8):return
            if c<2 or c==(0xff7 if self.bits==12 else 0xfff7):raise FloppyError(f'{self.path}: invalid FAT link {c}')
        raise FloppyError(f'{self.path}: chain outside volume')
    def contents(self,start,size):
        if size==0:return b''
        if start<2:raise FloppyError(f'{self.path}: nonempty file with zero cluster')
        out=bytearray(); n=self.spc*512
        for c in self.chain(start):
            pos=(self.data0+(c-2)*self.spc)*512
            out.extend(self.data[pos:pos+n])
            if len(out)>=size:return bytes(out[:size])
        raise FloppyError(f'{self.path}: truncated file chain')
    def entries(self,cluster=None):
        if cluster is None:raw=self.data[self.root_off:self.root_off+self.roots*32]
        else:
            buf=bytearray();size=self.spc*512
            for c in self.chain(cluster):
                pos=(self.data0+(c-2)*self.spc)*512;buf.extend(self.data[pos:pos+size])
            raw=bytes(buf)
        for off in range(0,len(raw),32):
            e=raw[off:off+32]
            if len(e)<32 or e[0]==0:return
            if e[0] == 0xe5 or e[11]==0x0f or e[11]&0x08:continue
            base=e[:8].decode('cp437').rstrip();ext=e[8:11].decode('cp437').rstrip()
            name=base+('.'+ext if ext else '')
            if name in ('.','..'):continue
            yield name,bool(e[11]&0x10),u16(e,26),u32(e,28)
    def files(self):
        def walk(cluster,prefix,depth):
            if depth>16:raise FloppyError(f'{self.path}: directory nesting too deep')
            for name,isdir,start,size in self.entries(cluster):
                # Explicitly enforce destination tool's DOS 8.3 constraints, avoiding silent conversion.
                path=prefix+name
                if isdir:
                    yield path,None
                    yield from walk(start,path+'/',depth+1)
                else:yield path,self.contents(start,size)
        yield from walk(None,'',0)

def load_fat16(path):
    spec=importlib.util.spec_from_file_location('bb_fat16tool',path)
    if not spec or not spec.loader:raise RuntimeError(f'Cannot load FAT16 manager: {path}')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    return m

def main():
    ap=argparse.ArgumentParser(description='Import 5 Descent floppy disk contents into C:/DESCENT/DISK1..5')
    ap.add_argument('--games',default=r'C:\blitzBUS\games',help='Folder containing descent_disk1.img through descent_disk5.img')
    ap.add_argument('--image',default=r'O:\BLITZBUS\DRIVE_C.IMG',help='FAT16 image to update')
    ap.add_argument('--fat-tool',default=None,help='Path to existing fat16tool.py')
    ap.add_argument('--dry-run',action='store_true',help='Analyze images, do not edit')
    a=ap.parse_args()
    here=Path(__file__).resolve().parent
    fat_tool=Path(a.fat_tool) if a.fat_tool else here.parent/'BB_FAT16_TOOL'/'fat16tool.py'
    tool=load_fat16(fat_tool)
    games=Path(a.games)
    floppies=[]
    for i in range(1,6):
        f=DOSFloppy(games/f'descent_disk{i}.img')
        entries=list(f.files())
        floppies.append(entries)
        print(f'DISK{i}: {f.total*512:,} bytes, FAT{f.bits}, {len(entries)} entries, {sum(len(v) for _,v in entries if v is not None):,} file bytes')
        for rel,content in entries:
            print('  '+rel+(' <DIR>' if content is None else f' ({len(content)} bytes)'))
    if a.dry_run:
        print('DRY RUN: no destination image modified');return
    p=Path(a.image)
    if not p.is_file():raise FileNotFoundError(f'Destination FAT16 image not found: {p}')
    fat=tool.FAT16(bytearray(p.read_bytes()))
    print(f'Destination FAT16: {len(fat.d):,} bytes, available clusters {sum(fat.fat(c)==0 for c in range(2,fat.clusters+2))}')
    # Refuse to overwrite an existing Descent tree: safe repeatability.
    try:
        fat.resolve('DESCENT')
    except tool.FatError as e:
        if not str(e).startswith('Not found:'):raise
    else:
        raise tool.FatError('DESCENT directory already exists. Refusing to overwrite; export/backup and remove it first.')
    fat.mkdir('DESCENT')
    imported=0
    for i,entries in enumerate(floppies,1):
        root=f'DESCENT/DISK{i}';fat.mkdir(root)
        for rel,content in entries:
            dest=root+'/'+rel
            if content is None:fat.mkdir(dest)
            else:
                # Use FAT16's existing allocation + directory routines in memory, single atomic commit at end.
                # tempfile only needed for importfile's host path API.
                import tempfile
                with tempfile.NamedTemporaryFile(prefix='bb-descent-',delete=False) as t:
                    t.write(content);temp=Path(t.name)
                try:fat.importfile(temp,dest)
                finally:temp.unlink(missing_ok=True)
                imported+=1
    print(f'Import prepared: {imported} files, 5 disk directories')
    tool.save_atomic(p,fat.d)
    print('SUCCESS: C:/DESCENT/DISK1 through DISK5 populated; destination saved atomically')

if __name__=='__main__':
    try:main()
    except (OSError,ValueError,RuntimeError,Exception) as e:
        print('ERROR:',e,file=sys.stderr);sys.exit(1)
