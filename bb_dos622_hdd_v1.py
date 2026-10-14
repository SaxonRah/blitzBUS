#!/usr/bin/env python3
"""Reversible MS-DOS 6.22 BIOS hard-disk installer. No Git patches.

Adds a separate BIOS DL=80h, 65x16x63 FAT16 HDD image with real SD-backed
read/write. Does NOT modify legacy DRIVE_C.IMG, DOS2/BOOT.IMG or DOS622.IMG.

Requires bb_dos622_atbios_v1.py (installed predecessor; reused solely for
byte-preserving SHA-manifest dependency updating). Commands:
  python bb_dos622_hdd_v1.py selftest|probe|apply|verify|restore|recover
"""
from pathlib import Path
import argparse,hashlib,json,os,re,shutil,subprocess,sys,tempfile
import bb_dos622_atbios_v1 as prior

ROOT=Path(__file__).resolve().parent
TAG='BB_DOS622_HDD_V1'
STATE='.bb_dos622_hdd_v1_state'
TARGETS=('sd_boot/bb_sd_boot.c','src/bb_dos622_bios.inc')
NEW_FILES={
  'sd_boot/bb_dos622_hdd_sd_v1.inc':'bb_dos622_hdd_sd_v1.inc',
  'src/bb_dos622_hdd_bios_v1.inc':'bb_dos622_hdd_bios_v1.inc',
}
sha=prior.sha
atomic=prior.atomic_bytes

def replace_once(buf, a, b, path):
    n=buf.count(a)
    if n!=1:raise ValueError(f'{path}: expected ONE anchor {a[:100]!r}; found {n}; no files touched')
    return buf.replace(a,b,1)

def transform(rel,buf):
    if TAG.encode() in buf:raise ValueError(f'{rel}: already installed')
    nl=b'\r\n' if buf.count(b'\r\n')>buf.count(b'\n')/2 else b'\n'
    if rel=='sd_boot/bb_sd_boot.c':
        # Existing DOS622 bootstrap is the only safe mount point.
        anchor=b'#include "bb_dos622_sd.inc"'
        buf=replace_once(buf,anchor,anchor+nl+
           b'/* BB_DOS622_HDD_V1: separate DOS6 BIOS HDD */'+nl+
           b'#include "bb_dos622_hdd_sd_v1.inc"',rel)
        anchor=b'bb622_mount(drive); /* BB_DOS622_IPL_V1 opt-in only */'
        buf=replace_once(buf,anchor,anchor+nl+
           b'    bb622_hd_mount(drive); /* BB_DOS622_HDD_V1 */',rel)
    elif rel=='src/bb_dos622_bios.inc':
        anchor=b'static bool BB622_FLASH bb622_int13(MdRuntime *rt)'
        if buf.count(anchor)!=1:raise ValueError('Cannot locate original DOS6 INT13')
        buf=replace_once(buf,anchor,
           b'/* BB_DOS622_HDD_V1: BIOS 80h service */'+nl+
           b'#include "bb_dos622_hdd_bios_v1.inc"'+nl+nl+anchor,rel)
        head=buf.index(anchor)
        body=buf.index(b'{',head)
        p=buf.find(b'MdX86 *c = &rt->cpu;',body,body+150)
        if p<0:raise ValueError('Unexpected INT13 CPU initialization; refusing patch')
        e=p+len(b'MdX86 *c = &rt->cpu;')
        buf=buf[:e]+nl+b'    if ((uint8_t)c->r[MD_X86_DX] == 0x80u) return bb622_hd_int13(rt); /* BB_DOS622_HDD_V1 */'+buf[e:]
        old=b'md_x86_write8(c, 0x0040u, 0x0075u, 0u); /* hard disks advertised */'
        new=b'md_x86_write8(c, 0x0040u, 0x0075u, bb_sd_hdd_available()?1u:0u); /* BB_DOS622_HDD_V1: real BIOS 80h */'
        buf=replace_once(buf,old,new,rel)
    else:raise ValueError(f'Invalid target {rel}')
    return buf


