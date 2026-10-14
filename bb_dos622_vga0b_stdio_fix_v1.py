#!/usr/bin/env python3
"""Fix Pico-only VGA0B printf build failure without removing installed layers.

Usage: python bb_dos622_vga0b_stdio_fix_v1.py selftest|probe|apply|verify|restore|recover

The installer proves the current VGA source matches the VGA0B/KEYS V1
manifest, adds <stdio.h> only, updates all active SHA metadata in a
convergent dependency graph, and keeps byte-exact originals for rollback.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
import bb_dos622_atbios_v1 as chain

ROOT=Path(__file__).resolve().parent
TAG='BB_DOS622_VGA0B_STDIO_FIX_V1'
STATE='.bb_dos622_vga0b_stdio_fix_v1_state'
VGA='src/bb_vga.c'
PARENT='.bb_dos622_vga0b_keys_v1_state/manifest.json'
PARENT_TAG='BB_DOS622_VGA0B_KEYS_V1'
SHA=lambda b:hashlib.sha256(b).hexdigest()
atomic=chain.atomic_bytes


def clean_rel(path):
    p=Path(path)
    if not isinstance(path,str) or not path or p.is_absolute() or '..' in p.parts:
        raise ValueError('Unsafe relative path: '+str(path))
    return path


def transform(raw:bytes)->bytes:
    if b'BB_DOS622_VGA0B_KEYS_V1' not in raw or b'[bb622-vga0b]' not in raw:
        raise ValueError('Expected VGA0B/KEYS V1 VGA diagnostic missing')
    if b'BB_DOS622_SCREEN_CLEAR_V1' not in raw:
        raise ValueError('Expected verified screen-clear layer missing')
    if b'#include <stdio.h>' in raw:
        raise ValueError('VGA stdio header already present; no change is needed')
    anchor=b'#include <string.h>'
    if raw.count(anchor)!=1:raise ValueError('Missing/ambiguous VGA string.h anchor')
    line_end=b'\r\n' if b'\r\n' in raw else b'\n'
    exact=anchor+line_end
    if raw.count(exact)!=1:raise ValueError('VGA includes in unexpected format')
    out=raw.replace(exact, exact+b'#include <stdio.h>  /* BB_DOS622_VGA0B_STDIO_FIX_V1 */'+line_end,1)
    if out.count(TAG.encode())!=1 or len(out)<=len(raw):
        raise ValueError('Unsafe stdio transform')
    return out


def load_parent(root:Path):
    p=root/PARENT
    if not p.is_file():raise ValueError('Missing VGA0B/KEYS V1 manifest: '+str(p))
    ob=json.loads(p.read_bytes())
    if ob.get('tag')!=PARENT_TAG or not isinstance(ob.get('files'),list):
        raise ValueError('Invalid VGA0B/KEYS V1 manifest')
    e=[x for x in ob['files'] if x.get('path')==VGA]
    if len(e)!=1 or not isinstance(e[0].get('installed'),str):
        raise ValueError('VGA source not uniquely tracked by V1 manifest')
    if len(e[0]['installed'])!=64:raise ValueError('Bad V1 installed SHA')
    backup=e[0].get('backup')
    if not isinstance(backup,str) or not backup.startswith('backup_'):
        raise ValueError('Unexpected V1 backup metadata')
    bf=root/'.bb_dos622_vga0b_keys_v1_state'/clean_rel(backup)
    if not bf.is_file() or SHA(bf.read_bytes())!=e[0].get('original'):
        raise ValueError('V1 backup hash mismatch; refusing to modify source')
    return e[0]


def cascade(root:Path,src_old:bytes,src_new:bytes):
    original=chain.active_metadata(root)
    if PARENT not in original:
        raise ValueError('VGA0B/KEYS V1 manifest not found in metadata graph')
    updated=dict(original)
    digest={SHA(src_old):SHA(src_new)}
    for _ in range(len(original)*8+8):
        changed=False
        for rel,raw in original.items():
            new,_=chain._update_metadata(raw,digest,rel)
            if updated[rel]!=new:
                updated[rel]=new;changed=True
            if new!=raw and digest.get(SHA(raw))!=SHA(new):
                digest[SHA(raw)]=SHA(new);changed=True
        if not changed:break
    else:raise ValueError('SHA graph did not converge')
    if updated[PARENT]==original[PARENT]:
        raise ValueError('No VGA0B/KEYS V1 manifest installed SHA was updated')
    verified=json.loads(updated[PARENT])
    entries=[x for x in verified['files'] if x.get('path')==VGA]
    if len(entries)!=1 or entries[0]['installed']!=SHA(src_new):
        raise ValueError('Expected V1 installed VGA SHA not updated exactly')
    for rel in original:
        if SHA(src_old).encode() in original[rel].lower() and VGA.encode() in original[rel] and updated[rel]==original[rel]:
            raise ValueError('Metadata still refers to old live VGA SHA: '+rel)
    return {rel:(original[rel],updated[rel]) for rel in original if original[rel]!=updated[rel]}


def prepare(root:Path=ROOT,verbose=True):
    if (root/STATE).exists():raise ValueError('Fix already installed; run verify')
    ent=load_parent(root)
    src=root/VGA
    if not src.is_file():raise ValueError('VGA source absent: '+str(src))
    old=src.read_bytes()
    if SHA(old)!=ent['installed']:
        raise ValueError('VGA source no longer matches V1 verified installed SHA; refusing')
    new=transform(old)
    changes={VGA:(old,new)}
    changes.update(cascade(root,old,new))
    if verbose:
        print(f'{VGA}: {len(old)} -> {len(new)} SHA {SHA(old)[:12]} -> {SHA(new)[:12]}')
        print(f'Updated dependent active metadata: {len(changes)-1} files')
        print('PROBE PASS: no repository files modified')
    return changes


def manifest(root:Path):
    p=root/STATE/'manifest.json'
    if not p.is_file():raise ValueError('Missing install state: '+str(p))
    m=json.loads(p.read_bytes())
    if m.get('tag')!=TAG or not isinstance(m.get('files'),list):
        raise ValueError('Corrupted stdio fix state')
    return m


def verify(root:Path=ROOT):
    m=manifest(root)
    if not m['files']:raise ValueError('Empty installer state')
    seen=set()
    for ent in m['files']:
        rel=clean_rel(ent['path'])
        if rel in seen:raise ValueError('Duplicate state path: '+rel)
        seen.add(rel)
        bn=clean_rel(ent['backup'])
        src=root/rel;bak=root/STATE/bn
        if not src.is_file() or SHA(src.read_bytes())!=ent['installed']:
            raise ValueError('Current installed SHA mismatch: '+str(src))
        if not bak.is_file() or SHA(bak.read_bytes())!=ent['original']:
            raise ValueError('Byte-exact backup SHA mismatch: '+str(bak))
    print(f'VERIFY PASS: {len(m["files"])} source/metadata files and original backups')


def apply(root:Path=ROOT):
    changes=prepare(root)
    dest=root/STATE
    dest.mkdir()
    m={'tag':TAG,'files':[]}
    try:
        for i,(rel,(old,new)) in enumerate(changes.items()):
            bn=f'backup_{i:03d}.bin'
            atomic(dest/bn,old)
            m['files'].append({'path':rel,'backup':bn,'original':SHA(old),'installed':SHA(new)})
        atomic(dest/'manifest.json',(json.dumps(m,indent=2)+'\n').encode())
        for rel,(old,new) in changes.items():atomic(root/rel,new)
        verify(root)
    except BaseException:
        for rel,(old,_) in changes.items():atomic(root/rel,old)
        shutil.rmtree(dest,ignore_errors=True)
        raise
    print('APPLIED: VGA0B Pico stdio compile fix; BIOS/keyboard behavior untouched')


def restore(root:Path=ROOT,recover=False):
    if not recover:verify(root)
    m=manifest(root)
    originals={}
    for e in m['files']:
        rel=clean_rel(e['path'])
        b=root/STATE/clean_rel(e['backup'])
        s=root/rel
        if not b.is_file() or SHA(b.read_bytes())!=e['original']:
            raise ValueError('Damaged backup; refusing restore: '+str(b))
        if recover and s.is_file() and SHA(s.read_bytes()) not in (e['original'],e['installed']):
            raise ValueError('Unexpected intervening edit; refusing recover: '+str(s))
        originals[rel]=b.read_bytes()
    for rel,raw in originals.items():atomic(root/rel,raw)
    shutil.rmtree(root/STATE)
    print('RESTORE PASS: all exact pre-fix source/metadata bytes restored')


def compile_regression(old:bytes,new:bytes):
    cc=shutil.which('gcc') or shutil.which('cc') or shutil.which('clang')
    if not cc:
        print('Host GCC/Clang missing: Pico-only branch compilation not checked');return
    with tempfile.TemporaryDirectory() as td:
        td=Path(td)
        oldf=td/'before.c';newf=td/'after.c'
        oldf.write_bytes(old);newf.write_bytes(new)
        def run(path):
            return subprocess.run([cc,'-std=c11','-DPICO_ON_DEVICE=1','-Werror=implicit-function-declaration','-fsyntax-only',str(path)],capture_output=True,text=True)
        a=run(oldf);b=run(newf)
        if a.returncode==0 or 'stdout' not in a.stderr:
            raise AssertionError('Regression fixture failed to reproduce undeclared stdout')
        if b.returncode!=0:
            raise AssertionError('PICO_ON_DEVICE=1 C compile still fails: '+b.stderr[:2500])
        print('C11 Pico-only VGA diagnostic regression PASS: missing stdout before, valid after')


def selftest():
    # The critical regression: unlike the old VGA0B test, stdio is NOT
    # included by a test harness prior to the inserted PICO_ON_DEVICE code.
    fixture=r"""#include <stdint.h>
