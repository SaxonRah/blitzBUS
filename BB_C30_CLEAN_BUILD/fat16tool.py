#!/usr/bin/env python3
"""blitzBUS FAT16 superfloppy image manager. Python 3.9+, stdlib only."""
import argparse, os, struct, sys, tempfile, shutil
from pathlib import Path

class FatError(Exception): pass

def u16(b,o): return struct.unpack_from('<H',b,o)[0]
def u32(b,o): return struct.unpack_from('<I',b,o)[0]
def w16(b,o,v): struct.pack_into('<H',b,o,v)
def w32(b,o,v): struct.pack_into('<I',b,o,v)

def dosname(s):
    s=s.upper()
    if s in ('.','..'): return s.encode().ljust(11,b' ')
    if s.count('.')>1: raise FatError('Invalid 8.3 name: '+s)
    p=s.split('.'); base=p[0]; ext=p[1] if len(p)>1 else ''
    illegal='"*+,/:;<=>?[\\]|'
    if not (1<=len(base)<=8 and len(ext)<=3) or any(ord(c)<33 or ord(c)>126 or c in illegal for c in base+ext):
        raise FatError('Invalid DOS 8.3 name: '+s)
    return (base.ljust(8)+ext.ljust(3)).encode('ascii')

def showname(b):
    return b[:8].decode('cp437').rstrip() + (('.'+b[8:11].decode('cp437').rstrip()) if b[8:11].strip() else '')

class FAT16:
    def __init__(self, data):
        self.d=data; b=data[:512]
        if len(b)<512 or b[510:512]!=b'\x55\xaa': raise FatError('Missing FAT boot sector signature')
        self.bps=u16(b,11); self.spc=b[13]; self.res=u16(b,14); self.nfat=b[16]; self.roots=u16(b,17)
        self.tot=u16(b,19) or u32(b,32); self.spfat=u16(b,22)
        if self.bps!=512 or self.spc==0 or self.spc&(self.spc-1) or not self.nfat or not self.spfat or not self.roots: raise FatError('Unsupported FAT geometry')
        self.rootsec=(self.roots*32+511)//512
        self.fat0=self.res*512
        self.root0=(self.res+self.nfat*self.spfat)*512
        self.firstdata=self.res+self.nfat*self.spfat+self.rootsec
        self.clusters=(self.tot-self.firstdata)//self.spc
        if self.clusters<4085 or self.clusters>=65525: raise FatError(f'Not FAT16: {self.clusters} clusters')
        if len(data)!=self.tot*512: raise FatError(f'Image size mismatch: expected {self.tot*512}, got {len(data)}')
        if (self.clusters+2)*2>self.spfat*512: raise FatError('FAT too small')
    def off(self,c):
        if c<2 or c>=self.clusters+2: raise FatError('Invalid cluster '+str(c))
        return (self.firstdata+(c-2)*self.spc)*512
    def fat(self,c): return u16(self.d,self.fat0+c*2)
    def setfat(self,c,v):
        for i in range(self.nfat): w16(self.d,self.fat0+i*self.spfat*512+c*2,v)
    def chain(self,start):
        if start==0:return []
        seen=set(); out=[]; c=start
        while 2<=c<self.clusters+2:
            if c in seen: raise FatError('FAT cycle detected')
            seen.add(c);out.append(c); nxt=self.fat(c)
            if nxt>=0xfff8:return out
            if nxt==0 or nxt==0xfff7 or 0xfff0<=nxt<0xfff8: raise FatError('Broken FAT chain')
            c=nxt
        raise FatError('Out of range FAT chain')
    def alloc(self,count):
        free=[c for c in range(2,self.clusters+2) if self.fat(c)==0]
        if len(free)<count: raise FatError('Disk full')
        got=free[:count]
        for i,c in enumerate(got):self.setfat(c,got[i+1] if i+1<len(got) else 0xffff)
        return got
    def release(self,start):
        for c in self.chain(start):self.setfat(c,0)
    def dirs(self,cluster):
        if cluster is None: return [self.root0+i*32 for i in range(self.roots)]
        out=[]
        for c in self.chain(cluster): out.extend(range(self.off(c),self.off(c)+self.spc*512,32))
        return out
    def items(self,cluster):
        for off in self.dirs(cluster):
            ent=self.d[off:off+32]
            if ent[0]==0:break
            if ent[0] in (0xe5,) or ent[11]==0x0f or ent[11]&8: continue
            yield off,ent
    def find(self,cluster,name):
        target=dosname(name)
        for off,ent in self.items(cluster):
            if ent[:11]==target:return off,ent
        raise FatError('Not found: '+name)
    def parent(self,path):
        parts=[x for x in path.replace('\\','/').split('/') if x and x!='.']
        if not parts:raise FatError('Path required')
        parent=None
        for seg in parts[:-1]:
            _,ent=self.find(parent,seg)
            if not ent[11]&16: raise FatError('Not directory: '+seg)
            parent=u16(ent,26)
        return parent,parts[-1]
    def resolve(self,path):
        if path in ('','/','\\'):return None,None
        parent,name=self.parent(path);return self.find(parent,name)
    def slot(self,parent):
        for off in self.dirs(parent):
            if self.d[off] in (0,0xe5):return off
        if parent is None:raise FatError('Root directory full')
        cl=self.chain(parent);new=self.alloc(1)[0];self.setfat(cl[-1],new)
        self.d[self.off(new):self.off(new)+self.spc*512]=b'\0'*(self.spc*512)
        return self.off(new)
    def putent(self,off,name,attr,cluster,size):
        self.d[off:off+32]=bytes(32)
        self.d[off:off+11]=dosname(name);self.d[off+11]=attr
        w16(self.d,off+26,cluster);w32(self.d,off+28,size)
    def filebytes(self,ent):
        size=u32(ent,28);chain=self.chain(u16(ent,26))
        if size>len(chain)*self.spc*512:raise FatError('File truncated by FAT chain')
        return b''.join(self.d[self.off(c):self.off(c)+self.spc*512] for c in chain)[:size]
    def importfile(self,host,dest,replace=False):
        parent,name=self.parent(dest);dosname(name)
        old=None
        try:old=self.find(parent,name)
        except FatError:pass
        if old and not replace: raise FatError('File already exists; specify --replace')
        if old and old[1][11]&16:raise FatError('Cannot replace directory')
        raw=Path(host).read_bytes();size=self.spc*512;n=(len(raw)+size-1)//size
        # Reserve replacement data BEFORE releasing the old chain.
        new=self.alloc(n)
        for i,c in enumerate(new):
            chunk=raw[i*size:(i+1)*size];self.d[self.off(c):self.off(c)+size]=chunk.ljust(size,b'\0')
        if old:
            self.release(u16(old[1],26));off=old[0]
        else:off=self.slot(parent)
        self.putent(off,name,0x20,new[0] if new else 0,len(raw))
    def mkdir(self,path):
        parent,name=self.parent(path);dosname(name)
        try:self.find(parent,name);raise FatError('Already exists: '+path)
        except FatError as e:
            if not str(e).startswith('Not found:'):raise
        new=self.alloc(1)[0];off=self.off(new);size=self.spc*512
        self.d[off:off+size]=b'\0'*size
        self.putent(off,'.',0x10,new,0)
        self.putent(off+32,'..',0x10,parent or 0,0)
        self.putent(self.slot(parent),name,0x10,new,0)
    def delete(self,path):
        off,ent=self.resolve(path)
        if ent[11]&16:
            c=u16(ent,26)
            if any(showname(e[:11]) not in ('.','..') for _,e in self.items(c)):raise FatError('Directory not empty')
        self.release(u16(ent,26));self.d[off]=0xe5
    def listing(self,path):
        if path in ('','/','\\'):parent=None
        else:
            _,ent=self.resolve(path)
            if not ent[11]&16: raise FatError('Not a directory')
            parent=u16(ent,26)
        for _,ent in self.items(parent):
            name=showname(ent[:11]);typ='<DIR>' if ent[11]&16 else '     '
            print(f'{name:<13} {typ} {u32(ent,28):>10} bytes')
        free=sum(self.fat(c)==0 for c in range(2,self.clusters+2))
        print(f'{free*self.spc*512:,} bytes free')