def parent_cascade(root, digests):
    old=prior.active_metadata(root)
    modified=dict(old)
    digest_changes=dict(digests)
    count={}
    for step in range(len(old)*8+8):
        changed=False
        for rel,base in old.items():
            updated,hits=prior._update_metadata(base,digest_changes,rel)
            if updated!=modified[rel]:modified[rel]=updated;count[rel]=hits;changed=True
            if hits:
                digest_changes[sha(base)]=sha(updated)
        if not changed:break
    else:raise ValueError('Metadata SHA graph did not converge')
    # Both original installed source digests MUST be represented in active
    # fields in parent metadata; never silently orphan backup records.
    for original_digest in digests:
        if not any((original_digest.encode() in old[k].lower() and k in count) for k in old):
            raise ValueError(f'No active parent SHA tracking source {original_digest}; refusing')
    return {r:(old[r],modified[r]) for r in old if modified[r]!=old[r]}


def prepare(root=ROOT,report=True):
    if (root/STATE).exists():raise ValueError('Installation state already exists; verify or restore')
    state_path=root/'.bb_dos622_atbios_v1_state/manifest.json'
    if not state_path.is_file():raise ValueError('AT BIOS Phase1 install state missing')
    before={};after={};diffs={}
    for rel in TARGETS:
        p=root/rel
        if not p.is_file():raise ValueError(f'Missing target {p}')
        data=p.read_bytes();out=transform(rel,data)
        before[rel]=data;after[rel]=out;diffs[sha(data)]=sha(out)
    # Trust only the active SHA chain installed by the earlier package.
    # Existing older parent manifests are verified by the user's prior checks.
    for rel,loc in NEW_FILES.items():
        if (root/rel).exists():raise ValueError(f'{rel} already exists; refusing overwrite')
        contents=(root/loc)
        if not contents.is_file():raise ValueError(f'Extract {loc} into repo root')
        raw=contents.read_bytes()
        if TAG.encode() not in raw:raise ValueError(f'{loc} missing module signature')
        after[rel]=raw;before[rel]=None
    changes=parent_cascade(root,diffs)
    result={r:(before[r],after[r]) for r in [*TARGETS,*NEW_FILES]}
    result.update(changes)
    if report:
        for r in TARGETS:print(f'{r}: {len(before[r])}->{len(after[r])} SHA {sha(before[r])[:12]}->{sha(after[r])[:12]}')
        for r in NEW_FILES:print(f'{r}: NEW {len(after[r])} bytes')
        print(f'Parent manifest cascade: {len(changes)} metadata files')
        print('PROBE PASS; repository unchanged')
    return result

def probe(root=ROOT):prepare(root)

def _state(root):
    p=root/STATE/'manifest.json'
    if not p.is_file():raise ValueError(f'State absent: {p}')
    j=json.loads(p.read_bytes())
    if j.get('tag')!=TAG:raise ValueError('Bad installer state tag')
    return j

def verify(root=ROOT):
    state=_state(root)
    for ent in state['files']:
        p=root/ent['path']
        if not p.is_file() or sha(p.read_bytes())!=ent['installed']:raise ValueError(f'Installed file changed {p}')
        b=ent['backup']
        if b:
            f=root/STATE/b
            if not f.is_file() or sha(f.read_bytes())!=ent['original']:raise ValueError(f'Backup mismatch {f}')
        elif ent['original'] is not None:raise ValueError('Broken new-file state')
    print(f'VERIFY PASS: {len(state["files"])} source/module/parent files and all backups intact')

def apply(root=ROOT):
    changes=prepare(root)
    state=root/STATE
    state.mkdir()
    manifest={'tag':TAG,'files':[]}
    try:
        for i,(rel,(old,new)) in enumerate(changes.items()):
            bk=f'backup_{i:03d}.bin' if old is not None else None
            if bk:atomic(state/bk,old)
            manifest['files'].append({'path':rel,'backup':bk,'original':sha(old) if old is not None else None,'installed':sha(new)})
        atomic(state/'manifest.json',(json.dumps(manifest,indent=2)+'\n').encode())
        for rel,(old,new) in changes.items():atomic(root/rel,new)
        verify(root)
    except BaseException:
        for rel,(old,_) in changes.items():
            if old is None:(root/rel).unlink(missing_ok=True)
            else:atomic(root/rel,old)
        shutil.rmtree(state,ignore_errors=True)
        raise
    print('APPLIED: DOS622 HDD only. Legacy DOS2 images unchanged')

