#!/usr/bin/env python3
"""blitzBUS SD image helper (Python 3.9+, stdlib only). Pico OFF / SD in PC.

  grow-c        copy DRIVE_C.IMG into a larger FAT16 image (max 65520 sectors,
                31.99 MiB: DOS 2.x addresses sectors with 16-bit numbers)
  import-bench  copy the programs of a FAT12 floppy image (dosbench3d.img:
                T2ECPU.COM, 3DBENCH.EXE, ...) into a directory of DRIVE_C.IMG
                or of a partitioned hard disk image (DOS622_HDD.IMG)
  ls            list a FAT12 floppy image
  export12      copy one file out of a FAT12 image (BOOT.IMG, C: after make-c12)
  check-c       report FAT chains of DRIVE_C.IMG that leave the volume
  make-c12      build C: as FAT12 (MS-DOS 2.00 has no FAT16), from an old C:
                and/or host folders

Examples (PowerShell):
  python .\\tools\\sdtools.py grow-c O:\\BLITZBUS\\DRIVE_C.IMG --mb 32
  python .\\tools\\sdtools.py import-bench C:\\blitzBUS\\media\\dosbench3d.img O:\\BLITZBUS\\DRIVE_C.IMG BENCH
"""
import argparse, shutil, struct, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # fat16tool.py sits next to this file
import fat16tool as F                                             # noqa: E402

MAX_SECTORS = 65520           # 16-bit sector numbers (DOS 2.x request header, BPB)
SKIP = {'IO.SYS', 'MSDOS.SYS', 'IBMBIO.COM', 'IBMDOS.COM', 'COMMAND.COM'}


