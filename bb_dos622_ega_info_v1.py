#!/usr/bin/env python3
"""DOS6-only VGA/EGA INT10h AH=12h BL=10h query compatibility.

Reversible exact-SHA installer. Commands: selftest/probe/apply/verify/restore/recover.
Reads the installed VGA0B stdio-fix manifest as the exact source baseline,
recursively updates only the active SHA fields of all installed manifests.
No Git patches, DOS disk modifications, or DOS2 behavior changes.
"""
from __future__ import annotations
import argparse, hashlib, json, shutil, subprocess, sys, tempfile
from pathlib import Path
import bb_dos622_atbios_v1 as chain

ROOT=Path(__file__).resolve().parent
TAG='BB_DOS622_EGA_INFO_V1'
STATE='.bb_dos622_ega_info_v1_state'
VGA='src/bb_vga.c'
PARENT='.bb_dos622_vga0b_stdio_fix_v1_state/manifest.json'
PARENT_TAG='BB_DOS622_VGA0B_STDIO_FIX_V1'
FLOPPY='.bb_dos622_floppy_b_v1_state/manifest.json'
SHA=lambda raw:hashlib.sha256(raw).hexdigest()
atomic=chain.atomic_bytes

# Deliberately narrow: 12h/10h is a query, not a video mode switch.
# This is a VGA-class compatibility response; planar VGA RAM/graphics
# registers are not made complete by this BIOS-only answer.
HANDLER='''    /* BB_DOS622_EGA_INFO_V1: VGA-compatible EGA information query.
     * INT 10h AH=12h BL=10h: BH=00 color, BL=03 256 KiB VGA-class
     * adapter, CH=00 feature bits, CL=09 VGA-compatible switch setting.
     * Unlike BL=30h/34h, BL=10h does NOT return AL=12h.
     * Preserve AX/DX, flags, and current display state.
     * Other AH=12h selectors remain separately implemented/unhandled.
     */
    case 0x12: {
        if ((uint8_t)(*bx) != 0x10u) return false;
        if (mode != 3u && mode != 0x13u) return false;
#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE
        extern bool bb_sd_dos622_active(void);
        if (!bb_sd_dos622_active()) return false;
        *bx = 0x0003u;
        *cx = 0x0009u;
        { static unsigned bb622_ega_info_calls;
          if (bb622_ega_info_calls++ < 2u) {
              printf("[bb622-ega] INT10 AH=12 BL=10 AX=%04X BX=%04X CX=%04X (color VGA)\\n",
                  (unsigned)*ax,(unsigned)*bx,(unsigned)*cx);
              fflush(stdout);
          }
        }
        return true;
#else
        return false;
#endif
    }
'''


def newline(raw:bytes,s:str)->bytes:
    if b'\r\n' in raw and b'\n' in raw.replace(b'\r\n',b''):
        raise ValueError('Mixed line endings; cannot transform safely')
    return s.replace('\n','\r\n').encode() if b'\r\n' in raw else s.encode()


def transform(raw:bytes)->bytes:
    if TAG.encode() in raw:
        raise ValueError('EGA INFO layer already in source')
    for marker in (b'BB_DOS622_SCREEN_CLEAR_V1', b'BB_DOS622_VGA0B_KEYS_V1',
                   b'BB_DOS622_VGA0B_STDIO_FIX_V1',b'#include <stdio.h>'):
        if marker not in raw: raise ValueError('Expected VGA source prerequisite missing: '+marker.decode())
    # The exact AH=1Ah case occurs only in bb_vga_int10, not bios_palette().
    anchor=b'    case 0x1A:if(al==0){*ax=0x001A;*bx=0x0008;return true;}return false;'
    if raw.count(anchor)!=1:raise ValueError('INT10 AH=1Ah dispatch anchor missing/ambiguous')
    if raw.count(b'bool bb_vga_int10(')!=1:raise ValueError('VGA BIOS interface not unique')
    # Must not silently install a second AH=12 dispatch.
    section=raw.split(b'bool bb_vga_int10(',1)[1].split(b'static uint8_t io_status(',1)[0]
    if b'case 0x12:' in section:raise ValueError('AH=12 dispatch already present, inspect before patching')
    out=raw.replace(anchor,newline(raw,HANDLER)+anchor,1)
    if out.count(TAG.encode())!=1:raise ValueError('Handler not inserted exactly once')
    return out


