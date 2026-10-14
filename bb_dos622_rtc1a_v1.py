#!/usr/bin/env python3
"""Install/remove DOS 6.22 BIOS INT 1Ah RTC support without touching JIT or DOS 2.

Requires IPL -> diagnostic -> heap -> watch -> serial14 -> printer17 stages.
Exact-byte SHA-256 backups and checksummed cascading parent manifests.
No git patch, no fetching and no changes to original DOS floppy images.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile

HERE=Path(__file__).resolve().parent
TAG='BB_DOS622_RTC1A_V1'
SRC='src/bb_live.c'
BIOS='src/bb_dos622_bios.inc'
RTC_INC='src/bb_dos622_rtc1a.inc'
PRINTER_INC='src/bb_dos622_printer17.inc'
SERIAL_INC='src/bb_dos622_serial14.inc'
WATCH_INC='src/bb_dos622_stall_watch.inc'
IPL='.bb_dos622_ipl_v1_state/manifest.json'
DIAG='.bb_dos622_boot_diag_v1_state/repair.json'
HEAP='.bb_dos622_heap_rescue_v1_state/manifest.json'
WATCH='.bb_dos622_stall_watch_v1_state/manifest.json'
SERIAL_ROOT='.bb_dos622_serial14_guard_v1_state'
SERIAL=SERIAL_ROOT+'/manifest.json'
PRINTER_ROOT='.bb_dos622_printer17_v1_state'
PRINTER=PRINTER_ROOT+'/manifest.json'
STATE='.bb_dos622_rtc1a_v1_state'
PARENTS=(IPL,DIAG,HEAP,WATCH,SERIAL,PRINTER)

def sha(data:bytes)->str: return hashlib.sha256(data).hexdigest()
def jbytes(obj:dict)->bytes: return json.dumps(obj,indent=2).encode('utf-8')

def insert_after(old:bytes, pattern:bytes, insert:bytes, desc:str)->bytes:
    match=list(re.finditer(pattern,old,re.M))
    if len(match)!=1:
        nearby=[l[:160].decode('utf8','replace') for l in old.splitlines()
                if b'printer17' in l or b'case 0x1Au:' in l][:12]
        raise ValueError(f'{desc}: expected one matching source line, found {len(match)}, nearby={nearby}')
    m=match[0]
    nl=m.group('nl') or b'\n'
    return old[:m.end()]+insert.replace(b'@NL@',nl)+old[m.end():]

def transform(old:bytes)->bytes:
    if b'BB_DOS622_RTC1A_V1' in old or b'bb_dos622_rtc1a.inc' in old:
        raise ValueError('RTC stage is already installed')
    after=insert_after(old,
        rb'^[ \t]*#include "bb_dos622_printer17\.inc"(?P<nl>\r\n|\n|\r|$)',
        b'/* BB_DOS622_RTC1A_V1 */@NL@#include "bb_dos622_rtc1a.inc"@NL@',
        'printer17 include')
    after=insert_after(after,
        rb'^[ \t]*case 0x1Au:(?P<nl>\r\n|\n|\r|$)',
        b'        if ((c->r[MD_X86_AX] >> 8) >= 0x02u &&@NL@'
        b'            (c->r[MD_X86_AX] >> 8) <= 0x07u)@NL@'
        b'            return bb622_rtc_int1a(rt);@NL@',
        'INT1A BIOS switch')
    return after

def check_state(root:Path):
    rels=(SRC,BIOS,PRINTER_INC,SERIAL_INC,WATCH_INC)+PARENTS
    data={p:(root/p).read_bytes() for p in rels}
    a,b,c,d,e,f=(json.loads(data[p]) for p in PARENTS)
    names=[p.get('tag') for p in (a,b,c,d,e,f)]
    expect=['BB_DOS622_IPL_V1','BB_DOS622_BOOT_DIAG_V1',
            'BB_DOS622_HEAP_RESCUE_V1','BB_DOS622_STALL_WATCH_V1',
            'BB_DOS622_SERIAL14_GUARD_V1','BB_DOS622_PRINTER17_V1']
    if names!=expect: raise ValueError(f'expected installed stage order {expect}; found {names}')
    for p in (SRC,BIOS):
        if a['files'][p]['installed']!=sha(data[p]): raise ValueError(f'IPL source SHA mismatch: {p}')
        if b['files'][p]['new']!=sha(data[p]): raise ValueError(f'diagnostic source SHA mismatch: {p}')
        if d['files'][p]['new']!=sha(data[p]): raise ValueError(f'watch source SHA mismatch: {p}')
    if b['parent_after']!=sha(data[IPL]): raise ValueError('boot diag parent SHA mismatch')
    for p in (SRC,IPL,DIAG):
        if c['files'][p]['after']!=sha(data[p]): raise ValueError(f'heap source SHA mismatch: {p}')
    for p in (BIOS,WATCH_INC,IPL,DIAG,HEAP):
        if d['files'][p]['new']!=sha(data[p]): raise ValueError(f'watch parent SHA mismatch: {p}')
    for manifest, state_dir, desc in ((e,SERIAL_ROOT,'serial14'),(f,PRINTER_ROOT,'printer17')):
        for p,entry in manifest['files'].items():
            actual=(root/p).read_bytes()
            if entry['new']!=sha(actual): raise ValueError(f'{desc} source SHA mismatch: {p}')
            if entry['old'] is not None:
                saved=(root/state_dir/entry['backup']).read_bytes()
                if entry['old']!=sha(saved): raise ValueError(f'{desc} original backup modified: {p}')
    if b'#include "bb_dos622_printer17.inc"' not in data[BIOS] or \
       b'case 0x17u: return bb622_printer17(rt);' not in data[BIOS]:
        raise ValueError('printer17 BIOS stage missing')
    return data,(a,b,c,d,e,f)

def plan(root:Path,rtc_bytes:bytes):
    if (root/STATE).exists(): raise ValueError('RTC stage already installed; use verify or restore')
    if (root/RTC_INC).exists(): raise ValueError('RTC include already exists; refusing overwrite')
    old,(a,b,c,d,e,f)=check_state(root)
    bios=transform(old[BIOS])
    a['files'][BIOS]['installed']=sha(bios)
    ai=jbytes(a)
    b['files'][BIOS]['new']=sha(bios)
    b['parent_after']=sha(ai)
    bi=jbytes(b)
    for key,value in ((IPL,ai),(DIAG,bi)):
        c['files'][key]['after']=sha(value)
    ci=jbytes(c)
    d['files'][BIOS]['new']=sha(bios)
    for key,value in ((IPL,ai),(DIAG,bi),(HEAP,ci)):
        d['files'][key]['new']=sha(value)
    di=jbytes(d)
    for key,value in ((BIOS,bios),(IPL,ai),(DIAG,bi),(HEAP,ci),(WATCH,di)):
        e['files'][key]['new']=sha(value)
    ei=jbytes(e)
    for key,value in ((BIOS,bios),(IPL,ai),(DIAG,bi),(HEAP,ci),(WATCH,di),(SERIAL,ei)):
        f['files'][key]['new']=sha(value)
    fi=jbytes(f)
    return {
        BIOS:(old[BIOS],bios),RTC_INC:(None,rtc_bytes),IPL:(old[IPL],ai),
        DIAG:(old[DIAG],bi),HEAP:(old[HEAP],ci),WATCH:(old[WATCH],di),
        SERIAL:(old[SERIAL],ei),PRINTER:(old[PRINTER],fi),
    }

def verify(root:Path):
    state=root/STATE
    meta=json.loads((state/'manifest.json').read_text(encoding='utf-8'))
    if meta.get('tag')!=TAG:raise ValueError('invalid RTC manifest tag')
    for p,item in meta['files'].items():
        if sha((root/p).read_bytes())!=item['new']:
            raise ValueError(f'installed file SHA mismatch: {p}')
        if item['old'] is not None and sha((state/item['backup']).read_bytes())!=item['old']:
            raise ValueError(f'RTC stage backup altered: {p}')
    check_state(root)
    bios=(root/BIOS).read_bytes()
    if b'#include "bb_dos622_rtc1a.inc"' not in bios or b'return bb622_rtc_int1a(rt);' not in bios:
        raise ValueError('RTC BIOS handler missing')
    print('VERIFIED: RTC source + IPL/diag/heap/watch/serial14/printer17 SHA chain; original backups intact')

def apply(root:Path,include:bytes):
    changes=plan(root,include)
    state=root/STATE
    state.mkdir()
    try:
        manifest={'tag':TAG,'files':{}}
        for i,(p,(old,new)) in enumerate(changes.items()):
            backup=f'original_{i}.bin'
            manifest['files'][p]={'old':None if old is None else sha(old),
                                  'new':sha(new),'backup':backup}
            if old is not None: (state/backup).write_bytes(old)
        (state/'manifest.json').write_bytes(jbytes(manifest))
        for p,(old,new) in changes.items():
            dest=root/p
            if old is None and dest.exists():raise ValueError(f'RTC file appeared during install: {p}')
            if old is not None and dest.read_bytes()!=old:raise ValueError(f'file modified during install: {p}')
            dest.write_bytes(new)
        verify(root)
    except Exception:
        for p,(old,_) in changes.items():
            dest=root/p
            if old is None:dest.unlink(missing_ok=True)
            else:dest.write_bytes(old)
        shutil.rmtree(state,ignore_errors=True)
        raise
    print('APPLIED: DOS 6.22 AT BIOS BCD RTC INT1A AH=02/03/04/05 and alarm responses; JIT unchanged')

def restore(root:Path):
    verify(root)
    state=root/STATE
    manifest=json.loads((state/'manifest.json').read_text(encoding='utf-8'))
    for p,item in manifest['files'].items():
        dst=root/p
        if item['old'] is None:dst.unlink()
        else:dst.write_bytes((state/item['backup']).read_bytes())
    shutil.rmtree(state)
    print('RESTORED: complete RTC-stage source and every parent manifest byte-for-byte')

def selftest(include:bytes):
    fixture=b'''/* BB_DOS622_STALL_WATCH_V1 */
#include "bb_dos622_serial14.inc"
/* BB_DOS622_PRINTER17_V1 */
#include "bb_dos622_printer17.inc"
static bool BB622_FLASH bb622_bios_interrupt(MdRuntime *rt,uint8_t vector,void *user)
{
    bb622_watch_bios(rt,vector);
    switch (vector) {
    case 0x13u: return bb622_int13(rt);
    case 0x14u: return bb622_serial14(rt);
    case 0x17u: return bb622_printer17(rt);
    case 0x1Au:
        if ((c->r[MD_X86_AX] >> 8) == 0x00u) return true;
        break;
    default:break;
    }
    if (md_msdos2_boot_interrupt(rt,vector,user))return true;
    if (bb622_null_firmware_vector(rt,vector))return true;
    return false;
}
'''
    variants=[('LF',fixture),('CRLF',fixture.replace(b'\n',b'\r\n')),
              ('MIXED',fixture.replace(b'    case 0x1Au:\n',b'    case 0x1Au:\r\n')),
              ('CRLF_MIXED',fixture.replace(b'\n',b'\r\n').replace(b'    case 0x1Au:\r\n',b'    case 0x1Au:\n'))]
    sr=b'/* unchanged real 286 CPU and 232-KiB JIT source */\n'
    ser=b'/* existing serial14 include */\n'
    printer=b'/* existing printer17 include */\n'
    watchinc=b'/* existing stallwatch include */\n'
    for name,bios in variants:
        with tempfile.TemporaryDirectory(prefix='bb622_rtc1a_') as tmp:
            root=Path(tmp)
            for p in (SRC,BIOS,SERIAL_INC,PRINTER_INC,WATCH_INC)+PARENTS:
                (root/p).parent.mkdir(parents=True,exist_ok=True)
            for p,val in ((SRC,sr),(BIOS,bios),(SERIAL_INC,ser),(PRINTER_INC,printer),(WATCH_INC,watchinc)):
                (root/p).write_bytes(val)
            a={'tag':'BB_DOS622_IPL_V1','files':{SRC:{'installed':sha(sr)},BIOS:{'installed':sha(bios)}}}
            ai=jbytes(a);(root/IPL).write_bytes(ai)
            b={'tag':'BB_DOS622_BOOT_DIAG_V1','files':{SRC:{'new':sha(sr)},BIOS:{'new':sha(bios)}},'parent_after':sha(ai)}
            bi=jbytes(b);(root/DIAG).write_bytes(bi)
            c={'tag':'BB_DOS622_HEAP_RESCUE_V1','files':{SRC:{'after':sha(sr)},IPL:{'after':sha(ai)},DIAG:{'after':sha(bi)}}}
            ci=jbytes(c);(root/HEAP).write_bytes(ci)
            d={'tag':'BB_DOS622_STALL_WATCH_V1','files':{SRC:{'new':sha(sr)},BIOS:{'new':sha(bios)},WATCH_INC:{'new':sha(watchinc)},
                IPL:{'new':sha(ai)},DIAG:{'new':sha(bi)},HEAP:{'new':sha(ci)}}}
            di=jbytes(d);(root/WATCH).write_bytes(di)
            e={'tag':'BB_DOS622_SERIAL14_GUARD_V1','files':{}}
            for i,p in enumerate((BIOS,SERIAL_INC,IPL,DIAG,HEAP,WATCH)):
                val=(root/p).read_bytes(); backup=f'original_{i}.bin'
                (root/SERIAL_ROOT/backup).write_bytes(val)
                e['files'][p]={'old':sha(val),'new':sha(val),'backup':backup}
            ei=jbytes(e);(root/SERIAL).write_bytes(ei)
            f={'tag':'BB_DOS622_PRINTER17_V1','files':{}}
            for i,p in enumerate((BIOS,PRINTER_INC,IPL,DIAG,HEAP,WATCH,SERIAL)):
                val=(root/p).read_bytes(); backup=f'original_{i}.bin'
                (root/PRINTER_ROOT/backup).write_bytes(val)
                f['files'][p]={'old':sha(val),'new':sha(val),'backup':backup}
            fi=jbytes(f);(root/PRINTER).write_bytes(fi)
            original={p:(root/p).read_bytes() for p in (SRC,BIOS,SERIAL_INC,PRINTER_INC,WATCH_INC)+PARENTS}
            probe=plan(root,include)
            assert len(probe)==8
            assert not (root/RTC_INC).exists()
            apply(root,include)
            assert (root/RTC_INC).read_bytes()==include
            assert (root/BIOS).read_bytes().count(b'return bb622_rtc_int1a(rt);')==1
            verify(root)
            restore(root)
            assert not (root/RTC_INC).exists() and not (root/STATE).exists()
            assert all((root/p).read_bytes()==val for p,val in original.items())
            print(f'SELFTEST {name}: install/verify/restore + 6-parent SHA chain PASS')
    print('SELFTEST PASS: LF/CRLF/MIXED source; all manifests and backups restored byte-exact')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=('selftest','probe','apply','verify','restore'))
    p.add_argument('--root',type=Path,default=HERE)
    args=p.parse_args()
    root=args.root.resolve()
    try:
        include=(Path(__file__).resolve().parent/'bb_dos622_rtc1a.inc').read_bytes()
        if args.command=='selftest':selftest(include)
        elif args.command=='probe':
            for key,(old,new) in plan(root,include).items():
                print(f'{key}: {0 if old is None else len(old)} -> {len(new)} B, sha256={sha(new)[:16]}')
            print('PROBE PASS: previous stages valid, no files changed')
        elif args.command=='apply':apply(root,include)
        elif args.command=='verify':verify(root)
        elif args.command=='restore':restore(root)
    except (OSError,ValueError,AssertionError,TypeError,KeyError) as ex:
        p.exit(1,f'ERROR: {ex}\n')
if __name__=='__main__':main()
