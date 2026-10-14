#!/usr/bin/env python3
"""blitzBUS DOS 6.22: VGA INT 10h AH=12h BL=34h cursor-emulation probe.

Fixes the safe-stop observed after the port-61 refresh patch.
DOS6-only BIOS compatibility; no keyboard, JIT, SD, DOS2, or IRQ0 changes.
Exact-source guard: post-P61 live hardware output 92909 bytes / SHA 2b37...
Reversible installer with complete SHA manifest dependency propagation.
Usage: selftest | probe | apply | verify | restore | recover
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
TAG = "BB_DOS622_VGA12_34_V1"
STATE_NAME = ".bb_dos622_vga12_34_v1_state"
EXPECTED_SIZE = 92909
EXPECTED_SHA_PREFIX = "2b37d15bf75e0af512d7ba716c73512df37039ca4ce897bcbeeacaf94a972cf6"
KEYB92_STATE = ".bb_dos622_keyb92_v1_state"

def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_bytes(path: Path, data: bytes):
    """Atomic replace in same directory; preserve content exactly."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, fn = tempfile.mkstemp(prefix=".bbkeyba2-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(fn, path)
    finally:
        try:
            os.unlink(fn)
        except FileNotFoundError:
            pass


def transform(raw: bytes) -> bytes:
    """Add DOS6-only VGA cursor-emulation BIOS service to both INT10 paths.

    Gate before the shared VGA function so both native and interpreter can
    return through their existing AX/flags/segment synchronization logic.
    Does not pretend other AH12/BLxx services exist.
    """
    if TAG.encode() in raw:
        raise ValueError("VGA12/34 fix already present; run verify")
    if b"BB_DOS622_P61_REFRESH_V1" not in raw or b"BB_DOS622_KEYBA2_V3" not in raw:
        raise ValueError("Expected active port61 and keyba2 patches; refusing unknown tree")
    if b'static unsigned bb_v61_events;' not in raw:
        raise ValueError("Missing unique native INT dispatcher anchor")
    if raw.count(b'static unsigned bb_v61_events;') != 1:
        raise ValueError("Ambiguous native INT dispatcher anchor")
    native = b'if (bb_vga_int10(&ax,&bx,&cx,&dx,&es,&bp,&f)) {'
    interp = b'if (bb_vga_int10(&ax,&bx,&cx,&dx,&es,&bp,&flags)) {'
    if raw.count(native) != 1 or raw.count(interp) != 1:
        raise ValueError(f"INT10 hook signatures not unique: native={raw.count(native)} interpreter={raw.count(interp)}")
    # Ensure the two call sites belong to their respective dispatch routines.
    start_native = raw.find(b'static int hook_int(')
    if start_native < 0: start_native=raw.find(b'static int hook_int (')
    start_interp = raw.find(b'static bool bb_v15_interrupt(')
    if start_native < 0 or start_interp < 0 or start_native >= start_interp:
        raise ValueError("Cannot establish native->interpreter INT10 dispatcher order")
    if not (start_native < raw.find(native) < start_interp < raw.find(interp)):
        raise ValueError("INT10 hook call sites not in expected dispatchers")
    nl = b'\r\n' if b'\r\n' in raw else b'\n'
    # The same helper is used for both tiers. Prefix it near the native
    # dispatcher (not inside an interrupt callback).
    helper = """/* BB_DOS622_VGA12_34_V1: DOS 6.22 VGA cursor emulation compatibility.
   INT 10h AH=12h BL=34h AL=0/1 => return AL=12h on VGA support.
   Existing VGA cursor shape handling remains in bb_vga_int10. */
#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE
extern bool bb_sd_dos622_active(void);
static int bb622_vga12_34(uint16_t *ax, uint16_t bx)
{
    if (!bb_sd_dos622_active()) return 0;
    if ((*ax >> 8) != 0x12u || (bx & 0x00ffu) != 0x34u || (*ax & 0x00ffu) > 1u) return 0;
    static uint8_t cursor_emulation = 1u;
    static unsigned calls;
    cursor_emulation = (uint8_t)((*ax & 0xffu) == 0u);
    *ax = (uint16_t)((*ax & 0xff00u) | 0x12u);
    if (++calls <= 8u) {
        printf("[bb622-vga12] INT10 AH=12 BL=34 cursor_emulation=%u out-ax=%04X\\n",
               (unsigned)cursor_emulation, (unsigned)*ax);
        fflush(stdout);
    }
    return 1;
}
#else
static int bb622_vga12_34(uint16_t *ax, uint16_t bx)
{ (void)ax; (void)bx; return 0; }
#endif

""".encode('ascii').replace(b'\n',nl)
    raw=raw.replace(b'static unsigned bb_v61_events;', helper+b'static unsigned bb_v61_events;', 1)
    # Maintain return-path side effects and flag synchronization unchanged.
    raw=raw.replace(native, b'if (bb622_vga12_34(&ax,bx) || bb_vga_int10(&ax,&bx,&cx,&dx,&es,&bp,&f)) {', 1)
    raw=raw.replace(interp, b'if (bb622_vga12_34(&ax,bx) || bb_vga_int10(&ax,&bx,&cx,&dx,&es,&bp,&flags)) {', 1)
    if raw.count(TAG.encode()) != 1 or raw.count(b'[bb622-vga12]') != 1:
        raise AssertionError('Expected exactly one new VGA12 marker and diagnostic')
    return raw