def save_atomic(path,data):
    # Same-directory temporary file; preserve original if a write fails.
    p=Path(path); fd,name=tempfile.mkstemp(prefix='.blitzbus-',suffix='.img.tmp',dir=str(p.parent))
    try:
        with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(name,p)
    finally:
        if os.path.exists(name):os.unlink(name)

def main():
    pa=argparse.ArgumentParser(description='blitzBUS FAT16 image manager (Pico OFF / SD ejected required for edits)')
    pa.add_argument('--image',default='O:/BLITZBUS/DRIVE_C.IMG')
    sub=pa.add_subparsers(dest='cmd',required=True)
    x=sub.add_parser('ls');x.add_argument('path',nargs='?',default='/')
    x=sub.add_parser('export');x.add_argument('dos_path');x.add_argument('host_path')
    x=sub.add_parser('import');x.add_argument('host_path');x.add_argument('dos_path');x.add_argument('--replace',action='store_true')
    x=sub.add_parser('rm');x.add_argument('dos_path')
    x=sub.add_parser('mkdir');x.add_argument('dos_path')
    x=sub.add_parser('info')
    a=pa.parse_args();p=Path(a.image)
    if not p.is_file():pa.error('Image not found: '+str(p))
    fat=FAT16(bytearray(p.read_bytes()))
    if a.cmd=='ls':fat.listing(a.path)
    elif a.cmd=='info':print(f'FAT16 {fat.tot*512:,} bytes, {fat.clusters} clusters, {fat.spc*512} byte clusters, {fat.nfat} FATs')
    elif a.cmd=='export':
        _,ent=fat.resolve(a.dos_path)
        if ent[11]&16:raise FatError('Use export for files only')
        dest=Path(a.host_path)
        if dest.exists():raise FatError('Host destination already exists')
        dest.write_bytes(fat.filebytes(ent));print(f'Exported {a.dos_path} -> {dest}')
    else:
        print('IMPORTANT: Pico must be stopped and SD safely ejected from it. Editing image:',p)
        if a.cmd=='import':fat.importfile(a.host_path,a.dos_path,a.replace)
        elif a.cmd=='mkdir':fat.mkdir(a.dos_path)
        elif a.cmd=='rm':fat.delete(a.dos_path)
        save_atomic(p,fat.d);print('Updated image successfully')

if __name__=='__main__':
    try:main()
    except (FatError,OSError) as e:print('ERROR:',e,file=sys.stderr);sys.exit(1)
