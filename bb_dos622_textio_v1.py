#!/usr/bin/env python3
"""Reversible DOS 6.22 USB text-console bridge for exact live blitzBUS checkout.

Install this *full file* and bb_dos622_textio.inc in C:\blitzBUS. Requires
previously installed RTC1A stage. No git patches, DOS image mutation or JIT
changes. Update every parent verification manifest; save exact-byte backups.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
import bb_dos622_rtc1a_v1 as rtc

HERE=Path(__file__).resolve().parent
TAG='BB_DOS622_TEXTIO_V1'
SRC='src/bb_live.c'
INC='src/bb_dos622_textio.inc'
STATE='.bb_dos622_textio_v1_state'
RTC_MANIFEST='.bb_dos622_rtc1a_v1_state/manifest.json'
PARENTS=(*rtc.PARENTS,RTC_MANIFEST)

def sha(data:bytes)->str:return hashlib.sha256(data).hexdigest()
def jd(obj:dict)->bytes:return json.dumps(obj,indent=2).encode('utf-8')

def add_before_line(old:bytes, needle:bytes, addition:bytes, descriptor:str)->bytes:
    p=rb'(?m)^[ \t]*'+re.escape(needle)+rb'(?P<nl>\r\n|\n|\r|$)'
    matches=list(re.finditer(p,old))
    if len(matches)!=1:raise ValueError(f'{descriptor}: expected one line {needle!r}, found {len(matches)}')
    m=matches[0];nl=m.group('nl') or b'\n'
    return old[:m.start()]+addition.replace(b'@NL@',nl)+old[m.start():]

def replace_line(old:bytes,needle:bytes,new:bytes,descriptor:str)->bytes:
    p=rb'(?m)^[ \t]*'+re.escape(needle)+rb'(?P<nl>\r\n|\n|\r|$)'
    matches=list(re.finditer(p,old))
    if len(matches)!=1:raise ValueError(f'{descriptor}: expected one line {needle!r}, found {len(matches)}')
    m=matches[0];nl=m.group('nl') or b'\n'
    return old[:m.start()]+new.replace(b'@NL@',nl)+old[m.end():]

def transform(old:bytes)->bytes:
    if TAG.encode() in old or b'bb_dos622_textio.inc' in old:
        raise ValueError('textio already installed')
    old=add_before_line(old,b'static void bb_v23_poll_input(void) {',
        b'/* BB_DOS622_TEXTIO_V1 - input + text output only for real DOS 6.22 */@NL@'
        b'#include "bb_dos622_textio.inc"@NL@', 'textio include')
    old=replace_line(old,b'if(!bb_video_seen||!R)return;',
        b'    if (!R) return;@NL@'
        b'#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE@NL@'
        b'    if (!bb_video_seen && !bb_sd_dos622_active()) return;@NL@'
        b'#else@NL@'
        b'    if (!bb_video_seen) return;@NL@'
        b'#endif@NL@', 'text-mode USB guard')
    start=old.find(b'B86_HOT int bb_live_try(')
    if start<0:raise ValueError('bb_live_try function not found')
    call=rb'(?m)^[ \t]*bb_v23_poll_input\(\);(?P<nl>\r\n|\n|\r|$)'
    m=list(re.finditer(call,old[start:]))
    if len(m)!=1:raise ValueError(f'bb_live_try USB poll call: expected one, found {len(m)}')
    mm=m[0]; pos=start+mm.end(); nl=mm.group('nl') or b'\n'
    return old[:pos]+b'    bb622_textio_mirror(rt);'+nl+old[pos:]

def validate_root(root:Path):
    rtc.verify(root)
    dat={p:(root/p).read_bytes() for p in (SRC,*PARENTS)}
    r=json.loads(dat[RTC_MANIFEST]);
    if r.get('tag')!='BB_DOS622_RTC1A_V1':raise ValueError('missing validated RTC1A parent')
    return dat

def plan(root:Path, inc:bytes):
    if (root/STATE).exists():raise ValueError(f'{STATE} already exists: use verify/restore')
    if (root/INC).exists():raise ValueError(f'{INC} exists: refusing overwrite')
    original=validate_root(root)
    updated={SRC:transform(original[SRC])}
    # Parents are a dependency chain; update their tracked content hashes in
    # topological order without changing any original backup fields.
    for path in PARENTS:
        m=json.loads(original[path]); m=copy.deepcopy(m)
        for tracked, entry in m.get('files',{}).items():
            if tracked in updated:
                for key in ('installed','new','after'):
                    if key in entry:entry[key]=sha(updated[tracked])
        if path==rtc.DIAG:
            m['parent_after']=sha(updated[rtc.IPL])
        updated[path]=jd(m)
    changes={SRC:(original[SRC],updated[SRC]),INC:(None,inc)}
    changes.update({p:(original[p],updated[p]) for p in PARENTS})
    return changes

def verify(root:Path,quiet=False):
    state=root/STATE
    m=json.loads((state/'manifest.json').read_text(encoding='utf8'))
    if m.get('tag')!=TAG:raise ValueError('invalid textio state')
    for p,item in m['files'].items():
        if sha((root/p).read_bytes())!=item['new']:raise ValueError(f'installed hash changed: {p}')
        if item['old'] is not None and sha((state/item['backup']).read_bytes())!=item['old']:
            raise ValueError(f'backup hash changed: {p}')
    rtc.verify(root)
    s=(root/SRC).read_bytes()
    if b'#include "bb_dos622_textio.inc"' not in s or b'bb622_textio_mirror(rt);' not in s:
        raise ValueError('text bridge not linked in live source')
    if not quiet:print('VERIFIED: textio installed, original backups intact, RTC and all earlier parent manifests valid')

def apply(root:Path,inc:bytes):
    changes=plan(root,inc);state=root/STATE
    state.mkdir()
    try:
        m={'tag':TAG,'files':{}}
        for i,(p,(old,new)) in enumerate(changes.items()):
            name=f'original_{i:02}.bin'
            m['files'][p]={'old':None if old is None else sha(old),'new':sha(new),'backup':name}
            if old is not None:(state/name).write_bytes(old)
        (state/'manifest.json').write_bytes(jd(m))
        for p,(old,new) in changes.items():
            dst=root/p
            if old is None and dst.exists():raise ValueError(f'unexpected concurrent file: {p}')
            if old is not None and dst.read_bytes()!=old:raise ValueError(f'file changed mid-install: {p}')
            dst.parent.mkdir(parents=True,exist_ok=True)
            dst.write_bytes(new)
        verify(root,True)
    except BaseException:
        for p,(old,_) in changes.items():
            dst=root/p
            if old is None:dst.unlink(missing_ok=True)
            else:dst.write_bytes(old)
        shutil.rmtree(state,ignore_errors=True)
        raise
    print('APPLIED: DOS622 text-mode USB keyboard and B800 serial screen; DOS2/286-JIT untouched')

def restore(root:Path):
    verify(root,True)
    state=root/STATE
    m=json.loads((state/'manifest.json').read_text(encoding='utf8'))
    for p,item in m['files'].items():
        if item['old'] is None:(root/p).unlink()
        else:(root/p).write_bytes((state/item['backup']).read_bytes())
    shutil.rmtree(state)
    rtc.verify(root)
    print('RESTORED: source, new include and seven parent manifest files byte-exact')

def fixture(root:Path,source:bytes):
    # Match previous stages' schema (including all original backup checks)
    # using synthetic source so tests are independent of a live machine.
    bios=b'''/* BB_DOS622_STALL_WATCH_V1 */\n#include "bb_dos622_serial14.inc"\n/* BB_DOS622_PRINTER17_V1 */\n#include "bb_dos622_printer17.inc"\nstatic bool BB622_FLASH bb622_bios_interrupt(MdRuntime *rt,uint8_t vector,void *user)\n{\n bb622_watch_bios(rt,vector);\n switch (vector) {\n case 0x13u:return bb622_int13(rt);\n case 0x14u:return bb622_serial14(rt);\n case 0x17u: return bb622_printer17(rt);\n case 0x1Au:\n if ((c->r[MD_X86_AX] >> 8)==0x00u)return true;\n break;\n default:break;\n }\n return false;\n}\n'''
    vals={SRC:source,rtc.BIOS:bios,rtc.SERIAL_INC:b'serial inc\n',rtc.PRINTER_INC:b'printer inc\n',rtc.WATCH_INC:b'watch inc\n'}
    for p,v in vals.items(): (root/p).parent.mkdir(parents=True,exist_ok=True);(root/p).write_bytes(v)
    a={'tag':'BB_DOS622_IPL_V1','files':{SRC:{'installed':sha(source)},rtc.BIOS:{'installed':sha(bios)}}};ai=jd(a)
    (root/rtc.IPL).parent.mkdir(parents=True,exist_ok=True);(root/rtc.IPL).write_bytes(ai)
    b={'tag':'BB_DOS622_BOOT_DIAG_V1','files':{SRC:{'new':sha(source)},rtc.BIOS:{'new':sha(bios)}},'parent_after':sha(ai)};bi=jd(b)
    (root/rtc.DIAG).parent.mkdir(parents=True,exist_ok=True);(root/rtc.DIAG).write_bytes(bi)
    c={'tag':'BB_DOS622_HEAP_RESCUE_V1','files':{SRC:{'after':sha(source)},rtc.IPL:{'after':sha(ai)},rtc.DIAG:{'after':sha(bi)}}};ci=jd(c)
    (root/rtc.HEAP).parent.mkdir(parents=True,exist_ok=True);(root/rtc.HEAP).write_bytes(ci)
    d={'tag':'BB_DOS622_STALL_WATCH_V1','files':{SRC:{'new':sha(source)},rtc.BIOS:{'new':sha(bios)},rtc.WATCH_INC:{'new':sha(vals[rtc.WATCH_INC])},rtc.IPL:{'new':sha(ai)},rtc.DIAG:{'new':sha(bi)},rtc.HEAP:{'new':sha(ci)}}};di=jd(d)
    (root/rtc.WATCH).parent.mkdir(parents=True,exist_ok=True);(root/rtc.WATCH).write_bytes(di)
    for tag, state_root, manifest_path, members in (
        ('BB_DOS622_SERIAL14_GUARD_V1',rtc.SERIAL_ROOT,rtc.SERIAL,(rtc.BIOS,rtc.SERIAL_INC,rtc.IPL,rtc.DIAG,rtc.HEAP,rtc.WATCH)),
        ('BB_DOS622_PRINTER17_V1',rtc.PRINTER_ROOT,rtc.PRINTER,(rtc.BIOS,rtc.PRINTER_INC,rtc.IPL,rtc.DIAG,rtc.HEAP,rtc.WATCH,rtc.SERIAL))):
        m={'tag':tag,'files':{}}
        for i,p in enumerate(members):
            data=(root/p).read_bytes();backup=f'original_{i}.bin'
            (root/state_root).mkdir(parents=True,exist_ok=True)
            (root/state_root/backup).write_bytes(data)
            m['files'][p]={'old':sha(data),'new':sha(data),'backup':backup}
        (root/manifest_path).write_bytes(jd(m))
    # create real RTC parent stage from the previous installer under test.
    rtc.apply(root,b'/* fixture RTC C source */\n')
    rtc.verify(root)

def selftest(inc:bytes):
    baseline=b'''/* text keyboard section */\nstatic void bb_v23_poll_input(void) {\n    if(!bb_video_seen||!R)return;\n    ++bb_v23_polls;\n}\nstatic int bb_v22_keyboard(void) {\n    bb_v23_poll_input();\n    return 1;\n}\nB86_HOT int bb_live_try(MdRuntime *rt, uint64_t left)\n{\n    if (R == NULL && !start(rt)) return 0;\n    bb_v23_poll_input();\n    return 1;\n}\n'''
    for name,src in (
        ('LF',baseline),('CRLF',baseline.replace(b'\n',b'\r\n')),
        ('MIXED',baseline.replace(b'    if(!bb_video_seen||!R)return;\n',b'    if(!bb_video_seen||!R)return;\r\n'))):
        with tempfile.TemporaryDirectory(prefix='bb622_textio_') as temp:
            root=Path(temp)
            fixture(root,src)
            orig={p:(root/p).read_bytes() for p in (SRC,rtc.BIOS,rtc.SERIAL_INC,rtc.PRINTER_INC,rtc.WATCH_INC,rtc.RTC_INC,*PARENTS)}
            changes=plan(root,inc)
            assert len(changes)==9
            assert not (root/INC).exists()
            apply(root,inc)
            assert (root/SRC).read_bytes().count(b'bb622_textio_mirror(rt);')==1
            assert (root/SRC).read_bytes().count(b'bb_sd_dos622_active()) return;')==1
            verify(root)
            restore(root)
            assert all((root/p).read_bytes()==raw for p,raw in orig.items())
            assert not (root/INC).exists() and not (root/STATE).exists()
            print(f'SELFTEST {name}: parent chain + exact install, verify, restore PASS')
    print('SELFTEST PASS: LF, CRLF, MIXED, 7 parent manifests, byte-exact backups')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=('selftest','probe','apply','verify','restore'))
    p.add_argument('--root',type=Path,default=HERE)
    args=p.parse_args();root=args.root.resolve()
    try:
        inc=(Path(__file__).resolve().parent/'bb_dos622_textio.inc').read_bytes()
        if args.command=='selftest':selftest(inc)
        elif args.command=='probe':
            for k,(old,new) in plan(root,inc).items():
                print(f'{k}: {0 if old is None else len(old)} -> {len(new)} bytes sha256={sha(new)[:16]}')
            print('PROBE PASS: exact source anchors and complete parent checksum chain')
        elif args.command=='apply':apply(root,inc)
        elif args.command=='verify':verify(root)
        elif args.command=='restore':restore(root)
    except Exception as e:
        print(f'ERROR: {e}');return 1
    return 0
if __name__=='__main__':raise SystemExit(main())