def safe_rel(path):
    if not isinstance(path,str) or not path or Path(path).is_absolute() or '..' in Path(path).parts:
        raise ValueError('Unsafe relative path '+repr(path))
    return path


def load_prereq(root):
    p=root/PARENT
    if not p.is_file(): raise ValueError('Required installed VGA STDIO layer missing: '+str(p))
    ob=json.loads(p.read_bytes())
    if ob.get('tag')!=PARENT_TAG or not isinstance(ob.get('files'),list):
        raise ValueError('Installed VGA STDIO layer has invalid schema')
    entries=[e for e in ob['files'] if e.get('path')==VGA]
    if len(entries)!=1: raise ValueError('VGA source not uniquely tracked in stdio-fix manifest')
    e=entries[0];old=(root/VGA).read_bytes()
    if SHA(old)!=e.get('installed'):raise ValueError('VGA source changed since STDIO fix; exact-SHA guard refused')
    back=root/'.bb_dos622_vga0b_stdio_fix_v1_state'/safe_rel(e.get('backup'))
    if not back.is_file() or SHA(back.read_bytes())!=e.get('original'):
        raise ValueError('VGA stdio-fix backup SHA mismatch')
    p=root/FLOPPY
    if not p.is_file() or json.loads(p.read_bytes()).get('tag')!='BB_DOS622_FLOPPY_B_V1':
        raise ValueError('Expected physical floppy B layer absent; verify previous installation')
    return old


def cascade(root,old,new):
    originals=chain.active_metadata(root)
    if PARENT not in originals or FLOPPY not in originals:raise ValueError('Missing installed checksum graph nodes')
    updated=dict(originals)
    dig={SHA(old):SHA(new)}
    for _ in range(len(originals)*8+8):
        changed=False
        for rel,raw in originals.items():
            value,_=chain._update_metadata(raw,dig,rel)
            if value!=updated[rel]:updated[rel]=value;changed=True
            if value!=raw and dig.get(SHA(raw))!=SHA(value):
                dig[SHA(raw)]=SHA(value);changed=True
        if not changed:break
    else: raise ValueError('Manifest checksum graph did not converge')
    if originals[PARENT]==updated[PARENT]:raise ValueError('Expected predecessor VGA source SHA did not update')
    obj=json.loads(updated[PARENT]);ents=[e for e in obj['files'] if e.get('path')==VGA]
    if len(ents)!=1 or ents[0]['installed']!=SHA(new):raise ValueError('Parent VGA installed digest failed to update')
    return {p:(originals[p],updated[p]) for p in originals if originals[p]!=updated[p]}


def prepare(root=ROOT,verbose=True):
    if (root/STATE).exists():raise ValueError('Layer already installed; use verify or restore')
    old=load_prereq(root)
    new=transform(old)
    changes={VGA:(old,new)}
    changes.update(cascade(root,old,new))
    if verbose:
        print(f'{VGA}: {len(old)} -> {len(new)} bytes; SHA {SHA(old)[:16]} -> {SHA(new)[:16]}')
        print(f'Metadata checksum transitions: {len(changes)-1}')
        print('PROBE PASS: no source or metadata changed')
    return changes


def manifest(root):
    p=root/STATE/'manifest.json'
    if not p.is_file():raise ValueError('No install state: '+str(p))
    m=json.loads(p.read_bytes())
    if m.get('tag')!=TAG or not isinstance(m.get('files'),list):raise ValueError('Malformed layer state')
    return m


def verify(root=ROOT):
    m=manifest(root);seen=set()
    if not m['files']:raise ValueError('Empty installer state')
    for ent in m['files']:
        rel=safe_rel(ent['path']);bn=safe_rel(ent['backup'])
        if rel in seen:raise ValueError('Duplicate manifest entry '+rel)
        seen.add(rel)
        file=root/rel;backup=root/STATE/bn
        if not file.is_file() or SHA(file.read_bytes())!=ent['installed']:
            raise ValueError('Installed checksum mismatch '+str(file))
        if not backup.is_file() or SHA(backup.read_bytes())!=ent['original']:
            raise ValueError('Original backup corrupted '+str(backup))
    print(f'VERIFY PASS: {len(m["files"])} installed files and byte-exact backups')


