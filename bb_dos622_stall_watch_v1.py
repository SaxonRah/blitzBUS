#!/usr/bin/env python3
"""DOS622 startup stall watch v1: safe complete-file install, verify, restore.

Extends exact installed IPL -> boot diagnostic -> heap rescue manifest chain.
Requires the user's previous stages installed. Does not patch blitz86/JIT.
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
SRC = 'src/bb_live.c'
BIOS = 'src/bb_dos622_bios.inc'
INC = 'src/bb_dos622_stall_watch.inc'
IPL = '.bb_dos622_ipl_v1_state/manifest.json'
DIAG = '.bb_dos622_boot_diag_v1_state/repair.json'
HEAP = '.bb_dos622_heap_rescue_v1_state/manifest.json'
STATE = '.bb_dos622_stall_watch_v1_state'
TAG = 'BB_DOS622_STALL_WATCH_V1'


def sha(b): return hashlib.sha256(b).hexdigest()


def replace_once(data: bytes, old: bytes, new: bytes, name: str) -> bytes:
    count = data.count(old)
    if count != 1:
        raise ValueError(f'{name}: expected one instance, got {count}: {old[:125]!r}')
    return data.replace(old, new, 1)


def match_line(data: bytes, expression: bytes, note: str, replacement):
    # Preserve the specific matched line's EOL; mixed-EOL sources supported.
    hits = list(re.finditer(expression, data, flags=re.M))
    if len(hits) != 1:
        raise ValueError(f'{note}: expected 1 source match, got {len(hits)}')
    h = hits[0]
    nl = h.group('nl') or b'\n'
    return data[:h.start()] + replacement(h.group(0), nl) + data[h.end():]


def transform_src(b: bytes) -> bytes:
    if TAG.encode() in b: raise ValueError('stall trace is already in bb_live.c')
    b = match_line(b, rb'^#include "bb_dos622_bios\.inc"(?P<nl>\r\n|\n|\r|$)',
       'DOS622 BIOS include', lambda old,nl: b'/* ' + TAG.encode() + b' */' + nl +
           b'#include "bb_dos622_stall_watch.inc"' + nl + old)
    # This context uniquely identifies the first, pre-dispatch timing call.
    b = re.sub(rb'(?m)^(?P<line>[ \t]*bb_v25_bios_time\(\);)(?P<nl>\r\n|\n|\r)(?=[ \t]*if\(rt==R\)bb_irq36_dispatch\(rt,bb_now_us\(\)\);)',
               lambda h: h.group('line') + h.group('nl') +
                   b'    bb622_watch_slice(rt);' + h.group('nl'), b, count=1)
    if b.count(b'    bb622_watch_slice(rt);') != 1:
        raise ValueError('bb_live_try timing anchor missing; no file changed')
    return b


def transform_bios(b: bytes) -> bytes:
    if TAG.encode() in b: raise ValueError('stall trace is already in BIOS file')
    b = match_line(b,
       rb'^static bool BB622_FLASH bb622_bios_interrupt\(MdRuntime \*rt, uint8_t vector, void \*user\)(?P<nl>\r\n|\n|\r|$)',
       'BIOS callback function', lambda old,nl: b'/* ' + TAG.encode() + b' */' + nl + old)
    # Instrument only the actual function, without replacing switch behavior.
    b = match_line(b, rb'^[ \t]*switch \(vector\) \{(?P<nl>\r\n|\n|\r|$)',
       'BIOS vector switch', lambda old,nl: b'    bb622_watch_bios(rt, vector);' + nl + old)
    b = match_line(b,
       rb'^    return md_msdos2_boot_interrupt\(rt, vector, user\);(?P<nl>\r\n|\n|\r|$)',
       'BIOS fallback', lambda old,nl: b'    bb622_watch_ivt(rt, vector);' + nl + old)
    return b


def get_plan(root: Path, include_bytes: bytes):
    if (root/STATE).exists():
        raise ValueError('already installed (or interrupted); use verify/restore')
    if (root/INC).exists():
        raise ValueError('new include already exists; refusing overwrite')
    src, bios = (root/SRC).read_bytes(), (root/BIOS).read_bytes()
    a, b, c = (root/IPL).read_bytes(), (root/DIAG).read_bytes(), (root/HEAP).read_bytes()
    ai, bi, ci = json.loads(a), json.loads(b), json.loads(c)
    if [ai.get('tag'),bi.get('tag'),ci.get('tag')] != [
        'BB_DOS622_IPL_V1','BB_DOS622_BOOT_DIAG_V1','BB_DOS622_HEAP_RESCUE_V1']:
        raise ValueError('expected IPL+diag+heap rescue installed; unexpected manifest tags')
    if ai['files'][SRC]['installed'] != sha(src) or ai['files'][BIOS]['installed'] != sha(bios):
        raise ValueError('IPL file hashes mismatch; refuse to modify current sources')
    if bi['files'][SRC]['new'] != sha(src) or bi['files'][BIOS]['new'] != sha(bios):
        raise ValueError('diagnostic file hashes mismatch')
    if bi['parent_after'] != sha(a): raise ValueError('diagnostic IPL parent SHA mismatch')
    for rel, original in ((SRC,src),(IPL,a),(DIAG,b)):
        if ci['files'][rel]['after'] != sha(original):
            raise ValueError(f'heap rescue parent hash mismatch at {rel}')
    new_src, new_bios = transform_src(src), transform_bios(bios)
    ai['files'][SRC]['installed'] = sha(new_src)
    ai['files'][BIOS]['installed'] = sha(new_bios)
    na = json.dumps(ai, indent=2).encode('utf8')
    bi['files'][SRC]['new'] = sha(new_src)
    bi['files'][BIOS]['new'] = sha(new_bios)
    bi['parent_after'] = sha(na)
    nb = json.dumps(bi, indent=2).encode('utf8')
    ci['files'][SRC]['after'] = sha(new_src)
    ci['files'][IPL]['after'] = sha(na)
    ci['files'][DIAG]['after'] = sha(nb)
    nc = json.dumps(ci, indent=2).encode('utf8')
    return {SRC:(src,new_src), BIOS:(bios,new_bios), INC:(None,include_bytes),
            IPL:(a,na),DIAG:(b,nb),HEAP:(c,nc)}


def verify(root: Path):
    state = root / STATE
    rec = json.loads((state/'manifest.json').read_text(encoding='utf8'))
    if rec['tag'] != TAG: raise ValueError('wrong manifest tag')
    for rel, meta in rec['files'].items():
        p=root/rel
        if sha(p.read_bytes()) != meta['new']:
            raise ValueError(f'{rel}: installed SHA mismatch')
        if meta['old'] is not None and sha((state/meta['backup']).read_bytes()) != meta['old']:
            raise ValueError(f'{rel}: backup SHA mismatch')
    src, bios = (root/SRC).read_bytes(), (root/BIOS).read_bytes()
    ai, bi, ci = json.loads((root/IPL).read_bytes()), json.loads((root/DIAG).read_bytes()), json.loads((root/HEAP).read_bytes())
    if ai['files'][SRC]['installed'] != sha(src) or ai['files'][BIOS]['installed'] != sha(bios):
        raise ValueError('IPL manifest is not consistent')
    if bi['files'][SRC]['new'] != sha(src) or bi['files'][BIOS]['new'] != sha(bios) or bi['parent_after'] != sha((root/IPL).read_bytes()):
        raise ValueError('diagnostic manifest is not consistent')
    for rel in (SRC,IPL,DIAG):
        if ci['files'][rel]['after'] != sha((root/rel).read_bytes()):
            raise ValueError('heap-rescue manifest is not consistent')
    print('VERIFIED stall-watch source + all three parent SHA chains; rollback intact')


def apply(root: Path, include_bytes: bytes):
    plan = get_plan(root, include_bytes)
    print('PROBE PASS: exact installed source matches, all parent manifests consistent')
    state=root/STATE
    state.mkdir()
    try:
        rec={'tag':TAG,'files':{}}
        for n,(rel,(old,new)) in enumerate(plan.items()):
            backup=f'original_{n}.bin'
            rec['files'][rel] = {'old':sha(old) if old is not None else None,'new':sha(new),'backup':backup}
            if old is not None: (state/backup).write_bytes(old)
        (state/'manifest.json').write_text(json.dumps(rec,indent=2),encoding='utf8')
        for rel,(old,new) in plan.items():
            p=root/rel
            if old is None:
                if p.exists(): raise ValueError('new include path appeared concurrently')
            elif p.read_bytes()!=old: raise ValueError(f'source changed during install: {rel}')
            p.write_bytes(new)
        verify(root)
    except Exception:
        for rel,(old,new) in plan.items():
            p=root/rel
            if old is None: p.unlink(missing_ok=True)
            else: p.write_bytes(old)
        shutil.rmtree(state,ignore_errors=True)
        raise
    print('APPLIED: DOS622 guest-state sampling + BIOS-call trace, cache and clockfix untouched')


def restore(root: Path):
    verify(root)
    state=root/STATE
    rec=json.loads((state/'manifest.json').read_text(encoding='utf8'))
    for rel,meta in rec['files'].items():
        p=root/rel
        if meta['old'] is None: p.unlink()
        else: p.write_bytes((state/meta['backup']).read_bytes())
    shutil.rmtree(state)
    print('RESTORED: both C sources and IPL/diag/heap manifests exact bytes; include deleted')


def selftest(inc: bytes):
    # Tests synthetic versions of all three parent manifest layers, and
    # mixed newlines / inline comments. No actual user checkout changes.
    sample_src = b'''#include "bb_dos622_bios.inc"
void bb_live_try(MdRuntime*rt) {
    bb_v25_bios_time();
    if(rt==R)bb_irq36_dispatch(rt,bb_now_us());
}
'''
    sample_bios = b'''static bool BB622_FLASH bb622_bios_interrupt(MdRuntime *rt, uint8_t vector, void *user)
{
    switch (vector) {
    default: break;
    }
    return md_msdos2_boot_interrupt(rt, vector, user);
}
'''
    for name, src, bios in [('LF',sample_src,sample_bios),
                           ('CRLF',sample_src.replace(b'\n',b'\r\n'),sample_bios.replace(b'\n',b'\r\n')),
                           ('MIXED',sample_src.replace(b'    bb_v25_bios_time();\n',b'    bb_v25_bios_time();\r\n'),sample_bios)]:
        with tempfile.TemporaryDirectory(prefix='bb622_watch_') as d:
            root=Path(d); (root/'src').mkdir(); (root/IPL).parent.mkdir(); (root/DIAG).parent.mkdir(); (root/HEAP).parent.mkdir()
            (root/SRC).write_bytes(src); (root/BIOS).write_bytes(bios)
            ai={'tag':'BB_DOS622_IPL_V1','files':{SRC:{'installed':sha(src)},BIOS:{'installed':sha(bios)}}}
            ar=json.dumps(ai,indent=2).encode(); (root/IPL).write_bytes(ar)
            bi={'tag':'BB_DOS622_BOOT_DIAG_V1','files':{SRC:{'new':sha(src)},BIOS:{'new':sha(bios)}},'parent_after':sha(ar)}
            br=json.dumps(bi,indent=2).encode(); (root/DIAG).write_bytes(br)
            ci={'tag':'BB_DOS622_HEAP_RESCUE_V1','files':{SRC:{'after':sha(src)},IPL:{'after':sha(ar)},DIAG:{'after':sha(br)}}}
            cr=json.dumps(ci,indent=2).encode(); (root/HEAP).write_bytes(cr)
            originals={rel:(root/rel).read_bytes() for rel in (SRC,BIOS,IPL,DIAG,HEAP)}
            assert len(get_plan(root,inc))==6
            apply(root,inc)
            restore(root)
            assert not (root/INC).exists()
            assert all((root/rel).read_bytes()==old for rel,old in originals.items())
            print(f'SELFTEST {name}: install + verify + byte-exact restore PASS')
    print('SELFTEST PASS')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['selftest','probe','apply','verify','restore'])
    p.add_argument('--root',type=Path,default=ROOT)
    a=p.parse_args()
    root=a.root.resolve()
    inc=(Path(__file__).resolve().parent/'bb_dos622_stall_watch.inc').read_bytes()
    try:
        if a.command=='selftest': selftest(inc)
        elif a.command=='probe':
            d=get_plan(root,inc)
            for name,(old,new) in d.items():
                print(f'{name}: {0 if old is None else len(old)} -> {len(new)} B, SHA={sha(new)[:14]}')
            print('PROBE PASS; no source changed')
        elif a.command=='apply': apply(root,inc)
        elif a.command=='verify': verify(root)
        elif a.command=='restore': restore(root)
    except (OSError,KeyError,ValueError,AssertionError) as e:
        p.exit(1,f'ERROR: {e}\n')

if __name__=='__main__': main()