# Only active installer metadata is rewritten. Immutable historical snapshots,
# such as parent_before.json and *.bak, are NEVER scanned or modified.
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


def prepare(root: Path, strict: bool = True, report: bool = True):
    if (root / STATE_NAME).exists():
        raise ValueError(f"{STATE_NAME} exists: use verify or restore; no changes made")
    target = root / SOURCE
    if not target.is_file():
        raise ValueError(f"Missing {target}")
    original = target.read_bytes()
    pre_sha = sha(original)
    if strict and (len(original) != EXPECTED_SIZE or not pre_sha.startswith(EXPECTED_SHA_PREFIX)):
        raise ValueError(
            f"Local {SOURCE} differs from verified P61 source; "
            f"got bytes={len(original)} SHA256={pre_sha}; expected "
            f"bytes={EXPECTED_SIZE}, SHA256 prefix={EXPECTED_SHA_PREFIX}. "
            "Do not force installation: supply the updated local source and manifests for review.")
    changed = transform(original)
    post_sha = sha(changed)
    parents, counts = parent_manifests(root, pre_sha, post_sha)
    changes = {SOURCE: (original, changed), **parents}
    if report:
        print(f"{SOURCE}: anchor PASS {len(original)} -> {len(changed)} bytes")
        print(f"source old={pre_sha} new={post_sha}")
        for rel, (old_meta, new_meta) in parents.items():
            print(f"  {rel}: {len(old_meta)} -> {len(new_meta)} bytes, "
                  f"SHA {sha(old_meta)[:12]} -> {sha(new_meta)[:12]}, "
                  f"{counts[rel]} tracked SHA value(s)")
        print(f"parent metadata SHA cascade PASS: {len(parents)} updated atomically on apply")
        print("PROBE PASS: no repository files modified")
    return changes


def probe(root: Path = ROOT, strict: bool = True):
    prepare(root, strict)


def _load_state(root: Path):
    path = root / STATE_NAME / "manifest.json"
    if not path.is_file():
        raise ValueError(f"Missing installer state: {path}")
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("tag") != TAG or state.get("source") != SOURCE:
        raise ValueError("Installer state tag/path mismatch")
    if not isinstance(state.get("files"), list) or not state["files"]:
        raise ValueError("Installer state has no files")
    return state