def apply(root=ROOT):
    changes=prepare(root)
    dest=root/STATE
    dest.mkdir()
    ob={'tag':TAG,'files':[]}
    try:
        for i,(rel,(old,new)) in enumerate(changes.items()):
            name=f'backup_{i:03d}.bin'
            atomic(dest/name,old)
            ob['files'].append({'path':rel,'backup':name,'original':SHA(old),'installed':SHA(new)})
        atomic(dest/'manifest.json',(json.dumps(ob,indent=2)+'\n').encode())
        for rel,(old,new) in changes.items():atomic(root/rel,new)
        verify(root)
    except BaseException:
        for rel,(old,new) in changes.items():atomic(root/rel,old)
        shutil.rmtree(dest,ignore_errors=True)
        raise
    print('APPLIED: DOS6-only INT10 AH=12h BL=10h VGA/EGA info, no CPU/DOS2/disk changes')


def restore(root=ROOT,recover=False):
    if not recover:verify(root)
    m=manifest(root);orig={}
    for e in m['files']:
        rel=safe_rel(e['path']);b=root/STATE/safe_rel(e['backup'])
        if not b.is_file() or SHA(b.read_bytes())!=e['original']:
            raise ValueError('Damaged rollback backup: '+str(b))
        p=root/rel
        if recover and p.is_file() and SHA(p.read_bytes()) not in (e['installed'],e['original']):
            raise ValueError('Intervening changes; manual recovery needed '+str(p))
        orig[rel]=b.read_bytes()
    for rel,raw in orig.items():atomic(root/rel,raw)
    shutil.rmtree(root/STATE)
    print('RESTORED: exact pre-layer bytes including checksum metadata')


def compile_contract(handler):
    cc=shutil.which('gcc') or shutil.which('clang') or shutil.which('cc')
    if not cc:
        print('C11 compiler unavailable: behavioral test skipped (installer tests still run)')
        return
    test='''#include <stdbool.h>\n#include <stdint.h>\n#include <stdio.h>\n#include <assert.h>\nstatic uint8_t mode=3;\nstatic bool dos6=true;\nstatic bool bb_sd_dos622_active(void){return dos6;}\nstatic bool vga(uint16_t *ax,uint16_t *bx,uint16_t *cx,uint16_t *dx,uint16_t *fl) {\n(void)dx;(void)fl;uint8_t al=(uint8_t)*ax;(void)al;\nswitch(*ax>>8){\n'''+handler+'''default:return false;}}\nint main(void){uint16_t ax,bx,cx,dx,fl;\nax=0x1203;bx=0x0010;cx=0;dx=6;fl=0x0202;\nassert(vga(&ax,&bx,&cx,&dx,&fl));\nassert(ax==0x1203&&bx==0x0003&&cx==0x0009&&dx==6&&fl==0x0202);\nfor(unsigned b=0;b<256;b++){\n if(b==0x10)continue;
 ax=0x1203;bx=(uint16_t)b;cx=0x1234;dx=6;fl=0x0203;\n assert(!vga(&ax,&bx,&cx,&dx,&fl));\n assert(ax==0x1203&&bx==b&&cx==0x1234&&dx==6&&fl==0x0203);\n}\ndos6=false;ax=0x1203;bx=0x0010;cx=0;\nassert(!vga(&ax,&bx,&cx,&dx,&fl));assert(bx==0x10&&cx==0);\ndos6=true;mode=0x13;ax=0x1200;bx=0x0010;cx=0;\nassert(vga(&ax,&bx,&cx,&dx,&fl));assert(ax==0x1200&&bx==3&&cx==9);\nmode=7;ax=0x1203;bx=0x0010;cx=0;\nassert(!vga(&ax,&bx,&cx,&dx,&fl));\nputs("C11 VGA AH12/BL10 contract PASS: 256 selector values, DOS2 gate, AX/DX/flags preserved");return 0;}\n'''
    with tempfile.TemporaryDirectory() as d:
        src=Path(d)/'vga.c';exe=Path(d)/'vga_test'
        src.write_text(test)
        cmd=[cc,'-std=c11','-O2','-Wall','-Wextra','-Werror','-DPICO_ON_DEVICE=1',str(src),'-o',str(exe)]
        r=subprocess.run(cmd,capture_output=True,text=True)
        if r.returncode:raise AssertionError('VGA C11 compilation failed: '+r.stderr[:2500])
        r=subprocess.run([str(exe)],capture_output=True,text=True)
        if r.returncode:raise AssertionError('VGA C11 test failed: '+r.stderr[:2500])
        print(r.stdout.strip().splitlines()[-1])