#include <stdbool.h>
#include <string.h>
/* BB_DOS622_SCREEN_CLEAR_V1 */
static int bb_sd_dos622_active(void){return 1;}
static unsigned cga_palette_select;
/* BB_DOS622_VGA0B_KEYS_V1 */
static int vga_probe(unsigned *ax,unsigned bx){
    if(bb_sd_dos622_active()) {
        printf("[bb622-vga0b] INT10 AH=0B BX=%04X AX=%04X\\n",bx,*ax);
        fflush(stdout);
    }
    return 1;
}
int main(void){unsigned ax=0x0b40; return !vga_probe(&ax,0);}
""".encode()
    for eol in (b'\n',b'\r\n'):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            src=root/VGA;src.parent.mkdir(parents=True)
            orig=fixture.replace(b'\n',eol)
            src.write_bytes(orig)
            def meta(rel,tag,entries):
                p=root/rel;p.parent.mkdir(parents=True,exist_ok=True)
                chain.atomic_bytes(p,json.dumps({'tag':tag,'files':entries},indent=2).encode())
            md=[('.bb_dos622_ipl_v1_state/manifest.json','IPL'),
                ('.bb_dos622_boot_diag_v1_state/repair.json','DIAG'),
                ('.bb_dos622_heap_rescue_v1_state/manifest.json','HEAP'),
                ('.bb_dos622_vga12_34_v1_state/manifest.json','VGA34'),
                ('.bb_dos622_vga12_30_v1_state/manifest.json','VGA30'),
                ('.bb_dos622_keyb92_v1_state/manifest.json','KEYB92')]
            for rel,tag in md:meta(rel,tag,[])
            v1dir=root/'.bb_dos622_vga0b_keys_v1_state'
            v1dir.mkdir()
            pre=b'old-vga';chain.atomic_bytes(v1dir/'backup_000.bin',pre)
            meta(PARENT,PARENT_TAG,[{'path':VGA,'backup':'backup_000.bin','original':SHA(pre),'installed':SHA(orig)}])
            # A dependent ancestor active checksum of the V1 manifest.
            old_manifest=(root/PARENT).read_bytes()
            meta('.bb_dos622_hdd_v2_state/manifest.json','HDD_V2',
                 [{'path':PARENT,'backup':'backup_000.bin','original':'f'*64,'installed':SHA(old_manifest)}])
            changed=prepare(root,False)
            assert VGA in changed and PARENT in changed
            assert '.bb_dos622_hdd_v2_state/manifest.json' in changed
            target=changed[VGA][1]
            assert target.count(b'#include <stdio.h>')==1
            assert (b'\r\n' in target) == (eol==b'\r\n')
            apply(root)
            verify(root)
            # The newest installer verifies its current SHA after the layer.
            parent=json.loads((root/PARENT).read_bytes())
            assert parent['files'][0]['installed']==SHA(target)
            try:prepare(root,False)
            except ValueError:pass
            else:raise AssertionError('Reapplication must refuse')
            restore(root)
            assert src.read_bytes()==orig
            assert (root/PARENT).read_bytes()==old_manifest
            compile_regression(orig,target)
            print('SELFTEST '+('CRLF' if eol==b'\r\n' else 'LF')+': SHA cascade, safe refusal, exact rollback PASS')
    print('SELFTEST PASS: no files outside temporary fixtures modified')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('command',choices=['selftest','probe','apply','verify','restore','recover'])
    a=ap.parse_args()
    try:
        {'selftest':selftest,'probe':prepare,'apply':apply,'verify':verify,
         'restore':restore,'recover':lambda:restore(recover=True)}[a.command]()
    except (ValueError,AssertionError,OSError,RuntimeError,KeyError,TypeError) as exc:
        print('ERROR:',exc,file=sys.stderr)
        sys.exit(1)
if __name__=='__main__':main()