def restore(root=ROOT,recover=False):
    if not recover:verify(root)
    rec=_state(root)
    for ent in rec['files']:
        rel=ent['path'];p=root/rel;bk=ent['backup']
        if bk:
            b=root/STATE/bk
            if not b.is_file() or sha(b.read_bytes())!=ent['original']:raise ValueError(f'Backup corrupt: {b}')
        if recover and p.exists() and sha(p.read_bytes()) not in (ent['original'],ent['installed']):
            raise ValueError(f'Unsafe recover: {p} has unknown bytes')
    for ent in rec['files']:
        p=root/ent['path'];bk=ent['backup']
        if bk:atomic(p,(root/STATE/bk).read_bytes())
        else:p.unlink(missing_ok=True)
    shutil.rmtree(root/STATE)
    print('RESTORED: original source/metadata bytes exactly, new modules removed')

def selftest():
    for ending in ('LF','CRLF'):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root/'src').mkdir();(root/'sd_boot').mkdir()
            sd=(b'#include "bb_dos622_sd.inc"\nbb622_mount(drive); /* BB_DOS622_IPL_V1 opt-in only */\n')
            bios=(b'static bool BB622_FLASH bb622_int13(MdRuntime *rt)\n{\n    MdX86 *c = &rt->cpu;\n}\n'
              b'md_x86_write8(c, 0x0040u, 0x0075u, 0u); /* hard disks advertised */\n')
            if ending=='CRLF':sd=sd.replace(b'\n',b'\r\n');bios=bios.replace(b'\n',b'\r\n')
            (root/TARGETS[0]).write_bytes(sd);(root/TARGETS[1]).write_bytes(bios)
            for r,loc in NEW_FILES.items():shutil.copyfile(ROOT/loc,root/loc)
            (root/'.bb_dos622_atbios_v1_state').mkdir()
            (root/'.bb_dos622_atbios_v1_state/manifest.json').write_text('{"tag":"BB_DOS622_ATBIOS_V1"}')
            manifests={
                '.bb_dos622_ipl_v1_state/manifest.json':{'tag':'IPL','files':{TARGETS[0]:{'original':'a'*64,'installed':sha(sd)},TARGETS[1]:{'original':'a'*64,'installed':sha(bios)}}},
                '.bb_dos622_boot_diag_v1_state/repair.json':{'tag':'DIAG','files':{TARGETS[1]:{'old':'b'*64,'new':sha(bios)}}},
                '.bb_dos622_heap_rescue_v1_state/manifest.json':{'files':{TARGETS[1]:{'old':'b'*64,'new':sha(bios)}}},
                '.bb_dos622_vga12_34_v1_state/manifest.json':{'files':{}},
                '.bb_dos622_vga12_30_v1_state/manifest.json':{'files':{}},
                '.bb_dos622_keyb92_v1_state/manifest.json':{'files':{TARGETS[0]:{'after':sha(sd)}}},
            }
            for rel,obj in manifests.items():p=root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(obj))
            snapshot={p:p.read_bytes() for p in [root/TARGETS[0],root/TARGETS[1],*(root/k for k in manifests)]}
            prepare(root,report=False);apply(root);verify(root);restore(root)
            for p,b in snapshot.items():assert p.read_bytes()==b, f'Not restored: {p}'
            for rel in NEW_FILES:assert not (root/rel).exists()
        print('SELFTEST',ending,'PASS two-source SHA cascade/restore')
    print('SELFTEST PASS; hardware behavior still requires Pico run')

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action',choices=['selftest','probe','apply','verify','restore','recover'])
    args=ap.parse_args()
    try:{'selftest':selftest,'probe':probe,'apply':apply,'verify':verify,'restore':restore,'recover':lambda:restore(recover=True)}[args.action]()
    except (ValueError,OSError,AssertionError,KeyError,json.JSONDecodeError) as e:
        print('ERROR:',e,file=sys.stderr);sys.exit(1)
if __name__=='__main__':main()