def apply(root: Path = ROOT, strict: bool = True):
    changes = prepare(root, strict)
    state_path = root / STATE_NAME
    state_path.mkdir()  # refuse existing state
    state = {"tag": TAG, "source": SOURCE, "files": []}
    try:
        # Make verified byte-for-byte backups and commit the recovery manifest
        # BEFORE changing any parent/source, so interrupted writes are recoverable.
        for index, (rel, (old, new)) in enumerate(changes.items()):
            backup = f"backup_{index:03d}.bin"
            atomic_bytes(state_path / backup, old)
            state["files"].append({"path": rel, "backup": backup,
                                   "original": sha(old), "installed": sha(new)})
        atomic_bytes(state_path / "manifest.json", (json.dumps(state, indent=2) + "\n").encode("utf-8"))
        # Source + all parents have been validated; replace each atomically.
        for rel, (_, new) in changes.items():
            atomic_bytes(root / rel, new)
        verify(root)
    except Exception:
        # Automatic rollback of any changes that may already have completed.
        # State remains if recovery itself encounters a failure.
        try:
            for rel, (old, _) in changes.items():
                atomic_bytes(root / rel, old)
            shutil.rmtree(state_path)
        except Exception:
            print("Recovery state retained; use 'recover' after investigating errors", file=sys.stderr)
        raise
    print("APPLIED: DOS6-only VGA INT10 12/34 compatibility; parent SHA links updated; DOS2 unchanged")


def verify(root: Path = ROOT):
    state = _load_state(root)
    for item in state["files"]:
        path = root / item["path"]
        backup = root / STATE_NAME / item["backup"]
        if not backup.is_file() or sha(backup.read_bytes()) != item["original"]:
            raise ValueError(f"Missing/corrupt byte-exact backup for {item['path']}")
        if not path.is_file() or sha(path.read_bytes()) != item["installed"]:
            raise ValueError(f"Installed file SHA mismatch for {item['path']}")
    source = (root / SOURCE).read_bytes()
    if source.count(TAG.encode()) != 1:
        raise ValueError("VGA12 source marker missing/duplicated")
    print(f"VERIFY PASS: exact source and {len(state['files'])-1} parent metadata files match; all backups valid")


def restore(root: Path = ROOT, recover: bool = False):
    state = _load_state(root)
    if not recover:
        verify(root)  # strict restore; never erase unrelated user edits
    for item in state["files"]:
        dest = root / item["path"]
        backup = root / STATE_NAME / item["backup"]
        old = backup.read_bytes()
        if sha(old) != item["original"]:
            raise ValueError(f"Backup SHA mismatch: {dest}")
        if recover and dest.exists():
            current = sha(dest.read_bytes())
            if current not in (item["installed"], item["original"]):
                raise ValueError(f"Recover REFUSED: unrelated change to {dest}")
    for item in state["files"]:
        old = (root / STATE_NAME / item["backup"]).read_bytes()
        atomic_bytes(root / item["path"], old)
    shutil.rmtree(root / STATE_NAME)
    print(f"RESTORE PASS: {len(state['files'])} files exactly returned to pre-VGA12 bytes")


SAMPLE = r'''/* BB_DOS622_KEYBA2_V3 prerequisite */
/* BB_DOS622_P61_REFRESH_V1 prerequisite */
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
static int active;
static int vga_calls;
static bool bb_sd_dos622_active(void) { return active != 0; }
static int bb_vga_int10(uint16_t *ax,uint16_t *bx,uint16_t *cx,uint16_t *dx,
                        uint16_t *es,uint16_t *bp,uint16_t *flags)
{ (void)ax; (void)bx; (void)cx; (void)dx; (void)es; (void)bp; (void)flags;
  vga_calls++; return 0; }
static unsigned bb_v61_events;
static int hook_int(uint16_t *real_ax, uint16_t real_bx) {
    uint16_t ax=*real_ax,bx=real_bx,cx=8,dx=1,es=0,bp=0,f=0x0202;
    if (bb_vga_int10(&ax,&bx,&cx,&dx,&es,&bp,&f)) {
        *real_ax=ax;
        return 1;
    }
    return 0;
}
static bool bb_v15_interrupt(uint16_t *real_ax,uint16_t real_bx) {
    uint16_t ax=*real_ax,bx=real_bx,cx=8,dx=1,es=0,bp=0,flags=0x0202;
    if (bb_vga_int10(&ax,&bx,&cx,&dx,&es,&bp,&flags)) {
        *real_ax=ax;
        return true;
    }
    return false;
}
'''

