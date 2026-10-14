#!/usr/bin/env python3
"""Reversible, exact-anchor installer for blitzBUS MS-DOS 6.x BIOS bootstrap v1.
Install this script and both .inc files in C:\\blitzBUS; never uses Git patches.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile

ROOT=Path(__file__).resolve().parent
TAG='BB_DOS622_IPL_V1'
STORE='.bb_dos622_ipl_v1_state'
INCS={'sd_boot/bb_dos622_sd.inc':'bb_dos622_sd.inc',
      'src/bb_dos622_bios.inc':'bb_dos622_bios.inc'}
FILES=('sd_boot/bb_sd_boot.c','src/bb_live.c')

def h(raw): return hashlib.sha256(raw).hexdigest()

def replace_once(raw:bytes, needle:bytes, out:bytes, path:str):
    if raw.count(needle)!=1:
        raise ValueError(f'{path}: expected one anchor {needle[:70]!r}, found {raw.count(needle)}')
    return raw.replace(needle,out,1)

def transform(rel,raw):
    if TAG.encode() in raw: raise ValueError(f'{rel}: already contains {TAG} (use verify)')
    eol=b'\r\n' if b'\r\n' in raw else b'\n'
    if rel=='sd_boot/bb_sd_boot.c':
        raw=replace_once(raw,b'bool bb_sd_boot_image(uint8_t *dest, unsigned bytes)',
            b'/* '+TAG.encode()+b' - external optional SD boot floppy */'+eol+
            b'#include "bb_dos622_sd.inc"'+eol+eol+
            b'bool bb_sd_boot_image(uint8_t *dest, unsigned bytes)',rel)
        raw=replace_once(raw,b'    sd->state.mounted = true;',
            b'    sd->state.mounted = true;'+eol+
            b'    bb622_mount(drive); /* '+TAG.encode()+b' opt-in only */',rel)
    else:
        raw=replace_once(raw,b'static int start(MdRuntime *rt)',
            b'/* '+TAG.encode()+b' - initial BIOS implementation lives in flash */'+eol+
            b'#include "bb_dos622_bios.inc"'+eol+eol+
            b'static int start(MdRuntime *rt)',rel)
        needle=b'    rt->hooks.interrupt = bb_v15_interrupt;'
        raw=replace_once(raw,needle,
            needle+eol+
            b'#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE'+eol+
            b'    /* '+TAG.encode()+b': boot a real disk only when DOS622.TXT = 1. */'+eol+
            b'    if (bb_sd_dos622_active()) {'+eol+
            b'        bb_v15_original_interrupt = bb622_bios_interrupt;'+eol+
            b'        if (!bb622_boot_floppy(rt)) {'+eol+
            b'            failed = 1; fail_reason = "DOS622 sector read failed"; return 0;'+eol+
            b'        }'+eol+
            b'    }'+eol+
            b'#endif',rel)
    return raw

def probe(root=ROOT,log=True):
    outputs={}
    if (root/STORE).exists(): raise ValueError('Installation state present; use verify or restore')
    for rel in FILES:
        src=root/rel
        if not src.is_file(): raise ValueError(f'Missing source: {src}')
        old=src.read_bytes(); new=transform(rel,old)
        outputs[rel]=(old,new)
        if log:print(f'{rel}: anchor PASS {len(old)} -> {len(new)} bytes')
    for rel,local in INCS.items():
        if (root/rel).exists():raise ValueError(f'{rel} exists: refusing overwrite')
        if not (root/local).is_file():raise ValueError(f'Expected extracted {root/local}')
        outputs[rel]=(None,(root/local).read_bytes())
        if log:print(f'{rel}: new source file')
    if log:print('PROBE PASS: no files modified')
    return outputs

def apply(root=ROOT):
    out=probe(root)
    state=root/STORE
    state.mkdir()
    manifest={'tag':TAG,'files':{}}
    try:
        for rel,(before,after) in out.items():
            dest=root/rel
            if before is not None:
                backup=state/(rel.replace('/','__')+'.bak')
                backup.write_bytes(before)
            dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_bytes(after)
            manifest['files'][rel]={'original':h(before) if before is not None else None,'installed':h(after)}
        (state/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
        verify(root)
    except Exception:
        for rel,(before,_) in out.items():
            dst=root/rel
            if before is None:dst.unlink(missing_ok=True)
            else:dst.write_bytes(before)
        shutil.rmtree(state,ignore_errors=True)
        raise
    print('APPLIED: DOS 6.x BIOS bootstrap opt-in; DOS2 unchanged if no DOS622.TXT')

def verify(root=ROOT):
    state=root/STORE
    manifest=json.loads((state/'manifest.json').read_text(encoding='utf8'))
    if manifest.get('tag')!=TAG:raise ValueError('Wrong manifest tag')
    for rel,info in manifest['files'].items():
        if h((root/rel).read_bytes()) != info['installed']:
            raise ValueError(f'Verification failed: file changed {rel}')
        if info['original'] is not None:
            backup=state/(rel.replace('/','__')+'.bak')
            if h(backup.read_bytes()) != info['original']:
                raise ValueError(f'Backup corrupted: {rel}')
    print('VERIFIED: source SHA256 and byte-identical backups intact')

def restore(root=ROOT):
    verify(root)
    state=root/STORE
    manifest=json.loads((state/'manifest.json').read_text(encoding='utf8'))
    for rel,info in manifest['files'].items():
        dest=root/rel
        if info['original'] is None:dest.unlink()
        else:dest.write_bytes((state/(rel.replace('/','__')+'.bak')).read_bytes())
    shutil.rmtree(state)
    print('RESTORED: DOS622 boot layer removed byte-for-byte')

def selftest():
    for eol in (b'\n',b'\r\n'):
        with tempfile.TemporaryDirectory(prefix='bb622_test_') as td:
            root=Path(td)
            for rel,body in {
                'sd_boot/bb_sd_boot.c': b'sd->state.mounted = true;\n' # replaced below
                                      b'    sd->state.mounted = true;\n'
                                      b'bool bb_sd_boot_image(uint8_t *dest, unsigned bytes)\n',
                'src/bb_live.c': b'rt->hooks.interrupt = bb_v15_interrupt;\n'
                                 b'    rt->hooks.interrupt = bb_v15_interrupt;\n'
                                 b'static int start(MdRuntime *rt)\n',
            }.items():
                p=root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(body.replace(b'\n',eol))
            (root/'bb_dos622_sd.inc').write_bytes(b'/* sd test */\n')
            (root/'bb_dos622_bios.inc').write_bytes(b'/* bios test */\n')
            pre={rel:(root/rel).read_bytes() for rel in FILES}
            probe(root,False);apply(root);restore(root)
            for rel,data in pre.items():
                assert (root/rel).read_bytes()==data, f'{rel}: exact rollback failed'
            for rel in INCS:assert not (root/rel).exists()
    print('SELFTEST PASS: LF/CRLF, unique anchors, install/verify/exact-byte restore')

def main():
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument('action',choices=['selftest','probe','apply','verify','restore'])
    opt=a.parse_args()
    {'selftest':selftest,'probe':probe,'apply':apply,'verify':verify,'restore':restore}[opt.action]()

if __name__=='__main__':
    try: main()
    except (ValueError,AssertionError,OSError,KeyError) as e:
        print('ERROR: '+str(e),file=sys.stderr);sys.exit(1)
