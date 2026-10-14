#!/usr/bin/env python3
"""DOS622 Serial INT14 + null-IVT guard: reversible installed-source repair.

Targets the working IPL -> boot diagnostic -> heap rescue -> stall-watch chain.
No changes to JIT, native code cache, DOS2, disk image, clock or CPU model.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile

ROOT = Path(__file__).resolve().parent
BIOS = 'src/bb_dos622_bios.inc'
SRC = 'src/bb_live.c'
WATCH_INC = 'src/bb_dos622_stall_watch.inc'
NEW_INC = 'src/bb_dos622_serial14.inc'
IPL = '.bb_dos622_ipl_v1_state/manifest.json'
DIAG = '.bb_dos622_boot_diag_v1_state/repair.json'
HEAP = '.bb_dos622_heap_rescue_v1_state/manifest.json'
WATCH = '.bb_dos622_stall_watch_v1_state/manifest.json'
STATE = '.bb_dos622_serial14_guard_v1_state'
TAG = 'BB_DOS622_SERIAL14_GUARD_V1'


def digest(b: bytes) -> str: return hashlib.sha256(b).hexdigest()


def insert_line(data: bytes, pattern: bytes, before: bytes, after: bytes, name: str) -> bytes:
    hits = list(re.finditer(pattern, data, re.M))
    if len(hits) != 1:
        raise ValueError(f'{name}: expected one source match, got {len(hits)}')
    h = hits[0]
    nl = h.group('nl') or b'\n'
    return data[:h.start()] + before.replace(b'@NL@', nl) + h.group(0) + after.replace(b'@NL@', nl) + data[h.end():]


def transform_bios(b: bytes) -> bytes:
    if TAG.encode('ascii') in b or b'bb_dos622_serial14.inc' in b:
        raise ValueError('serial14 guard is already installed')
    b = insert_line(b,
        rb'^/\* BB_DOS622_STALL_WATCH_V1 \*/(?P<nl>\r\n|\n|\r|$)',
        b'/* ' + TAG.encode('ascii') + b' */@NL@' + b'#include "bb_dos622_serial14.inc"@NL@',
        b'', 'stall-watch BIOS marker')
    b = insert_line(b,
        rb'^[ \t]*case 0x13u: return bb622_int13\(rt\);(?P<nl>\r\n|\n|\r|$)',
        b'    case 0x14u: return bb622_serial14(rt);@NL@', b'', 'BIOS INT13 case')
    b = insert_line(b,
        rb'^[ \t]*return md_msdos2_boot_interrupt\(rt, vector, user\);(?P<nl>\r\n|\n|\r|$)',
        b'    if (md_msdos2_boot_interrupt(rt, vector, user)) return true;@NL@'
        b'    if (bb622_null_firmware_vector(rt, vector)) return true;@NL@',
        b'', 'BIOS native fallback')
    # Original 'return md_msdos2_boot_interrupt' remains after the guard.
    # Replace that single terminal statement with 'return false;'.
    old = b'    return md_msdos2_boot_interrupt(rt, vector, user);'
    if b.count(old) != 1: raise ValueError('original BIOS fallback not unique')
    return b.replace(old, b'    return false;', 1)


def read_layers(root: Path):
    paths = [SRC, BIOS, WATCH_INC, IPL, DIAG, HEAP, WATCH]
    old = {p:(root/p).read_bytes() for p in paths}
    a,b,c,d=(json.loads(old[p]) for p in [IPL, DIAG, HEAP, WATCH])
    expected=['BB_DOS622_IPL_V1','BB_DOS622_BOOT_DIAG_V1',
              'BB_DOS622_HEAP_RESCUE_V1','BB_DOS622_STALL_WATCH_V1']
    if [a.get('tag'),b.get('tag'),c.get('tag'),d.get('tag')] != expected:
        raise ValueError('unexpected parent manifest tags; do not modify repository')
    for p in [SRC, BIOS]:
        if a['files'][p]['installed'] != digest(old[p]): raise ValueError(f'IPL SHA mismatch: {p}')
        if b['files'][p]['new'] != digest(old[p]): raise ValueError(f'diagnostic SHA mismatch: {p}')
        if d['files'][p]['new'] != digest(old[p]): raise ValueError(f'stall-watch SHA mismatch: {p}')
    if b['parent_after'] != digest(old[IPL]): raise ValueError('diagnostic parent SHA mismatch')
    for p in [SRC, IPL, DIAG]:
        if c['files'][p]['after'] != digest(old[p]): raise ValueError(f'heap parent SHA mismatch: {p}')
    for p in [WATCH_INC, IPL, DIAG, HEAP]:
        if d['files'][p]['new'] != digest(old[p]): raise ValueError(f'stall-watch parent SHA mismatch: {p}')
    return old,a,b,c,d


def make_plan(root: Path, serial_bytes: bytes):
    if (root/STATE).exists(): raise ValueError('stage already installed; use verify or restore')
    if (root/NEW_INC).exists(): raise ValueError('new include exists: refusing overwrite')
    old,a,b,c,d=read_layers(root)
    replacement = transform_bios(old[BIOS])
    # Preserve all parent manifests and their original backups, update only
    # the installed checksum chain for files deliberately modified.
    a['files'][BIOS]['installed']=digest(replacement)
    aip=json.dumps(a,indent=2).encode('utf8')
    b['files'][BIOS]['new']=digest(replacement)
    b['parent_after']=digest(aip)
    bip=json.dumps(b,indent=2).encode('utf8')
    c['files'][IPL]['after']=digest(aip)
    c['files'][DIAG]['after']=digest(bip)
    hip=json.dumps(c,indent=2).encode('utf8')
    d['files'][BIOS]['new']=digest(replacement)
    for p,bytes_ in [(IPL,aip),(DIAG,bip),(HEAP,hip)]:
        d['files'][p]['new']=digest(bytes_)
    wip=json.dumps(d,indent=2).encode('utf8')
    return {BIOS:(old[BIOS],replacement), NEW_INC:(None,serial_bytes),
            IPL:(old[IPL],aip), DIAG:(old[DIAG],bip),
            HEAP:(old[HEAP],hip), WATCH:(old[WATCH],wip)}


def verify(root: Path):
    st=root/STATE
    rec=json.loads((st/'manifest.json').read_text(encoding='utf8'))
    if rec.get('tag')!=TAG: raise ValueError('invalid own manifest tag')
    for p,item in rec['files'].items():
        if digest((root/p).read_bytes()) != item['new']:
            raise ValueError(f'installed file SHA mismatch: {p}')
        if item['old'] is not None:
            if digest((st/item['backup']).read_bytes()) != item['old']:
                raise ValueError(f'backup modified: {p}')
    read_layers(root)
    print('VERIFIED: serial14 source + IPL/diag/heap/stall-watch SHA chains and rollback')


def apply(root: Path, inc: bytes):
    plan=make_plan(root,inc)
    state=root/STATE
    state.mkdir()
    try:
        manifest={'tag':TAG,'files':{}}
        for i,(p,(old,new)) in enumerate(plan.items()):
            backup=f'original_{i}.bin'
            manifest['files'][p]={'old':None if old is None else digest(old),
                                   'new':digest(new),'backup':backup}
            if old is not None:(state/backup).write_bytes(old)
        (state/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
        for p,(old,new) in plan.items():
            target=root/p
            if old is None and target.exists():raise ValueError(f'target exists: {p}')
            if old is not None and target.read_bytes()!=old:raise ValueError(f'concurrent modification: {p}')
            target.write_bytes(new)
        verify(root)
    except Exception:
        for p,(old,_) in plan.items():
            path=root/p
            if old is None:path.unlink(missing_ok=True)
            else:path.write_bytes(old)
        shutil.rmtree(state,ignore_errors=True)
        raise
    print('APPLIED: BIOS INT14 no-serial response + opt-in null-IVT guard; JIT unchanged')


def restore(root: Path):
    verify(root)
    state=root/STATE
    rec=json.loads((state/'manifest.json').read_text(encoding='utf8'))
    for p,item in rec['files'].items():
        path=root/p
        if item['old'] is None:path.unlink()
        else:path.write_bytes((state/item['backup']).read_bytes())
    shutil.rmtree(state)
    print('RESTORED: complete byte-exact BIOS source and all parent manifests')


def selftest(inc: bytes):
    sample_bios=b'''/* BB_DOS622_STALL_WATCH_V1 */
static bool BB622_FLASH bb622_bios_interrupt(MdRuntime *rt, uint8_t vector, void *user)
{
    bb622_watch_bios(rt, vector);
    switch (vector) {
    case 0x13u: return bb622_int13(rt);
    default: break;
    }
    bb622_watch_ivt(rt, vector);
    return md_msdos2_boot_interrupt(rt, vector, user);
}
'''
    src=b'/* user JIT untouched */\n'
    watchinc=b'/* test watch include */\n'
    variants=[('LF',sample_bios),('CRLF',sample_bios.replace(b'\n',b'\r\n')),
              ('MIXED',sample_bios.replace(b'    case 0x13u: return bb622_int13(rt);\n',
                                            b'    case 0x13u: return bb622_int13(rt);\r\n'))]
    for label,bios in variants:
        with tempfile.TemporaryDirectory(prefix='bb622_serial14_') as d:
            root=Path(d);(root/'src').mkdir()
            for p in [IPL, DIAG, HEAP, WATCH]:(root/p).parent.mkdir(exist_ok=True)
            for p,data in [(SRC,src),(BIOS,bios),(WATCH_INC,watchinc)]: (root/p).write_bytes(data)
            a={'tag':'BB_DOS622_IPL_V1','files':{SRC:{'installed':digest(src)},BIOS:{'installed':digest(bios)}}}
            aip=json.dumps(a,indent=2).encode('utf8'); (root/IPL).write_bytes(aip)
            b={'tag':'BB_DOS622_BOOT_DIAG_V1','files':{SRC:{'new':digest(src)},BIOS:{'new':digest(bios)}},'parent_after':digest(aip)}
            bip=json.dumps(b,indent=2).encode('utf8'); (root/DIAG).write_bytes(bip)
            c={'tag':'BB_DOS622_HEAP_RESCUE_V1','files':{SRC:{'after':digest(src)},IPL:{'after':digest(aip)},DIAG:{'after':digest(bip)}}}
            hip=json.dumps(c,indent=2).encode('utf8'); (root/HEAP).write_bytes(hip)
            w={'tag':'BB_DOS622_STALL_WATCH_V1','files':{SRC:{'old':digest(src),'new':digest(src)},
              BIOS:{'old':digest(bios),'new':digest(bios)},
              WATCH_INC:{'old':None,'new':digest(watchinc)},
              IPL:{'old':None,'new':digest(aip)},DIAG:{'old':None,'new':digest(bip)},
              HEAP:{'old':None,'new':digest(hip)}}}
            wip=json.dumps(w,indent=2).encode('utf8');(root/WATCH).write_bytes(wip)
            inputs={p:(root/p).read_bytes() for p in [SRC,BIOS,WATCH_INC,IPL,DIAG,HEAP,WATCH]}
            plan=make_plan(root,inc)
            assert len(plan)==6
            apply(root,inc)
            new=(root/BIOS).read_bytes()
            assert new.count(b'case 0x14u: return bb622_serial14(rt);')==1
            assert new.count(b'#include "bb_dos622_serial14.inc"')==1
            assert (root/NEW_INC).read_bytes()==inc
            restore(root)
            assert not (root/NEW_INC).exists() and not (root/STATE).exists()
            assert all((root/p).read_bytes()==old for p,old in inputs.items())
            print(f'SELFTEST {label}: install + verify + exact rollback PASS')
    print('SELFTEST PASS: LF/CRLF/MIXED, 4 parent manifests, byte-exact restore')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['selftest','probe','apply','verify','restore'])
    parser.add_argument('--root',type=Path,default=ROOT)
    args=parser.parse_args()
    root=args.root.resolve()
    include=(Path(__file__).resolve().parent/'bb_dos622_serial14.inc').read_bytes()
    try:
        if args.command=='selftest': selftest(include)
        elif args.command=='probe':
            plan=make_plan(root,include)
            for p,(old,new) in plan.items():
                print(f'{p}: {0 if old is None else len(old)} -> {len(new)} bytes, SHA256={digest(new)[:16]}')
            print('PROBE PASS: previous stages verified; no files modified')
        elif args.command=='apply':apply(root,include)
        elif args.command=='verify':verify(root)
        elif args.command=='restore':restore(root)
    except (OSError,ValueError,KeyError,AssertionError) as exc:
        parser.exit(1,f'ERROR: {exc}\n')

if __name__=='__main__':main()
