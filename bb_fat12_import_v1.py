#!/usr/bin/env python3
"""Safe FAT12 image importer for blitzBUS DRIVE_C.IMG (MS-DOS 2.00).

Usage from C:\\blitzBUS (Pico stopped; image not mounted anywhere):
  python bb_fat12_import_v1.py info
  python bb_fat12_import_v1.py import RCXTEST.COM BENCH/RCXTEST.COM
  python bb_fat12_import_v1.py verify RCXTEST.COM BENCH/RCXTEST.COM

Default image: O:/BLITZBUS/DRIVE_C.IMG
Backup: timestamped full image copy in the current directory (never overwritten).

Standard-library only; preserves boot sector and FAT12 layout. Supports FAT12 only.
"""
from __future__ import annotations
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile
from datetime import datetime

class ImageError(Exception):
    pass

def rd16(d, o): return struct.unpack_from('<H', d, o)[0]
def rd32(d, o): return struct.unpack_from('<I', d, o)[0]
def wr16(d, o, v): struct.pack_into('<H', d, o, v)
def wr32(d, o, v): struct.pack_into('<I', d, o, v)

def dos83(name):
    s = name.upper()
    if s in ('.', '..'):
        return s.encode('ascii').ljust(11, b' ')
    p = s.split('.')
    if len(p) > 2:
        raise ImageError('Not an 8.3 DOS filename: ' + name)
    a, ext = p[0], p[1] if len(p) == 2 else ''
    bad = '"*+,/:;<=>?[\\]|'
    if not (1 <= len(a) <= 8 and len(ext) <= 3) or any((ord(c) < 33 or ord(c) > 126 or c in bad) for c in a + ext):
        raise ImageError('Not an 8.3 DOS filename: ' + name)
    return (a.ljust(8) + ext.ljust(3)).encode('ascii')