def selftest():
    # Run exact transform/manifest/rollback on both LF/CRLF in isolated fixtures.
    for eol in ('LF','CRLF'):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            src=root/VGA;src.parent.mkdir()
            fixture='''#include <stdio.h> /* BB_DOS622_VGA0B_STDIO_FIX_V1 */\n/* BB_DOS622_SCREEN_CLEAR_V1 */\n/* BB_DOS622_VGA0B_KEYS_V1 */\n#include <stdint.h>\n#include <stdbool.h>\nstatic uint8_t mode;\nbool bb_vga_int10(uint16_t *ax,uint16_t *bx,uint16_t *cx,uint16_t *dx,uint16_t *es,uint16_t *bp,uint16_t *flags){\n uint8_t al=(uint8_t)*ax;(void)dx;(void)es;(void)bp;(void)flags;switch(*ax>>8){\n    case 0x1A:if(al==0){*ax=0x001A;*bx=0x0008;return true;}return false;\n    default:return false;}}\nstatic uint8_t io_status(unsigned x){return (uint8_t)x;}\n'''
            src.write_bytes(newline(b'\r\n' if eol=='CRLF' else b'\n',fixture))
            before=src.read_bytes()
            # Required ancestor states for canonical metadata scanner.
            for rel in ('.bb_dos622_ipl_v1_state/manifest.json',
                        '.bb_dos622_boot_diag_v1_state/repair.json',
                        '.bb_dos622_heap_rescue_v1_state/manifest.json',
                        '.bb_dos622_vga12_34_v1_state/manifest.json',
                        '.bb_dos622_vga12_30_v1_state/manifest.json',
                        '.bb_dos622_keyb92_v1_state/manifest.json'):
                p=root/rel;p.parent.mkdir(parents=True,exist_ok=True)
                atomic(p,(json.dumps({'tag':'fixture','files':[]})+'\n').encode())
            p=root/PARENT;p.parent.mkdir()
            bk=b'prior-source';atomic(p.parent/'backup_000.bin',bk)
            atomic(p,(json.dumps({'tag':PARENT_TAG,'files':[{'path':VGA,'backup':'backup_000.bin',
                        'original':SHA(bk),'installed':SHA(before)}]},indent=2)+'\n').encode())
            f=root/FLOPPY;f.parent.mkdir()
            atomic(f,(json.dumps({'tag':'BB_DOS622_FLOPPY_B_V1','files':[]})+'\n').encode())
            # Assert dependent SHA lineage propagation for parent metadata.
            p2=root/'.bb_dos622_hdd_v2_state/manifest.json';p2.parent.mkdir()
            atomic(p2,(json.dumps({'tag':'parent','files':[{'path':PARENT,'installed':SHA(p.read_bytes()),
                          'original':'f'*64,'backup':'backup_000.bin'}]})+'\n').encode())
            changes=prepare(root,False)
            assert VGA in changes and PARENT in changes and p2.relative_to(root).as_posix() in changes
            post=changes[VGA][1]
            assert post.count(TAG.encode())==1
            assert (b'\r\n' in post)==(eol=='CRLF')
            assert src.read_bytes()==before
            apply(root);verify(root)
            assert src.read_bytes()==post
            try:prepare(root,False)
            except ValueError:pass
            else:raise AssertionError('Second apply must refuse')
            restore(root)
            assert src.read_bytes()==before
            assert not (root/STATE).exists()
            print(f'SELFTEST {eol}: source SHA, manifest cascade, exact byte rollback PASS')
    # Negative tests guard unexpected source alterations and duplicate patching.
    sample=b'/* BB_DOS622_SCREEN_CLEAR_V1 BB_DOS622_VGA0B_KEYS_V1 BB_DOS622_VGA0B_STDIO_FIX_V1 */\n#include <stdio.h>\n'
    try:transform(sample)
    except ValueError:pass
    else:raise AssertionError('Missing BIOS switch accepted')
    compile_contract(HANDLER)
    print('SELFTEST PASS: repository untouched, Pico build/hardware not yet tested')


def main():
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument('command',choices=['selftest','probe','apply','verify','restore','recover'])
    args=a.parse_args()
    try:
        {'selftest':selftest,'probe':prepare,'apply':apply,'verify':verify,'restore':restore,
         'recover':lambda:restore(recover=True)}[args.command]()
    except (ValueError,AssertionError,KeyError,TypeError,OSError,RuntimeError) as exc:
        print('ERROR:',exc,file=sys.stderr);sys.exit(1)
if __name__=='__main__':main()