def _synthetic_tree(root: Path, kind: str):
    orig = SAMPLE
    if kind == 'CRLF': orig = orig.replace('\n','\r\n')
    elif kind == 'MIXED': orig = '// mixed\r\n' + orig
    elif kind == 'CRLF_LF': orig = orig + '// last line CRLF\r\n'
    source = root / SOURCE
    source.parent.mkdir(parents=True, exist_ok=True)
    data=orig.encode('ascii')
    source.write_bytes(data)
    prior=sha(data)
    ipl = root / '.bb_dos622_ipl_v1_state/manifest.json'
    diag = root / '.bb_dos622_boot_diag_v1_state/repair.json'
    heap = root / '.bb_dos622_heap_rescue_v1_state/manifest.json'
    keyb92 = root / KEYB92_STATE / 'manifest.json'
    keyba2 = root / '.bb_dos622_keyba2_v3_state/manifest.json'
    p61 = root / '.bb_dos622_p61_refresh_v1_state/manifest.json'
    for p in (ipl,diag,heap,keyb92,keyba2,p61):p.parent.mkdir(parents=True,exist_ok=True)
    def put(p,obj):p.write_bytes((json.dumps(obj,indent=2)+'\n').encode())
    put(ipl,{'tag':'IPL','files':{SOURCE:{'original':'0'*64,'installed':prior}}})
    put(diag,{'tag':'DIAG','files':{SOURCE:{'old':'1'*64,'new':prior}},
              'parent_before':'2'*64,'parent_after':sha(ipl.read_bytes())})
    put(heap,{'tag':'HEAP','files':{SOURCE:{'old':'3'*64,'new':prior}},
              'ref':{'parent_after':sha(ipl.read_bytes())}})
    put(keyb92,{'tag':'KEYB92','files':{SOURCE:{'before':'4'*64,'after':prior},
        '.bb_dos622_ipl_v1_state/manifest.json':{'old':'5'*64,'new':sha(ipl.read_bytes())},
        '.bb_dos622_boot_diag_v1_state/repair.json':{'old':'6'*64,'installed':sha(diag.read_bytes())}}})
    put(keyba2,{'tag':'KEYBA2','source':SOURCE,'files':[
        {'path':SOURCE,'original':'7'*64,'installed':prior},
        {'path':'.bb_dos622_keyb92_v1_state/manifest.json','original':'8'*64,'installed':sha(keyb92.read_bytes())}]})
    put(p61,{'tag':'P61','source':SOURCE,'files':[
        {'path':SOURCE,'original':'9'*64,'installed':prior},
        {'path':'.bb_dos622_keyba2_v3_state/manifest.json','original':'a'*64,'installed':sha(keyba2.read_bytes())}]})
    snapshot={p:p.read_bytes() for p in (source,ipl,diag,heap,keyb92,keyba2,p61)}
    return snapshot


