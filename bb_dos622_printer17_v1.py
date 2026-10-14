#!/usr/bin/env python3
"""Reversible optional MS-DOS 6.22 BIOS INT17 printer probe fix.

Works with the installed IPL -> boot diag -> heap rescue -> stall watch ->
serial14 guard chain. Changes ONLY the DOS622 BIOS C include and installed
SHA manifests. Source, original backups and JIT remain unchanged otherwise.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile

HERE = Path(__file__).resolve().parent
TAG = 'BB_DOS622_PRINTER17_V1'
SRC = 'src/bb_live.c'
BIOS = 'src/bb_dos622_bios.inc'
SERIAL_INC = 'src/bb_dos622_serial14.inc'
WATCH_INC = 'src/bb_dos622_stall_watch.inc'
PRINTER_INC = 'src/bb_dos622_printer17.inc'
IPL = '.bb_dos622_ipl_v1_state/manifest.json'
DIAG = '.bb_dos622_boot_diag_v1_state/repair.json'
HEAP = '.bb_dos622_heap_rescue_v1_state/manifest.json'
WATCH = '.bb_dos622_stall_watch_v1_state/manifest.json'
SERIAL_STATE = '.bb_dos622_serial14_guard_v1_state'
SERIAL = SERIAL_STATE + '/manifest.json'
STATE = '.bb_dos622_printer17_v1_state'


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def jsonbytes(obj: dict) -> bytes:
    return json.dumps(obj, indent=2).encode('utf8')


def add_after_line(source: bytes, pattern: bytes, text: bytes, label: str) -> bytes:
    matches = list(re.finditer(pattern, source, re.M))
    if len(matches) != 1:
        nearby = [line[:160] for line in source.splitlines() if
                  (b'serial14' in line or b'case 0x14u:' in line)][:6]
        raise ValueError(f'{label}: expected one exact source line; found {len(matches)}; nearby={nearby!r}')
    m = matches[0]
    nl = m.group('nl') or b'\n'
    return source[:m.end()] + text.replace(b'@NL@', nl) + source[m.end():]


def transform_bios(old: bytes) -> bytes:
    if TAG.encode() in old or b'#include "bb_dos622_printer17.inc"' in old:
        raise ValueError('printer17 is already installed in BIOS source')
    data = add_after_line(old,
        rb'^[ \t]*#include "bb_dos622_serial14\.inc"(?P<nl>\r\n|\n|\r|$)',
        b'/* ' + TAG.encode() + b' */@NL@#include "bb_dos622_printer17.inc"@NL@',
        'serial14 include')
    data = add_after_line(data,
        rb'^[ \t]*case 0x14u: return bb622_serial14\(rt\);(?P<nl>\r\n|\n|\r|$)',
        b'    case 0x17u: return bb622_printer17(rt);@NL@',
        'serial14 switch case')
    return data


def read_chain(root: Path):
    rels = (SRC, BIOS, SERIAL_INC, WATCH_INC, IPL, DIAG, HEAP, WATCH, SERIAL)
    content = {p: (root / p).read_bytes() for p in rels}
    a, b, c, d, e = [json.loads(content[p]) for p in (IPL, DIAG, HEAP, WATCH, SERIAL)]
    tags = [a.get('tag'), b.get('tag'), c.get('tag'), d.get('tag'), e.get('tag')]
    expected = ['BB_DOS622_IPL_V1', 'BB_DOS622_BOOT_DIAG_V1',
                'BB_DOS622_HEAP_RESCUE_V1', 'BB_DOS622_STALL_WATCH_V1',
                'BB_DOS622_SERIAL14_GUARD_V1']
    if tags != expected:
        raise ValueError(f'installed manifest stages differ from expected: {tags!r}')
    # Check source references AND all cascading checksum dependencies.
    for p in (SRC, BIOS):
        if a['files'][p]['installed'] != sha(content[p]):
            raise ValueError(f'IPL checksum differs for {p}')
        if b['files'][p]['new'] != sha(content[p]):
            raise ValueError(f'boot diag checksum differs for {p}')
        if d['files'][p]['new'] != sha(content[p]):
            raise ValueError(f'stall watch checksum differs for {p}')
    if b['parent_after'] != sha(content[IPL]):
        raise ValueError('boot diag to IPL parent mismatch')
    for p in (SRC, IPL, DIAG):
        if c['files'][p]['after'] != sha(content[p]):
            raise ValueError(f'heap parent mismatch: {p}')
    for p in (WATCH_INC, IPL, DIAG, HEAP):
        if d['files'][p]['new'] != sha(content[p]):
            raise ValueError(f'stall watch parent mismatch: {p}')
    for p, item in e['files'].items():
        if sha((root/p).read_bytes()) != item['new']:
            raise ValueError(f'serial14 manifest checksum mismatch: {p}')
        if item['old'] is not None:
            backup = (root/SERIAL_STATE/item['backup']).read_bytes()
            if sha(backup) != item['old']:
                raise ValueError(f'serial14 saved original altered: {p}')
    if b'case 0x14u: return bb622_serial14(rt);' not in content[BIOS]:
        raise ValueError('serial14 code missing; refusing to install printer17')
    return content, a, b, c, d, e


def plan(root: Path, new_include: bytes):
    if (root/STATE).exists():
        raise ValueError('printer17 stage already present; use verify or restore')
    if (root/PRINTER_INC).exists():
        raise ValueError('printer17 include exists; refusing overwrite')
    old, a, b, c, d, e = read_chain(root)
    new_bios = transform_bios(old[BIOS])
    a['files'][BIOS]['installed'] = sha(new_bios)
    new_a = jsonbytes(a)
    b['files'][BIOS]['new'] = sha(new_bios)
    b['parent_after'] = sha(new_a)
    new_b = jsonbytes(b)
    c['files'][IPL]['after'] = sha(new_a)
    c['files'][DIAG]['after'] = sha(new_b)
    new_c = jsonbytes(c)
    d['files'][BIOS]['new'] = sha(new_bios)
    for rel, content in ((IPL,new_a), (DIAG,new_b), (HEAP,new_c)):
        d['files'][rel]['new'] = sha(content)
    new_d = jsonbytes(d)
    for rel, content in ((BIOS,new_bios), (IPL,new_a), (DIAG,new_b),
                         (HEAP,new_c), (WATCH,new_d)):
        e['files'][rel]['new'] = sha(content)
    new_e = jsonbytes(e)
    return {BIOS: (old[BIOS], new_bios), PRINTER_INC: (None, new_include),
            IPL:(old[IPL],new_a), DIAG:(old[DIAG],new_b),
            HEAP:(old[HEAP],new_c), WATCH:(old[WATCH],new_d),
            SERIAL:(old[SERIAL],new_e)}


def verify(root: Path):
    state = root/STATE
    manifest = json.loads((state/'manifest.json').read_text(encoding='utf8'))
    if manifest.get('tag') != TAG: raise ValueError('invalid printer17 stage manifest')
    for rel, info in manifest['files'].items():
        if sha((root/rel).read_bytes()) != info['new']:
            raise ValueError(f'installed checksum differs: {rel}')
        if info['old'] is not None and sha((state/info['backup']).read_bytes()) != info['old']:
            raise ValueError(f'rollback backup changed: {rel}')
    read_chain(root)
    bios = (root/BIOS).read_bytes()
    if b'#include "bb_dos622_printer17.inc"' not in bios or \
       b'case 0x17u: return bb622_printer17(rt);' not in bios:
        raise ValueError('printer17 BIOS dispatch not installed')
    print('VERIFIED: printer17, original backups, IPL/diag/heap/stall-watch/serial14 checksum chain')


def apply(root: Path, new_include: bytes):
    changes = plan(root, new_include)
    state = root/STATE
    state.mkdir()
    try:
        manifest = {'tag':TAG, 'files':{}}
        for i, (rel, (old,new)) in enumerate(changes.items()):
            backup = f'original_{i}.bin'
            manifest['files'][rel] = {
                'old': None if old is None else sha(old), 'new':sha(new), 'backup':backup}
            if old is not None: (state/backup).write_bytes(old)
        (state/'manifest.json').write_bytes(jsonbytes(manifest))
        for rel,(old,new) in changes.items():
            dest = root/rel
            if old is None and dest.exists():
                raise ValueError(f'new file unexpectedly exists: {rel}')
            if old is not None and dest.read_bytes() != old:
                raise ValueError(f'concurrent modification: {rel}')
            dest.write_bytes(new)
        verify(root)
    except Exception:
        for rel,(old,_) in changes.items():
            dest=root/rel
            if old is None: dest.unlink(missing_ok=True)
            else: dest.write_bytes(old)
        shutil.rmtree(state, ignore_errors=True)
        raise
    print('APPLIED: DOS622 BIOS INT17 no-printer response; null guard, 286 JIT and DOS2 untouched')


def restore(root: Path):
    verify(root)
    state=root/STATE
    manifest=json.loads((state/'manifest.json').read_text(encoding='utf8'))
    for rel,info in manifest['files'].items():
        dest=root/rel
        if info['old'] is None: dest.unlink()
        else: dest.write_bytes((state/info['backup']).read_bytes())
    shutil.rmtree(state)
    print('RESTORED: byte-exact BIOS, manifests and serial14 state; new include removed')


def selftest(include: bytes):
    bios = b'''/* BB_DOS622_STALL_WATCH_V1 */
#include "bb_dos622_serial14.inc"
static bool BB622_FLASH bb622_bios_interrupt(MdRuntime *rt, uint8_t vector, void *user)
{
    bb622_watch_bios(rt, vector);
    switch (vector) {
    case 0x13u: return bb622_int13(rt);
    case 0x14u: return bb622_serial14(rt);
    default: break;
    }
    if (md_msdos2_boot_interrupt(rt, vector, user)) return true;
    if (bb622_null_firmware_vector(rt, vector)) return true;
    return false;
}
'''
    variants = [
        ('LF',bios),
        ('CRLF',bios.replace(b'\n',b'\r\n')),
        ('MIXED',bios.replace(b'    case 0x14u: return bb622_serial14(rt);\n',
                              b'    case 0x14u: return bb622_serial14(rt);\r\n'))]
    src=b'/* untouched native 286 JIT */\n'
    ser=b'/* serial14 test include */\n'
    watchinc=b'/* watch include */\n'
    for label, initial_bios in variants:
        with tempfile.TemporaryDirectory(prefix='bb622_printer17_') as folder:
            root=Path(folder)
            (root/'src').mkdir()
            for rel in (IPL, DIAG, HEAP, WATCH, SERIAL):
                (root/rel).parent.mkdir(parents=True, exist_ok=True)
            for rel,value in ((SRC,src),(BIOS,initial_bios),
                              (SERIAL_INC,ser),(WATCH_INC,watchinc)):
                (root/rel).write_bytes(value)
            a={'tag':'BB_DOS622_IPL_V1','files':{
                SRC:{'installed':sha(src)}, BIOS:{'installed':sha(initial_bios)}}}
            new_a=jsonbytes(a);(root/IPL).write_bytes(new_a)
            b={'tag':'BB_DOS622_BOOT_DIAG_V1','files':{
                SRC:{'new':sha(src)},BIOS:{'new':sha(initial_bios)}},
                'parent_after':sha(new_a)}
            new_b=jsonbytes(b);(root/DIAG).write_bytes(new_b)
            c={'tag':'BB_DOS622_HEAP_RESCUE_V1','files':{
                SRC:{'after':sha(src)}, IPL:{'after':sha(new_a)},
                DIAG:{'after':sha(new_b)}}}
            new_c=jsonbytes(c);(root/HEAP).write_bytes(new_c)
            d={'tag':'BB_DOS622_STALL_WATCH_V1','files':{
                SRC:{'new':sha(src)},BIOS:{'new':sha(initial_bios)},
                WATCH_INC:{'new':sha(watchinc)},IPL:{'new':sha(new_a)},
                DIAG:{'new':sha(new_b)},HEAP:{'new':sha(new_c)}}}
            new_d=jsonbytes(d);(root/WATCH).write_bytes(new_d)
            e={'tag':'BB_DOS622_SERIAL14_GUARD_V1','files':{}}
            for i, rel in enumerate((BIOS,SERIAL_INC,IPL,DIAG,HEAP,WATCH)):
                value=(root/rel).read_bytes()
                bak=f'original_{i}.bin'
                (root/SERIAL_STATE/bak).write_bytes(value)
                e['files'][rel]={'old':sha(value),'new':sha(value),'backup':bak}
            new_e=jsonbytes(e);(root/SERIAL).write_bytes(new_e)
            original = {rel:(root/rel).read_bytes() for rel in
                        (SRC,BIOS,SERIAL_INC,WATCH_INC,IPL,DIAG,HEAP,WATCH,SERIAL)}
            p=plan(root,include)
            assert len(p)==7 and (root/PRINTER_INC).exists() is False
            apply(root,include)
            assert (root/PRINTER_INC).read_bytes()==include
            assert (root/BIOS).read_bytes().count(b'case 0x17u: return bb622_printer17(rt);')==1
            restore(root)
            assert not (root/PRINTER_INC).exists() and not (root/STATE).exists()
            assert all((root/rel).read_bytes()==value for rel,value in original.items())
            print(f'SELFTEST {label}: install, five manifest layers, verify, byte-identical rollback PASS')
    print('SELFTEST PASS: LF/CRLF/MIXED + prior-stage SHA chains')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('selftest','probe','apply','verify','restore'))
    parser.add_argument('--root', type=Path, default=HERE)
    args=parser.parse_args()
    root=args.root.resolve()
    include=(Path(__file__).resolve().parent/'bb_dos622_printer17.inc').read_bytes()
    try:
        if args.command=='selftest':selftest(include)
        elif args.command=='probe':
            for rel,(old,new) in plan(root,include).items():
                print(f'{rel}: {0 if old is None else len(old)} -> {len(new)} B, SHA={sha(new)[:16]}')
            print('PROBE PASS: all stages verified; no changes made')
        elif args.command=='apply':apply(root,include)
        elif args.command=='verify':verify(root)
        elif args.command=='restore':restore(root)
    except (OSError,ValueError,AssertionError,KeyError,TypeError) as err:
        parser.exit(1,f'ERROR: {err}\n')

if __name__=='__main__':main()
