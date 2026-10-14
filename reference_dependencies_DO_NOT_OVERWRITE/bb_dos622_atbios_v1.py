#!/usr/bin/env python3
"""DOS 6.22 / AT BIOS Phase 1: VGA font geometry + BIOS write-string.

Reversible, opt-in DOS622 layer for C:\blitzBUS; no Git patches.
Usage: python bb_dos622_atbios_v1.py selftest|probe|apply|verify|restore|recover

Requires the successful VGA12/30 source and its verified state manifest.
This is NOT a complete 386 BIOS: extended RAM/A20/IRQ0 still need real backing.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
SOURCE = "src/bb_live.c"
MODULE = "src/bb_dos622_atbios_v1.inc"
MODULE_LOCAL = "bb_dos622_atbios_v1.inc"
TAG = "BB_DOS622_ATBIOS_V1"
STATE_NAME = ".bb_dos622_atbios_v1_state"
PREREQ = ".bb_dos622_vga12_30_v1_state/manifest.json"
KEYB92_STATE = ".bb_dos622_keyb92_v1_state"

def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def atomic_bytes(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, fn = tempfile.mkstemp(prefix=".bbatbios-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
        os.replace(fn, path)
    finally:
        try: os.unlink(fn)
        except FileNotFoundError: pass


def transform(raw: bytes) -> bytes:
    if TAG.encode() in raw: raise ValueError("Already installed: use verify")
    for mark in (b"BB_DOS622_VGA12_30_V1", b"BB_DOS622_VGA12_34_V1", b"BB_DOS622_P61_REFRESH_V1", b"BB_DOS622_KEYBA2_V3"):
        if mark not in raw: raise ValueError(f"Required previous source layer missing: {mark.decode()}")
    anchor=b"static unsigned bb_v61_events;"
    native=(b"if (bb622_vga12_34(&ax,bx) || bb622_vga12_30(&ax,bx) || bb_vga_int10(&ax,&bx,&cx,&dx,&es,&bp,&f)) {")
    interp=(b"if (bb622_vga12_34(&ax,bx) || bb622_vga12_30(&ax,bx) || bb_vga_int10(&ax,&bx,&cx,&dx,&es,&bp,&flags)) {")
    if any(raw.count(x) != 1 for x in (anchor, native, interp)):
        raise ValueError("Expected exact VGA12/30 native/interpreter anchors; repository changed; no files modified")
    p_native=raw.find(native); p_interp=raw.find(interp)
    start_native=raw.find(b"static int hook_int("); start_interp=raw.find(b"static bool bb_v15_interrupt(")
    if not (start_native >= 0 and start_native < p_native < start_interp < p_interp):
        raise ValueError("Native/interpreter INT10 call hierarchy cannot be proven")
    nl=b"\r\n" if b"\r\n" in raw else b"\n"
    include=b"/* BB_DOS622_ATBIOS_V1: DOS622 AT/VGA text compatibility */"+nl+b'#include "bb_dos622_atbios_v1.inc"'+nl
    raw=raw.replace(anchor,include+anchor,1)
    raw=raw.replace(native,b"if (bb622_vga12_34(&ax,bx) || bb622_vga12_30(&ax,bx) || bb622_at_vga_int10(&ax,&bx,&cx,&dx,&es,&bp,&f) || bb_vga_int10(&ax,&bx,&cx,&dx,&es,&bp,&f)) {",1)
    raw=raw.replace(interp,b"if (bb622_vga12_34(&ax,bx) || bb622_vga12_30(&ax,bx) || bb622_at_vga_int10(&ax,&bx,&cx,&dx,&es,&bp,&flags) || bb_vga_int10(&ax,&bx,&cx,&dx,&es,&bp,&flags)) {",1)
    assert raw.count(TAG.encode()) == 1
    return raw


def prereq_sha(root: Path):
    path=root/PREREQ
    if not path.is_file(): raise ValueError(f"Missing verified prior installer manifest: {path}")
    info=json.loads(path.read_bytes())
    if info.get("tag") != "BB_DOS622_VGA12_30_V1" or info.get("source") != SOURCE:
        raise ValueError("Unexpected VGA12/30 prior installer state")
    for ent in info.get("files",[]):
        if ent.get("path")==SOURCE:
            expected=ent.get("installed")
            if not isinstance(expected,str) or len(expected)!=64:break
            return expected.lower()
    raise ValueError("Cannot identify prior installed source checksum; refusing to patch")

META_BASENAMES = {"manifest.json", "repair.json"}
# These values represent the currently installed file (or currently installed
# parent metadata); older/source/backup hashes have different field names.
ACTIVE_SHA_KEYS = frozenset({
    "installed", "new", "after", "current", "post", "parent_after",
    "installed_sha", "installed_hash", "installed_sha256",
    "new_sha", "new_hash", "new_sha256",
    "after_sha", "after_hash", "after_sha256",
    "current_sha", "current_hash", "current_sha256",
    "post_sha", "post_hash", "post_sha256",
    "sha_after", "sha_new", "sha_installed", "sha_current",
    "parent_after_sha", "parent_after_hash", "parent_after_sha256",
    "src_new", "src_after", "src_installed", "src_current",
    "source_new", "source_after", "source_installed", "source_current",
    "file_new", "file_after", "file_installed", "file_current",
    "src_new_sha", "src_after_sha", "src_installed_sha", "src_current_sha",
    "source_new_sha", "source_after_sha", "source_installed_sha", "source_current_sha",
})
HISTORICAL_SHA_KEYS = frozenset({
    "original", "old", "before", "previous", "parent_before",
    "original_sha", "original_hash", "original_sha256",
    "old_sha", "old_hash", "old_sha256",
    "before_sha", "before_hash", "before_sha256",
    "backup", "backup_sha", "backup_hash", "backup_sha256",
    "parent_before_sha", "parent_before_hash", "parent_before_sha256",
})
# Byte preserving: only the 64 hexadecimal characters of a JSON key/value
# string are replaced. Original spacing, line endings, ordering and indentation
# are never reserialized. This supports 'installed', 'new', 'after', and
# 'parent_after' without presuming a particular parent manifest schema.
KV_SHA = re.compile(rb'"(?P<key>[^"\\]+)"\s*:\s*"(?P<digest>[A-Fa-f0-9]{64})"')


def active_metadata(root: Path):
    found = {}
    for folder in sorted(root.glob(".bb_dos622_*_state")):
        if not folder.is_dir() or folder.name == STATE_NAME:
            continue
        for path in sorted(folder.glob("*.json")):
            if path.name not in META_BASENAMES:
                continue
            rel = path.relative_to(root).as_posix()
            raw = path.read_bytes()
            try:
                parsed = json.loads(raw)
            except Exception as exc:
                raise ValueError(f"Malformed active parent metadata {rel}: {exc}") from exc
            if not isinstance(parsed, dict):
                raise ValueError(f"Unexpected active metadata type in {rel}; expected JSON object")
            found[rel] = raw
    expected = [
        ".bb_dos622_ipl_v1_state/manifest.json",
        ".bb_dos622_boot_diag_v1_state/repair.json",
        ".bb_dos622_heap_rescue_v1_state/manifest.json",
        ".bb_dos622_vga12_34_v1_state/manifest.json",
        ".bb_dos622_vga12_30_v1_state/manifest.json",
    ]
    for path in expected:
        if path not in found:
            raise ValueError(f"Missing expected installed parent metadata: {path}")
    if not any(rel.startswith(KEYB92_STATE + "/") for rel in found):
        raise ValueError(f"Missing active metadata under {KEYB92_STATE}; do not patch unverified state")
    return found


def _key_is_active(key: str):
    key = key.lower()
    if key in ACTIVE_SHA_KEYS:
        return True
    # Recognize a constrained naming convention but not ambiguous keys like
    # 'sha', 'checksum', 'digest', or metadata 'original'.
    parts = re.split(r"[_-]", key)
    return (len(parts) >= 2 and (
                (parts[0] in {"after", "installed", "current", "new", "post"}
                 and all(x in {"sha", "sha256", "hash", "digest", "checksum", "parent", "file", "source"}
                         for x in parts[1:]))
                or (parts[0] in {"src", "source", "file", "parent"}
                    and parts[1] in {"after", "installed", "current", "new", "post"}
                    and all(x in {"sha", "sha256", "hash", "digest", "checksum"}
                            for x in parts[2:]))))


def _key_is_historical(key: str):
    key = key.lower()
    if key in HISTORICAL_SHA_KEYS:
        return True
    if key.startswith(("original_", "old_", "before_", "backup_", "previous_", "parent_before_")):
        return True
    parts = re.split(r"[_-]", key)
    return len(parts) >= 2 and parts[0] in {"src", "source", "file", "parent"} and parts[1] in {"original", "old", "before", "backup", "previous"}


def _update_metadata(raw: bytes, changes: dict[str, str], rel: str):
    """Only replace SHA values in explicit active/current fields."""
    replacements = []
    blocked = []
    for m in KV_SHA.finditer(raw):
        key = m.group("key").decode("ascii", "replace")
        old = m.group("digest").decode("ascii")
        target = changes.get(old.lower())
        if target is None or target == old.lower():
            continue
        if _key_is_active(key):
            replacement = target.upper() if old.isupper() else target
            replacements.append((m.start("digest"), m.end("digest"), replacement.encode("ascii")))
        elif not _key_is_historical(key):
            blocked.append(key)
    if blocked:
        raise ValueError(f"Unknown current-SHA key(s) {sorted(set(blocked))} in {rel}; "
                         "refusing to guess metadata semantics. Supply the JSON for review.")
    if not replacements:
        return raw, 0
    out = bytearray(raw)
    for start, end, value in replacements:
        assert len(value) == end - start == 64
        out[start:end] = value
    data = bytes(out)
    if len(data) != len(raw):
        raise AssertionError(f"Metadata length changed unexpectedly: {rel}")
    # Validate schema neutral: the resulting JSON is still parseable.
    json.loads(data)
    return data, len(replacements)


def parent_manifests(root: Path, pre_sha: str, post_sha: str):
    """Update active checksums across nested formats and cascading parents.

    A higher-stage manifest may record the SHA of a lower-stage manifest.
    Thus changing the source -> IPL metadata -> boot_diag repair -> KEYB92
    manifest is a dependency graph. Iterate to a fixed point without touching
    historical backups and without reformatting any JSON.
    """
    original = active_metadata(root)
    after = dict(original)
    # Map old file checksum to newest file checksum (source initially).
    digest_changes = {pre_sha: post_sha}
    counts = {}
    for iteration in range(len(original) * 8 + 8):
        changed = False
        for rel, before in original.items():
            updated, hits = _update_metadata(before, digest_changes, rel)
            if hits:
                # Historical SHA always refers to the original bytes on disk.
                # Replacements can be recomputed as dependency hashes evolve.
                old_digest = sha(before)
                new_digest = sha(updated)
                if digest_changes.get(old_digest) != new_digest:
                    digest_changes[old_digest] = new_digest
                    changed = True
                if after[rel] != updated:
                    after[rel] = updated
                    counts[rel] = hits
                    changed = True
        if not changed:
            break
    else:
        raise ValueError("Metadata SHA dependency graph did not converge; refusing modification")

    # No silent misses for parent manifests claiming to hold the pre-patch
    # source checksum: it must be an active/current value, or the manifest
    # is either unrelated or incompatible. Historical-only references remain.
    required = f"{KEYB92_STATE}/manifest.json"
    if required not in after:
        raise ValueError(f"Missing expected KEYB92 manifest: {required}")
    keyb92_raw = original[required]
    if pre_sha.encode("ascii") not in keyb92_raw.lower() or required not in counts:
        raise ValueError("KEYB92 manifest does not actively track the installed source SHA; "
                         "refusing modification (inspect actual KEYB92 manifest)")
    for rel, before in original.items():
        if (pre_sha.encode("ascii") in before.lower() and SOURCE.encode("ascii") in before
                and rel not in counts):
            raise ValueError(f"Metadata references source SHA but has no supported active field: {rel}")
    result = {rel: (original[rel], after[rel]) for rel in original if after[rel] != original[rel]}
    for rel, (old, new) in result.items():
        if sha(old) == sha(new):
            raise AssertionError(f"Unexpected unchanged state: {rel}")
    return result, counts



def prepare(root: Path = ROOT, report=True, strict=True):
    if (root / STATE_NAME).exists():
        raise ValueError(f"{STATE_NAME} already exists; use verify, restore, or recover")
    source=root/SOURCE; mod=root/MODULE
    if not source.is_file(): raise ValueError(f"Source missing: {source}")
    if mod.exists(): raise ValueError(f"Module exists: {mod}; refusing overwrite")
    local=Path(__file__).resolve().parent/MODULE_LOCAL
    if not local.is_file(): raise ValueError(f"Extract {MODULE_LOCAL} next to installer first")
    original=source.read_bytes(); before=sha(original)
    if strict and before != prereq_sha(root):
        raise ValueError(f"Source does not match current VGA12/30 install SHA: {before}. Do not use force mode")
    updated=transform(original)
    inc=local.read_bytes()
    if inc.count(TAG.encode()) < 1: raise ValueError("Module signature missing")
    parents, counts=parent_manifests(root,before,sha(updated))
    changes={SOURCE:(original,updated), MODULE:(None,inc), **parents}
    if report:
        print(f"{SOURCE}: {len(original)} -> {len(updated)} SHA={before} -> {sha(updated)}")
        print(f"{MODULE}: NEW {len(inc)} bytes SHA={sha(inc)}")
        for rel,(pre,post) in parents.items():
            print(f"  {rel}: SHA {sha(pre)[:12]} -> {sha(post)[:12]} ({counts[rel]} active SHA field(s))")
        print(f"PROBE PASS: no files changed; {len(parents)} parent metadata files to update")
    return changes


def probe(root: Path = ROOT):prepare(root)


def _load_state(root):
    p=root/STATE_NAME/'manifest.json'
    if not p.is_file():raise ValueError(f"Missing installer state {p}")
    state=json.loads(p.read_bytes())
    if state.get('tag') != TAG or not state.get('files'):
        raise ValueError('Installer state invalid')
    return state


def apply(root:Path=ROOT,strict=True):
    changes=prepare(root,strict=strict)
    folder=root/STATE_NAME
    folder.mkdir()
    state={'tag':TAG,'source':SOURCE,'files':[]}
    try:
        for i,(rel,(before,after)) in enumerate(changes.items()):
            bk=f'backup_{i:03d}.bin' if before is not None else None
            if bk: atomic_bytes(folder/bk,before)
            state['files'].append({'path':rel,'backup':bk,
                       'original':sha(before) if before is not None else None,
                       'installed':sha(after)})
        atomic_bytes(folder/'manifest.json',(json.dumps(state,indent=2)+'\n').encode())
        for rel,(_,after) in changes.items():atomic_bytes(root/rel,after)
        verify(root)
    except Exception:
        try:
            for rel,(before,after) in changes.items():
                if before is None:(root/rel).unlink(missing_ok=True)
                else:atomic_bytes(root/rel,before)
            shutil.rmtree(folder)
        except Exception:print('State retained for recover',file=sys.stderr)
        raise
    print('APPLIED: DOS622-only VGA 8x16 font geometry + text strings; DOS2 and 386 core untouched')


def verify(root:Path=ROOT):
    state=_load_state(root)
    for ent in state['files']:
        dest=root/ent['path']
        if not dest.is_file() or sha(dest.read_bytes()) != ent['installed']:
            raise ValueError(f"Installed checksum mismatch: {dest}")
        if ent['backup']:
            b=root/STATE_NAME/ent['backup']
            if not b.is_file() or sha(b.read_bytes()) != ent['original']:
                raise ValueError(f"Backup mismatch: {b}")
        elif ent['original'] is not None:
            raise ValueError('Inconsistent new file record')
    if (root/SOURCE).read_bytes().count(TAG.encode()) != 1:
        raise ValueError('Missing source signature')
    print(f"VERIFY PASS: source + module + {len(state['files'])-2} parent metadata; backups intact")


def restore(root:Path=ROOT,recover=False):
    state=_load_state(root)
    if not recover:verify(root)
    for ent in state['files']:
        dst=root/ent['path']
        if ent['backup']:
            bk=root/STATE_NAME/ent['backup']
            if not bk.is_file() or sha(bk.read_bytes()) != ent['original']:
                raise ValueError(f"Corrupted backup: {bk}")
        if recover and dst.exists() and sha(dst.read_bytes()) not in (ent['original'],ent['installed']):
            raise ValueError(f"Recover refused: unrelated change to {dst}")
    for ent in state['files']:
        dst=root/ent['path']
        if ent['backup']:atomic_bytes(dst,(root/STATE_NAME/ent['backup']).read_bytes())
        else:dst.unlink(missing_ok=True)
    shutil.rmtree(root/STATE_NAME)
    print('RESTORE PASS: exact pre-install files and metadata restored')

SAMPLE=r'''/* BB_DOS622_KEYBA2_V3 */
/* BB_DOS622_P61_REFRESH_V1 */
/* BB_DOS622_VGA12_34_V1 */
/* BB_DOS622_VGA12_30_V1 */
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
static bool active=true;
static bool bb_sd_dos622_active(void){return active;}
static uint8_t store[0x110000];
static uint8_t *mem=store;
static uint8_t mode=3;
static uint16_t cursor[8],cursor_shape;
static uint8_t mread(uint16_t seg,uint16_t off){return mem[(((unsigned)seg<<4)+off)&0xFFFFF];}
static void video_bda(void){mem[0x450]=(uint8_t)cursor[0];mem[0x451]=(uint8_t)(cursor[0]>>8);}
static void scroll_text(unsigned t,unsigned l,unsigned b,unsigned r,unsigned n,uint8_t fill,int down){(void)t;(void)l;(void)b;(void)r;(void)n;(void)fill;(void)down;}
static int bb622_vga12_34(uint16_t *ax,uint16_t bx){(void)ax;(void)bx;return 0;}
static int bb622_vga12_30(uint16_t *ax,uint16_t bx){(void)ax;(void)bx;return 0;}
static int bb_vga_int10(uint16_t *ax,uint16_t *bx,uint16_t *cx,uint16_t *dx,uint16_t *es,uint16_t *bp,uint16_t *fl){(void)ax;(void)bx;(void)cx;(void)dx;(void)es;(void)bp;(void)fl;return 0;}
static unsigned bb_v61_events;
static int hook_int(uint16_t *real_ax, uint16_t real_bx, uint16_t real_cx, uint16_t real_dx, uint16_t real_es,uint16_t real_bp) {
    uint16_t ax=*real_ax,bx=real_bx,cx=real_cx,dx=real_dx,es=real_es,bp=real_bp,f=0x0202;
    if (bb622_vga12_34(&ax,bx) || bb622_vga12_30(&ax,bx) || bb_vga_int10(&ax,&bx,&cx,&dx,&es,&bp,&f)) {
        *real_ax=ax; return 1;
    }
    return 0;
}
static bool bb_v15_interrupt(uint16_t *real_ax, uint16_t real_bx, uint16_t real_cx, uint16_t real_dx,uint16_t real_es,uint16_t real_bp) {
    uint16_t ax=*real_ax,bx=real_bx,cx=real_cx,dx=real_dx,es=real_es,bp=real_bp,flags=0x0202;
    if (bb622_vga12_34(&ax,bx) || bb622_vga12_30(&ax,bx) || bb_vga_int10(&ax,&bx,&cx,&dx,&es,&bp,&flags)) {
        *real_ax=ax; return true;
    }
    return false;
}
'''

def testtree(root:Path,kind:str):
    raw=SAMPLE.replace('\n','\r\n') if kind == 'CRLF' else SAMPLE
    if kind=='MIXED':raw='// mixed\r\n'+raw
    data=raw.encode()
    src=root/SOURCE; src.parent.mkdir(parents=True,exist_ok=True);src.write_bytes(data)
    digest=sha(data)
    pre=root/PREREQ;pre.parent.mkdir(parents=True,exist_ok=True)
    prev={'tag':'BB_DOS622_VGA12_30_V1','source':SOURCE,
      'files':[{'path':SOURCE,'original':'b'*64,'installed':digest}]}
    pre.write_text(json.dumps(prev,indent=2))
    ipl=root/'.bb_dos622_ipl_v1_state/manifest.json';ipl.parent.mkdir(parents=True,exist_ok=True)
    ipl.write_text(json.dumps({'files':{SOURCE:{'old':'1'*64,'installed':digest}}}))
    diag=root/'.bb_dos622_boot_diag_v1_state/repair.json';diag.parent.mkdir(parents=True,exist_ok=True)
    diag.write_text(json.dumps({'files':{SOURCE:{'old':'2'*64,'new':digest}},'parent_after':sha(ipl.read_bytes())}))
    heap=root/'.bb_dos622_heap_rescue_v1_state/manifest.json';heap.parent.mkdir(parents=True,exist_ok=True)
    heap.write_text(json.dumps({'files':{SOURCE:{'old':'4'*64,'new':digest}},'parent_after':sha(ipl.read_bytes())}))
    vga34=root/'.bb_dos622_vga12_34_v1_state/manifest.json';vga34.parent.mkdir(parents=True,exist_ok=True)
    vga34.write_text(json.dumps({'files':[{'path':SOURCE,'original':'5'*64,'installed':digest}]}))
    keyb=root/'.bb_dos622_keyb92_v1_state/manifest.json';keyb.parent.mkdir(parents=True,exist_ok=True)
    keyb.write_text(json.dumps({'files':{SOURCE:{'old':'3'*64,'after':digest},'parent':{'installed':sha(diag.read_bytes())}}}))
    snapshots={p:p.read_bytes() for p in (src,pre,ipl,diag,heap,vga34,keyb)}
    return snapshots

def selftest():
    for kind in ('LF','CRLF','MIXED'):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);snap=testtree(root,kind)
            src=(root/SOURCE).read_bytes();new=transform(src)
            assert new.count(TAG.encode())==1
            prepare(root,strict=True,report=False)
            apply(root);verify(root)
            assert (root/MODULE).read_bytes()==(Path(__file__).resolve().parent/MODULE_LOCAL).read_bytes()
            assert sha((root/SOURCE).read_bytes())==sha(new)
            restore(root)
            for p,old in snap.items():assert p.read_bytes()==old, f'Nonidentical restored file {p}'
            assert not (root/MODULE).exists()
        print('SELFTEST',kind,'PASS parent SHA cascade, exact restore')
    for broken in (SAMPLE.replace('static unsigned bb_v61_events;',''),SAMPLE.replace('static int hook_int','static int broken_int'),SAMPLE.replace('bb_vga_int10(&ax,&bx,&cx,&dx,&es,&bp,&flags)','other_int(&ax)')):
        try:transform(broken.encode())
        except ValueError:pass
        else:raise AssertionError('Unsafe anchor was accepted')
    print('SELFTEST anchor guards PASS')
    cc=shutil.which('cc') or shutil.which('clang') or shutil.which('gcc')
    if cc:
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            fname=root/'test.c';exe=root/'test'
            code=transform(SAMPLE.encode()).decode()+r'''
#include <assert.h>
int main(void){
    uint16_t ax,bx,cx,dx,es,bp,f=0x0202;
    ax=0x1114;bx=0;cx=8;dx=0;es=0;bp=0;
    assert(hook_int(&ax,bx,cx,dx,es,bp)==1 && ax==0x1114);
    assert(mem[0x485]==16 && mem[0x484]==24 && cursor_shape==0x0607);
    ax=0x1114;assert(bb_v15_interrupt(&ax,bx,cx,dx,es,bp)==true);
    ax=0x1104;assert(hook_int(&ax,bx,cx,dx,es,bp)==1);
    ax=0x1114;assert(hook_int(&ax,1,cx,dx,es,bp)==0);
    ax=0x1130;assert(hook_int(&ax,0,cx,dx,es,bp)==0);
    mem[0x500]='H';mem[0x501]='i';
    ax=0x1301;cursor[0]=0;
    assert(hook_int(&ax,0x001E,2,0,0x0050,0)==1);
    assert(mem[0xB8000]=='H' && mem[0xB8001]==0x1E && mem[0xB8002]=='i' && cursor[0]==2);
    ax=0x1300;cursor[0]=7;assert(hook_int(&ax,0x001E,2,0,0x0050,0)==1 && cursor[0]==7);
    active=false;ax=0x1114;assert(hook_int(&ax,0,8,0,0,0)==0);
    active=true; mode=0x13;ax=0x1114;assert(hook_int(&ax,0,8,0,0,0)==0);
    return 0;
}
'''
            fname.write_text(code)
            r=subprocess.run([cc,'-std=c11','-Wall','-Wextra','-DPICO_ON_DEVICE=1','-I',str(Path(__file__).resolve().parent),str(fname),'-o',str(exe)],cwd=Path(__file__).resolve().parent,capture_output=True,text=True)
            if r.returncode:raise AssertionError('C compile failed: '+r.stderr)
            r=subprocess.run([str(exe)],capture_output=True,text=True)
            if r.returncode:raise AssertionError('C contract failure: '+r.stdout+r.stderr)
        print('SELFTEST C11 BIOS 1114/1104/1130 rejection/13h/DOS2 gate PASS')
    print('SELFTEST PASS: BIOS Phase 1')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('selftest','probe','apply','verify','restore','recover'))
    a=p.parse_args()
    try:
        {'selftest':selftest,'probe':probe,'apply':apply,'verify':verify,'restore':restore,
         'recover':lambda:restore(recover=True)}[a.action]()
    except (OSError,ValueError,AssertionError,json.JSONDecodeError) as ex:
        print('ERROR:',ex,file=sys.stderr);sys.exit(1)
if __name__=='__main__':main()