def selftest():
    for kind in ('LF','CRLF','MIXED','CRLF_LF'):
        with tempfile.TemporaryDirectory(prefix='bb622_vga1234_'+kind+'_') as td:
            root=Path(td)
            snaps=_synthetic_tree(root,kind)
            new=transform(snaps[root/SOURCE])
            assert new.count(TAG.encode()) == 1
            prepare(root,strict=False,report=False)
            apply(root,strict=False)
            verify(root)
            p61=json.loads((root/'.bb_dos622_p61_refresh_v1_state/manifest.json').read_bytes())
            assert p61['files'][0]['installed']==sha(new)
            diag=json.loads((root/'.bb_dos622_boot_diag_v1_state/repair.json').read_bytes())
            assert diag['parent_after']==sha((root/'.bb_dos622_ipl_v1_state/manifest.json').read_bytes())
            restore(root)
            for p,old in snaps.items():assert p.read_bytes()==old, f'{p}: restore not byte exact'
            assert not (root/STATE_NAME).exists()
            try:transform(new)
            except ValueError:pass
            else:raise AssertionError('duplicate patch was accepted')
        print('SELFTEST',kind,'PASS SHA cascade, exact rollback')
    # Fail closed when either native or interpreter hook is missing.
    for bad in (SAMPLE.replace('static unsigned bb_v61_events;',''),
                SAMPLE.replace('bb_vga_int10(&ax,&bx,&cx,&dx,&es,&bp,&f)','bogus(&ax)'),
                SAMPLE.replace('bb_vga_int10(&ax,&bx,&cx,&dx,&es,&bp,&flags)','bogus(&ax)'),
                SAMPLE.replace('bb_v15_interrupt','unknown_interrupt')):
        try:transform(bad.encode('ascii'))
        except ValueError:pass
        else:raise AssertionError('invalid VGA hook layout accepted')
    print('SELFTEST hook structure guards PASS')
    cc=shutil.which('cc') or shutil.which('clang') or shutil.which('gcc')
    if cc:
        with tempfile.TemporaryDirectory(prefix='bb622_vga1234_c_') as td:
            fn=Path(td)/'test.c'; exe=Path(td)/('test.exe' if os.name=='nt' else 'test')
            code=transform(SAMPLE.encode('ascii')).decode('ascii')+r'''
#include <assert.h>
int main(void) {
    uint16_t ax;
    active=1;
    ax=0x1200; assert(hook_int(&ax,0x0034)==1 && ax==0x1212);
    ax=0x1201; assert(bb_v15_interrupt(&ax,0x0034)==true && ax==0x1212);
    ax=0x1202; assert(hook_int(&ax,0x0034)==0 && ax==0x1202);
    ax=0x1200; assert(hook_int(&ax,0x0035)==0 && ax==0x1200);
    ax=0x0013; assert(hook_int(&ax,0x0034)==0 && ax==0x0013);
    active=0;
    ax=0x1200; assert(hook_int(&ax,0x0034)==0 && ax==0x1200);
    ax=0x1200; assert(bb_v15_interrupt(&ax,0x0034)==false && ax==0x1200);
    assert(vga_calls==5);
    return 0;
}
'''
            fn.write_text(code)
            result=subprocess.run([cc,'-std=c11','-Wall','-Wextra','-DPICO_ON_DEVICE=1',str(fn),'-o',str(exe)],capture_output=True,text=True)
            if result.returncode:raise AssertionError('C build failed:\n'+result.stderr)
            result=subprocess.run([str(exe)],capture_output=True,text=True)
            if result.returncode:raise AssertionError('C execution failed:\n'+result.stdout+'\n'+result.stderr)
        print('SELFTEST C11 native/interpreter/DOS6/DOS2/return AX contract PASS')
    else:print('SELFTEST C11 SKIP, compiler unavailable')
    print('SELFTEST PASS: VGA12/34, guards, all parent manifests, byte-exact rollback')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('selftest','probe','apply','verify','restore','recover'))
    args=parser.parse_args()
    try:
        {'selftest':selftest,'probe':probe,'apply':apply,'verify':verify,
         'restore':restore,'recover':lambda:restore(recover=True)}[args.action]()
    except (OSError,ValueError,AssertionError,json.JSONDecodeError) as exc:
        print('ERROR:',exc,file=sys.stderr)
        sys.exit(1)

if __name__=='__main__':main()