class FAT12:
    def __init__(self, d):
        self.d = d
        if len(d) < 512 or d[510:512] != b'\x55\xaa':
            raise ImageError('No valid raw FAT boot sector; only superfloppy images are supported')
        self.bps = rd16(d, 11)
        self.spc = d[13]
        self.res = rd16(d, 14)
        self.nfats = d[16]
        self.root_entries = rd16(d, 17)
        self.total = rd16(d, 19) or rd32(d, 32)
        self.media = d[21]
        self.fat_sectors = rd16(d, 22)
        if self.bps != 512 or self.spc not in (1,2,4,8,16,32,64,128) or self.res < 1 or self.nfats not in (1, 2) or not self.root_entries or not self.fat_sectors:
            raise ImageError('Unsupported FAT geometry')
        self.root_sectors = (self.root_entries * 32 + 511) // 512
        self.data_sector = self.res + self.nfats * self.fat_sectors + self.root_sectors
        if self.total <= self.data_sector:
            raise ImageError('Invalid FAT image geometry')
        self.clusters = (self.total - self.data_sector) // self.spc
        if self.clusters >= 4085 or self.clusters < 1:
            raise ImageError(f'Not FAT12: {self.clusters} clusters (this importer only handles FAT12)')
        if len(d) != self.total * 512:
            raise ImageError(f'Image file size mismatch: expected {self.total * 512:,} bytes, got {len(d):,}')
        if ((self.clusters+2)*3+1)//2 > self.fat_sectors * 512:
            raise ImageError('FAT too small for the declared cluster count')
        self.fat_start = self.res * 512
        self.root_start = (self.res + self.nfats * self.fat_sectors) * 512
        self.cl_bytes = self.spc * 512
        if self.fat(0) != (0xF00 | self.media) or self.fat(1) < 0xFF8:
            raise ImageError('FAT12 reserved entries mismatch; refusing to edit')
        for i in range(1, self.nfats):
            other = self.fat_start + i * self.fat_sectors * 512
            if d[other:other + self.fat_sectors * 512] != d[self.fat_start:self.fat_start + self.fat_sectors * 512]:
                raise ImageError('The FAT copies differ. Repair the image before importing.')

    def off(self, c):
        if not 2 <= c < self.clusters + 2:
            raise ImageError(f'Out-of-range FAT12 cluster {c}')
        return (self.data_sector + (c - 2) * self.spc) * 512

    def fat(self, c):
        o = self.fat_start + (c * 3) // 2
        v = self.d[o] | self.d[o + 1] << 8
        return (v >> 4) if (c & 1) else (v & 0xFFF)

    def setfat(self, c, value):
        if not 2 <= c < self.clusters + 2:
            raise ImageError(f'Invalid FAT12 cluster {c}')
        if not 0 <= value <= 0xFFF:
            raise ImageError('Invalid FAT12 value')
        for n in range(self.nfats):
            o = self.fat_start + n * self.fat_sectors * 512 + c * 3 // 2
            old = self.d[o] | self.d[o+1] << 8
            v = ((old & 0x000F) | (value << 4)) if (c & 1) else ((old & 0xF000) | value)
            self.d[o], self.d[o+1] = v & 255, (v >> 8) & 255

    def chain(self, start):
        if start == 0:
            return []
        out, seen, c = [], set(), start
        while True:
            if not 2 <= c < self.clusters + 2 or c in seen:
                raise ImageError(f'Broken or cyclic FAT12 chain at {c}')
            seen.add(c)
            out.append(c)
            n = self.fat(c)
            if n >= 0xFF8:
                return out
            if n < 2 or n == 0xFF7 or n >= 0xFF0:
                raise ImageError(f'Broken FAT12 chain: {c} -> {n:#x}')
            c = n

    def alloc(self, count):
        if not count:
            return []
        free = []
        for i in range(2, self.clusters + 2):
            if self.fat(i) == 0:
                free.append(i)
                if len(free) == count:
                    break
        if len(free) < count:
            raise ImageError(f'Not enough free space: need {count} clusters, found {len(free)}')
        for n, c in enumerate(free):
            self.setfat(c, free[n+1] if n+1<len(free) else 0xFFF)
        return free

    def release(self, start):
        for c in self.chain(start):
            self.setfat(c, 0)

    def directory_slots(self, cluster):
        if cluster is None:
            return [self.root_start + i*32 for i in range(self.root_entries)]
        return [self.off(c)+i*32 for c in self.chain(cluster) for i in range(self.cl_bytes//32)]

    def find(self, parent, name):
        target = dos83(name)
        for o in self.directory_slots(parent):
            ent = self.d[o:o+32]
            if ent[0] == 0:
                break
            if ent[0] in (0xE5,) or ent[11] == 0x0F or ent[11] & 8:
                continue
            if ent[:11] == target:
                return o, ent
        return None

    def slot(self, parent):
        for o in self.directory_slots(parent):
            if self.d[o] in (0, 0xE5):
                return o
        if parent is None:
            raise ImageError('Root directory is full')
        c = self.chain(parent)
        new = self.alloc(1)[0]
        self.setfat(c[-1], new)
        self.d[self.off(new):self.off(new)+self.cl_bytes] = bytes(self.cl_bytes)
        return self.off(new)

    def put_entry(self, o, name, attr, cl, size):
        self.d[o:o+32] = bytes(32)
        self.d[o:o+11] = dos83(name)
        self.d[o+11] = attr
        wr16(self.d, o+24, 0x0021) # 1980-01-01
        wr16(self.d, o+26, cl)
        wr32(self.d, o+28, size)

    def mkdir(self, parent, name):
        if self.find(parent, name):
            raise ImageError('Directory already exists: '+name)
        slot = self.slot(parent)
        c = self.alloc(1)[0]
        start = self.off(c)
        self.d[start:start+self.cl_bytes] = bytes(self.cl_bytes)
        self.put_entry(start, '.', 0x10, c, 0)
        self.put_entry(start+32, '..', 0x10, parent or 0, 0)
        self.put_entry(slot, name, 0x10, c, 0)
        return c

    def resolve_parent(self, dest):
        names = [a for a in dest.replace('\\', '/').strip('/').split('/') if a]
        if not names:
            raise ImageError('Destination filename missing')
        parent = None
        for p in names[:-1]:
            ent = self.find(parent, p)
            if ent is None:
                parent = self.mkdir(parent, p)
            else:
                if not ent[1][11] & 0x10:
                    raise ImageError(f'Not a directory: {p}')
                parent = rd16(ent[1], 26)
        return parent, names[-1]

    def readfile(self, entry):
        size = rd32(entry,28)
        if size == 0:
            return b''
        cl = rd16(entry,26)
        chain = self.chain(cl)
        if len(chain) * self.cl_bytes < size:
            raise ImageError('File has a short FAT chain')
        return b''.join(self.d[self.off(c):self.off(c)+self.cl_bytes] for c in chain)[:size]

    def importfile(self, hostbytes, dest, replace):
        parent, name = self.resolve_parent(dest)
        old = self.find(parent, name)
        if old is not None and not replace:
            raise ImageError('Destination exists; add --replace to overwrite it')
        if old is not None and old[1][11] & 0x10:
            raise ImageError('Destination is a directory')
        # Reserve a directory entry and all new data before releasing old data.
        o = old[0] if old else self.slot(parent)
        count = (len(hostbytes) + self.cl_bytes - 1) // self.cl_bytes
        new = self.alloc(count)
        for n, c in enumerate(new):
            s = hostbytes[n*self.cl_bytes:(n+1)*self.cl_bytes]
            self.d[self.off(c):self.off(c)+self.cl_bytes] = s.ljust(self.cl_bytes, b'\0')
        if old is not None:
            self.release(rd16(old[1],26))
        self.put_entry(o, name, 0x20, new[0] if new else 0, len(hostbytes))
        now = self.find(parent, name)
        if now is None or self.readfile(now[1]) != hostbytes:
            raise ImageError('Read-back verification failed; original image was NOT modified')
        return count

def sha(b): return hashlib.sha256(b).hexdigest()

def main():
    p = argparse.ArgumentParser(description='FAT12 image importer for blitzBUS (Pico must be OFF; image must not be mounted)')
    p.add_argument('--image', default='O:/BLITZBUS/DRIVE_C.IMG', help='path to raw FAT12 image')
    p.add_argument('--backup-dir', default='.', help='where to save a full pre-import backup (default: current directory)')
    commands = p.add_subparsers(dest='command', required=True)
    commands.add_parser('info')
    q = commands.add_parser('import')
    q.add_argument('source')
    q.add_argument('dest')
    q.add_argument('--replace', action='store_true')
    v = commands.add_parser('verify')
    v.add_argument('source')
    v.add_argument('dest')
    args = p.parse_args()
    imagepath = Path(args.image)
    if not imagepath.is_file():
        raise ImageError(f'Image not found: {imagepath}')
    raw = imagepath.read_bytes()
    fs = FAT12(bytearray(raw))
    print(f'FAT12 image: {imagepath} | {fs.total:,} sectors | {fs.clusters} clusters | {fs.cl_bytes:,} bytes/cluster')
    if args.command == 'info':
        print(f'Root entries: {fs.root_entries} | FATs: {fs.nfats} | free clusters: {sum(fs.fat(c)==0 for c in range(2,fs.clusters+2))}')
        return
    source = Path(args.source)
    if not source.is_file():
        raise ImageError(f'Source file not found: {source}')
    data = source.read_bytes()
    if args.command == 'verify':
        parent = None
        names = [n for n in args.dest.replace('\\','/').strip('/').split('/') if n]
        for n in names[:-1]:
            ent = fs.find(parent,n)
            if not ent or not ent[1][11] & 0x10:
                raise ImageError('Directory not found: '+n)
            parent = rd16(ent[1],26)
        if not names:
            raise ImageError('No destination')
        ent = fs.find(parent,names[-1])
        if not ent or ent[1][11] & 0x10:
            raise ImageError('File not found: '+args.dest)
        saved = fs.readfile(ent[1])
        if saved != data:
            raise ImageError(f'Verification FAILED: image {sha(saved)} != source {sha(data)}')
        print(f'VERIFIED: {args.dest}, {len(data):,} bytes, SHA256 {sha(data)}')
        return
    # All validations, allocations and read-back verification run on an in-memory
    # image first: no disk image is touched until all of them succeed.
    clusters = fs.importfile(data, args.dest, args.replace)
    check = FAT12(fs.d)
    parent = None
    for seg in [v for v in args.dest.replace('\\','/').strip('/').split('/') if v][:-1]:
        parent = rd16(check.find(parent,seg)[1],26)
    if check.readfile(check.find(parent,args.dest.replace('\\','/').split('/')[-1])[1]) != data:
        raise ImageError('Post-import FAT12 verification failed; image not written')
    # Make the backup on the PC (default C:\\blitzBUS), not the SD card.
    backup_dir = Path(args.backup_dir)
    backup_dir.mkdir(parents=True,exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup = backup_dir / (imagepath.stem + '-before-import-' + stamp + '.IMG')
    with backup.open('xb') as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    print(f'BACKUP: {backup} ({len(raw):,} bytes)')
    fd, tmpname = tempfile.mkstemp(prefix='.bb-fat12-', suffix='.img.tmp', dir=str(imagepath.parent))
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(fs.d)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmpname, imagepath)
    finally:
        if os.path.exists(tmpname): os.unlink(tmpname)
    print(f'IMPORTED: {source} -> C:\\{args.dest.replace("/", chr(92))} ({len(data):,} bytes, {clusters} cluster(s))')
    print('VERIFY: python bb_fat12_import_v1.py verify ' + args.source + ' ' + args.dest)

if __name__ == '__main__':
    try:
        main()
    except (ImageError, OSError, ValueError, struct.error) as e:
        print('ERROR:', e, file=sys.stderr)
        sys.exit(1)