# ---- FAT12 floppy (read only) -----------------------------------------------
class FAT12:
    def __init__(self, data):
        b = data[:512]
        self.d = data
        self.bps, self.spc, self.res, self.nfat, self.roots = struct.unpack_from('<HBHBH', b, 11)
        self.tot = struct.unpack_from('<H', b, 19)[0] or struct.unpack_from('<I', b, 32)[0]
        self.spfat = struct.unpack_from('<H', b, 22)[0]
        if self.bps != 512 or not self.spc or not self.spfat:
            raise SystemExit('not a FAT12 floppy image')
        self.fat0 = self.res * 512
        self.root0 = (self.res + self.nfat * self.spfat) * 512
        self.data0 = self.root0 + ((self.roots * 32 + 511) // 512) * 512

    def fat(self, c):
        o = self.fat0 + c * 3 // 2
        v = self.d[o] | self.d[o + 1] << 8
        return v >> 4 if c & 1 else v & 0xFFF

    def chain(self, c):
        out = []
        while 2 <= c < 0xFF8 and len(out) < 4096:
            out.append(c)
            c = self.fat(c)
        return out

    def entries(self, cluster=None):
        if cluster is None:
            raw = self.d[self.root0:self.root0 + self.roots * 32]
        else:
            raw = b''.join(self.d[self.data0 + (c - 2) * self.spc * 512:
                                  self.data0 + (c - 1) * self.spc * 512] for c in self.chain(cluster))
        for i in range(0, len(raw), 32):
            e = raw[i:i + 32]
            if e[0] == 0:
                break
            if e[0] == 0xE5 or e[11] & 0x08 or e[11] == 0x0F:
                continue
            yield e

    def read(self, e):
        size = struct.unpack_from('<I', e, 28)[0]
        cl = struct.unpack_from('<H', e, 26)[0]
        b = b''.join(self.d[self.data0 + (c - 2) * self.spc * 512:
                            self.data0 + (c - 1) * self.spc * 512] for c in self.chain(cl))
        return b[:size]


def name83(e):
    return F.showname(e[:11])


# ---- FAT16 helpers -------------------------------------------------------------
def walk16(fs, cluster, path=''):
    """yield (dos_path, is_dir, bytes|None) depth first"""
    for _, e in fs.items(cluster):
        n = F.showname(e[:11])
        if n in ('.', '..'):
            continue
        p = f'{path}/{n}' if path else n
        if e[11] & 0x10:
            yield p, True, None
            yield from walk16(fs, F.u16(e, 26), p)
        else:
            yield p, False, fs.filebytes(e)


def put_bytes(fs, dos_path, data):
    with tempfile.NamedTemporaryFile(delete=False) as t:
        t.write(data)
        tmp = t.name
    try:
        fs.importfile(tmp, dos_path, replace=True)
    finally:
        Path(tmp).unlink()


def mkdirs(fs, dos_path):
    parts = [p for p in dos_path.replace('\\', '/').split('/') if p]
    for i in range(len(parts)):
        sub = '/'.join(parts[:i + 1])
        try:
            fs.resolve(sub)
        except F.FatError:
            fs.mkdir(sub)


# ---- commands ------------------------------------------------------------------
def check_c(args):
    """Report FAT chains that leave the volume (what stopped the file-copy grow)."""
    fs = F.FAT16(bytearray(Path(args.image).read_bytes()))
    bad = 0
    def walk(cluster, path):
        nonlocal bad
        for _, e in fs.items(cluster):
            n = F.showname(e[:11])
            if n in ('.', '..'):
                continue
            p = f'{path}/{n}' if path else n
            c = F.u16(e, 26)
            seen, k, cur = set(), 0, c
            while 2 <= cur < fs.clusters + 2 and cur not in seen:
                seen.add(cur); k += 1; cur = fs.fat(cur)
            if c and not (cur >= 0xFFF8 or (cur == 0 and k == 0)):
                bad += 1
                print(f'  BAD  {p}: chain from {c} ends at {cur:#06x} after {k} clusters '
                      f'(size {F.u32(e, 28)}, volume has {fs.clusters} clusters)')
            if e[11] & 0x10 and c:
                walk(c, p)
    walk(None, '')
    vals = {}
    for c in range(2, fs.clusters + 2):
        v = fs.fat(c)
        if fs.clusters + 2 <= v < 0xFFF0:
            vals[v] = vals.get(v, 0) + 1
    print(f'{bad} file(s) with broken chains; out-of-range FAT values: '
          + (', '.join(f'{v:#06x} x{n}' for v, n in sorted(vals.items())) or 'none'))


def grow_c(args):
    src = Path(args.image)
    old = F.FAT16(bytearray(src.read_bytes()))
    tot = min(args.mb * 2048, MAX_SECTORS)
    if tot <= old.tot:
        raise SystemExit(f'image already has {old.tot} sectors; nothing to do (max {MAX_SECTORS})')
    newclusters = (tot - old.firstdata) // old.spc
    if (newclusters + 2) * 2 <= old.spfat * 512:
        # The existing FAT already covers the larger volume (30 -> 32 MiB with
        # 64-sector FATs): extend in place. Every byte of the old image stays
        # where it is - no file parsing, so even a damaged chain survives as is.
        img = bytearray(old.d) + bytearray((tot - old.tot) * 512)
        struct.pack_into('<H', img, 19, tot)
        for i in range(old.nfat):                 # the new clusters start out free
            base = (old.res + i * old.spfat) * 512
            for c in range(old.clusters + 2, newclusters + 2):
                struct.pack_into('<H', img, base + 2 * c, 0)
        out = Path(args.out) if args.out else src
        if not args.out:
            bak = src.with_suffix('.BAK')
            shutil.copyfile(src, bak)
            print(f'backup: {bak}')
        F.save_atomic(out, bytes(img))
        new = F.FAT16(img)
        free = sum(new.fat(c) == 0 for c in range(2, new.clusters + 2)) * new.spc * 512
        print(f'{out}: extended in place to {tot} sectors ({tot * 512:,} bytes), '
              f'{new.clusters} clusters, {free:,} bytes free')
        print('Firmware must read C: geometry from the image (blitzBUS sd_boot r2 or later).')
        return
    spc, res, nfat, roots = old.spc, old.res, old.nfat, old.roots
    rootsec = (roots * 32 + 511) // 512
    spfat = 1
    while True:                                   # smallest FAT that covers the clusters
        clusters = (tot - res - nfat * spfat - rootsec) // spc
        if (clusters + 2) * 2 <= spfat * 512:
            break
        spfat += 1
    if not 4085 <= clusters < 65525:
        raise SystemExit(f'geometry is not FAT16 ({clusters} clusters)')
    boot = bytearray(old.d[:512])                 # same boot code / OEM / media byte
    struct.pack_into('<H', boot, 19, tot)
    struct.pack_into('<H', boot, 22, spfat)
    struct.pack_into('<I', boot, 32, 0)
    img = bytearray(tot * 512)
    img[:512] = boot
    media = boot[21]
    for i in range(nfat):                         # FAT[0], FAT[1]
        o = (res + i * spfat) * 512
        struct.pack_into('<HH', img, o, 0xFF00 | media, 0xFFFF)
    new = F.FAT16(img)
    n = 0
    for p, isdir, data in walk16(old, None):
        if isdir:
            new.mkdir(p)
        else:
            put_bytes(new, p, data)
            n += 1
    out = Path(args.out) if args.out else src
    if not args.out:
        bak = src.with_suffix('.BAK')
        shutil.copyfile(src, bak)
        print(f'backup: {bak}')
    F.save_atomic(out, bytes(new.d))
    free = sum(new.fat(c) == 0 for c in range(2, new.clusters + 2)) * spc * 512
    print(f'{out}: {tot} sectors ({tot * 512:,} bytes), {new.clusters} clusters, '
          f'FAT {spfat} sectors, {n} files copied, {free:,} bytes free')
    print('Firmware must read C: geometry from the image (blitzBUS sd_boot r2 or later).')


def load_fat16(path):
    """(whole image, byte offset, FAT16) for a superfloppy or an MBR-partitioned
    disk image (first FAT16 partition, e.g. DOS622_HDD.IMG)."""
    whole = bytearray(Path(path).read_bytes())
    try:
        return whole, 0, F.FAT16(whole)
    except F.FatError:
        pass
    if whole[510:512] != b'\x55\xaa':
        raise SystemExit(f'{path}: neither a FAT16 volume nor an MBR disk')
    for i in range(4):
        e = whole[446 + 16 * i:462 + 16 * i]
        if e[4] in (0x04, 0x06, 0x0E):
            start = struct.unpack_from('<I', e, 8)[0] * 512
            bs = whole[start:start + 512]
            tot = struct.unpack_from('<H', bs, 19)[0] or struct.unpack_from('<I', bs, 32)[0]
            vol = bytearray(whole[start:start + tot * 512])
            return whole, start, F.FAT16(vol)
    raise SystemExit(f'{path}: no FAT16 partition in the MBR')


def save_fat16(path, whole, off, fs):
    whole[off:off + len(fs.d)] = fs.d
    F.save_atomic(Path(path), bytes(whole))


def import_bench(args):
    fl = FAT12(Path(args.floppy).read_bytes())
    cpath = Path(args.c_image)
    whole, off, fs = load_fat16(cpath)
    mkdirs(fs, args.dest)
    n = 0
    for e in fl.entries():
        if e[11] & 0x10:
            continue
        nm = name83(e)
        if nm.upper() in SKIP:
            continue
        put_bytes(fs, f'{args.dest}/{nm}', fl.read(e))
        print(f'  {args.dest}\\{nm}')
        n += 1
    save_fat16(cpath, whole, off, fs)
    print(f'{n} files imported into C:\\{args.dest}')


# ---- FAT12 hard-disk image builder ------------------------------------------------
def build_fat12(tot, files, label_src_boot=None):
    """files: list of (dos_path, bytes or None for dir). Returns image bytes.
    Cluster size: smallest power of two that keeps <= 4084 clusters (FAT12)."""
    res, nfat, roots, media = 1, 2, 512, 0xF8
    rootsec = roots * 32 // 512
    spc = 1
    while True:
        spfat = 1
        while True:
            clusters = (tot - res - nfat * spfat - rootsec) // spc
            if ((clusters + 2) * 3 + 1) // 2 <= spfat * 512:
                break
            spfat += 1
        if clusters <= 4084:
            break
        over = (clusters - 4084) * spc
        if over * 50 < tot:                       # <2% over: trim the volume, keep the smaller cluster
            tot -= over
            continue
        spc *= 2
    tot = res + nfat * spfat + rootsec + clusters * spc
    img = bytearray(tot * 512)
    if label_src_boot:
        img[:512] = label_src_boot[:512]
    else:
        img[0:3] = b'\xEB\x3C\x90'; img[3:11] = b'BLITZBUS'; img[510:512] = b'\x55\xAA'
    struct.pack_into('<HBHBHHBH', img, 11, 512, spc, res, nfat, roots, tot, media, spfat)
    struct.pack_into('<HHHI', img, 24, 17, 4, 0, 0)     # geometry fields (unused by the emulator)
    struct.pack_into('<I', img, 32, 0)
    img[54:62] = b'FAT12   '
    fat = [0] * (clusters + 2)
    fat[0], fat[1] = 0xF00 | media, 0xFFF
    data0 = res + nfat * spfat + rootsec
    cl_bytes = spc * 512
    nxt = [2]

    def alloc(nbytes):
        n = max(1, (nbytes + cl_bytes - 1) // cl_bytes)
        if nxt[0] + n > clusters + 2:
            raise SystemExit('C: image full')
        first = nxt[0]
        for i in range(n):
            fat[first + i] = first + i + 1 if i + 1 < n else 0xFFF
        nxt[0] += n
        return first

    def put(cl, data):
        o = (data0 + (cl - 2) * spc) * 512
        img[o:o + len(data)] = data

    def ent(name, attr, cl, size):
        e = bytearray(32)
        e[0:11] = F.dosname(name); e[11] = attr
        struct.pack_into('<HHHI', e, 22, 0, 0x0021, cl, size)   # time 0, date 1980-01-01
        return bytes(e)

    # directory tree
    tree = {'': []}
    for path, data in files:
        parent, _, name = path.replace('\\', '/').rpartition('/')
        tree.setdefault(parent, []).append((name, data, path))
        if data is None:
            tree.setdefault(path, [])
    dircl = {'': None}

    def emit_dir(path, parent_cl):
        kids = tree.get(path, [])
        entries = []
        if path:
            n = len(kids) + 2
            cl = alloc(n * 32)
            dircl[path] = cl
            entries += [ent('.', 0x10, cl, 0), ent('..', 0x10, parent_cl or 0, 0)]
        for name, data, full in kids:
            if data is None:
                emit_dir(full, dircl[path])
                entries.append(ent(name, 0x10, dircl[full], 0))
            else:
                cl = alloc(len(data)) if data else 0
                if data:
                    put(cl, data)
                entries.append(ent(name, 0x20, cl, len(data)))
        raw = b''.join(entries)
        if path:
            put(dircl[path], raw)
        else:
            if len(entries) > roots:
                raise SystemExit('root directory full')
            o = (res + nfat * spfat) * 512
            img[o:o + len(raw)] = raw

    emit_dir('', None)
    packed = bytearray(spfat * 512)
    for c, v in enumerate(fat):
        o = c * 3 // 2
        if c & 1:
            packed[o] = (packed[o] & 0x0F) | (v & 0x0F) << 4; packed[o + 1] = v >> 4 & 0xFF
        else:
            packed[o] = v & 0xFF; packed[o + 1] = (packed[o + 1] & 0xF0) | (v >> 8 & 0x0F)
    for i in range(nfat):
        o = (res + i * spfat) * 512
        img[o:o + len(packed)] = packed
    return bytes(img), spc, clusters, (clusters + 2 - nxt[0]) * cl_bytes, tot


def _is_fat12(path):
    b = path.read_bytes()[:512]
    spc, res, nfat, roots, tot, _, spfat = struct.unpack_from('<BHBHHBH', b, 13)
    tot = tot or struct.unpack_from('<I', b, 32)[0]
    clusters = (tot - res - nfat * spfat - (roots * 32 + 511) // 512) // max(spc, 1)
    return clusters < 4085


def make_c12(args):
    """Rebuild C: as FAT12 (what MS-DOS 2.00 actually implements)."""
    files, skipped = [], []
    if args.from_c and _is_fat12(Path(args.from_c)):
        fl = FAT12(Path(args.from_c).read_bytes())
        def walk12(cluster, path):
            for e in fl.entries(cluster):
                n = name83(e)
                if n in ('.', '..'):
                    continue
                p = f'{path}/{n}' if path else n
                if e[11] & 0x10:
                    files.append((p, None))
                    walk12(struct.unpack_from('<H', e, 26)[0], p)
                else:
                    files.append((p, fl.read(e)))
        walk12(None, '')
    elif args.from_c:
        old = F.FAT16(bytearray(Path(args.from_c).read_bytes()))
        def walk(cluster, path):
            for _, e in old.items(cluster):
                n = F.showname(e[:11])
                if n in ('.', '..'):
                    continue
                p = f'{path}/{n}' if path else n
                if e[11] & 0x10:
                    files.append((p, None))
                    walk(F.u16(e, 26), p)
                else:
                    try:
                        files.append((p, old.filebytes(e)))
                    except F.FatError as x:
                        skipped.append(f'{p} ({x})')
        walk(None, '')
    for spec in args.add or []:                    # HOSTDIR=DOSDIR or HOSTFILE=DOSPATH
        host, _, dos = spec.partition('=')
        hp = Path(host)
        dos = dos.strip('/\\').upper().replace('\\', '/')
        if hp.is_dir():
            parts = [x for x in dos.split('/') if x]
            for i in range(len(parts)):
                d = '/'.join(parts[:i + 1])
                if (d, None) not in files:
                    files.append((d, None))
            for f in sorted(hp.rglob('*')):
                rel = f.relative_to(hp).as_posix().upper()
                p = f'{dos}/{rel}' if dos else rel
                files[:] = [x for x in files if x[0] != p]
                files.append((p, None) if f.is_dir() else (p, f.read_bytes()))
        else:
            files[:] = [x for x in files if x[0] != dos]
            files.append((dos, hp.read_bytes()))
    tot = min(args.mb * 2048, MAX_SECTORS)
    img, spc, clusters, free, tot = build_fat12(tot, files)
    out = Path(args.out)
    F.save_atomic(out, img)
    for s in skipped:
        print(f'  SKIPPED (broken chain): {s}')
    print(f'{out}: FAT12, {tot} sectors ({tot * 512:,} bytes), {spc}-sector ({spc * 512 // 1024} KiB) clusters, '
          f'{clusters} clusters, {sum(1 for f in files if f[1] is not None)} files, {free:,} bytes free')


def export12(args):
    fl = FAT12(Path(args.image).read_bytes())
    cl = None
    parts = [x.upper() for x in args.dos_path.replace('\\', '/').split('/') if x]
    for i, part in enumerate(parts):
        for e in fl.entries(cl):
            if name83(e) == part:
                break
        else:
            raise SystemExit('not found: ' + args.dos_path)
        if i + 1 < len(parts):
            cl = struct.unpack_from('<H', e, 26)[0]
    Path(args.host_path).write_bytes(fl.read(e))
    print(f'{args.dos_path} -> {args.host_path}')


def ls12(args):
    fl = FAT12(Path(args.floppy).read_bytes())
    for e in fl.entries():
        print(f'{name83(e):<13} {"<DIR>" if e[11] & 0x10 else "":5} {struct.unpack_from("<I", e, 28)[0]:>8}')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    g = sub.add_parser('grow-c'); g.add_argument('image'); g.add_argument('--mb', type=int, default=32)
    g.add_argument('--out', help='write here instead of replacing IMAGE (default: replace, keep .BAK)')
    b = sub.add_parser('import-bench'); b.add_argument('floppy'); b.add_argument('c_image'); b.add_argument('dest', nargs='?', default='BENCH')
    l = sub.add_parser('ls'); l.add_argument('floppy')
    k = sub.add_parser('check-c'); k.add_argument('image')
    x = sub.add_parser('export12'); x.add_argument('image'); x.add_argument('dos_path'); x.add_argument('host_path')
    m = sub.add_parser('make-c12'); m.add_argument('out'); m.add_argument('--from-c', help='copy files from this FAT16 image')
    m.add_argument('--add', action='append', help='HOSTDIR=DOSDIR or HOSTFILE=DOSPATH (repeatable; replaces same names)')
    m.add_argument('--mb', type=int, default=32)
    a = ap.parse_args()
    {'grow-c': grow_c, 'import-bench': import_bench, 'ls': ls12, 'check-c': check_c, 'make-c12': make_c12, 'export12': export12}[a.cmd](a)


if __name__ == '__main__':
    main()
