#!/usr/bin/env python3
"""Reversible blitz86 experiment: eagerly unlink incoming patches on block invalidation.

Save in C:\\blitzBUS. No git patches and no changes to PSRAM layout.

  python bb_deadstub_unchain_ab.py apply
  python bb_deadstub_unchain_ab.py verify
  python bb_deadstub_unchain_ab.py set off
  python bb_deadstub_unchain_ab.py set on
  python bb_deadstub_unchain_ab.py restore

'apply' installs an OFF control first. 'set' changes only a compile-time
constant; rebuild firmware after each change. This is a correctness and
performance experiment; it has not been validated on target hardware.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parent
SOURCE=Path(r'C:\blitz86_v2\src\jit.c') if sys.platform=='win32' else ROOT/'_fixture_blitz86_v2'/'src'/'jit.c'
BACKUP=SOURCE.with_name('jit.c.bb-deadstub-ab-original.bak')
MANIFEST=ROOT/'bb_deadstub_unchain_manifest.json'
MARKER='BB_DEADSTUB_UNCHAIN_AB_V1'


def sha(x:bytes)->str: return hashlib.sha256(x).hexdigest()


def must_one(s:str,needle:str,label:str)->None:
    n=s.count(needle)
    if n!=1: raise RuntimeError(f'{label}: expected one anchor, found {n}; no files changed')


def build(original:str)->str:
    if MARKER in original: raise RuntimeError('Already installed')
    nl='\r\n' if '\r\n' in original else '\n'
    def n(s): return s.replace('\n',nl)
    s=original
    anchor='#define PLOGN 4096u'
    must_one(s,anchor,'macro location')
    s=s.replace(anchor,n('''/* BB_DEADSTUB_UNCHAIN_AB_V1: default OFF; toggle with the test script. */
#define B86_DEADSTUB_EAGER_UNCHAIN 0
''')+anchor,1)
    anchor='    uint32_t nfree;'
    must_one(s,anchor,'J struct field')
    s=s.replace(anchor,anchor+n('''
#if B86_DEADSTUB_EAGER_UNCHAIN
    uint8_t bb_deadstub_eviction_active;
#endif'''),1)
    anchor='B86_HOT static void kill_block(J *j, uint32_t idx)'
    must_one(s,anchor,'kill_block function')
    s=s.replace(anchor,n('''#if B86_DEADSTUB_EAGER_UNCHAIN
static void bb_deadstub_unlink(J *j, uint8_t *target);
#endif
''')+anchor,1)
    anchor='    be_kill_entry(b->host, b->dead_stub);'
    must_one(s,anchor,'kill entry')
    s=s.replace(anchor,n('''#if B86_DEADSTUB_EAGER_UNCHAIN
    /* Non-eviction invalidations previously left incoming patches pointing
       to the dead entry until eventual region reclamation. */
    if (!j->bb_deadstub_eviction_active) bb_deadstub_unlink(j, b->host);
#endif
''')+anchor,1)
    anchor='    j->st.evictions++;'
    must_one(s,anchor,'evict_range start')
    s=s.replace(anchor,n('''#if B86_DEADSTUB_EAGER_UNCHAIN
    j->bb_deadstub_eviction_active = 1; /* evict_range handles its own patch log */
#endif
''')+anchor,1)
    anchor='    j->flush_gen++;          /* pending chain / RET patch sites may be gone */'
    must_one(s,anchor,'evict_range end')
    s=s.replace(anchor,n('''#if B86_DEADSTUB_EAGER_UNCHAIN
    j->bb_deadstub_eviction_active = 0;
#endif
''')+anchor,1)
    # Put helper AFTER PatchLog and PL_* have been defined, before pg_unlink.
    anchor='B86_HOT static void pg_unlink(J *j, uint32_t idx)'
    must_one(s,anchor,'patch-log helper placement')
    helper='''#if B86_DEADSTUB_EAGER_UNCHAIN
/* Remove logged incoming patches to a killed-but-not-yet-reclaimed block.
   Preserve the same restoration rules as the established evict_range path. */
B86_HOT static void bb_deadstub_unlink(J *j, uint8_t *target)
{
    uint32_t w = 0;
    for (uint32_t k = 0; k < j->nplog; ++k) {
        PatchLog *l = &j->plog[k];
        if (l->target != target) {
            j->plog[w++] = *l;
            continue;
        }
        if (l->kind == PL_CHAIN) be_unchain(&j->e, l->site);
        else if (l->kind == PL_RET) be_patch_branch(be_ret_hit_branch(l->site), l->aux);
        else be_patch_branch(l->site, l->aux); /* PL_RECB */
        j->st.unchains++;
    }
    j->nplog = w;
}
#endif

'''
    s=s.replace(anchor,n(helper)+anchor,1)
    assert s!=original and MARKER in s
    return s


def load():
    if not SOURCE.is_file(): raise RuntimeError(f'Local JIT not found: {SOURCE}')
    return SOURCE.read_bytes()


def manifest():
    if not MANIFEST.exists(): raise RuntimeError('No manifest. Run apply first.')
    j=json.loads(MANIFEST.read_text(encoding='utf-8'))
    if Path(j['source'])!=SOURCE: raise RuntimeError('Manifest source mismatch')
    return j


def apply():
    if BACKUP.exists() or MANIFEST.exists(): raise RuntimeError('Backup/manifest already exists; refusing overwrite')
    orig=load()
    transformed=build(orig.decode('utf-8')).encode('utf-8')
    BACKUP.write_bytes(orig)
    try:
        SOURCE.write_bytes(transformed)
        MANIFEST.write_text(json.dumps(dict(source=str(SOURCE),original_sha256=sha(orig),
            edited_sha256=sha(transformed),backup=str(BACKUP),marker=MARKER),indent=2),encoding='utf-8')
    except Exception:
        SOURCE.write_bytes(orig)
        BACKUP.unlink(missing_ok=True)
        raise
    print('Installed with eager unlink OFF. Existing JIT instrumentation retained.')
    verify()


def verify():
    j=manifest()
    if not BACKUP.is_file(): raise RuntimeError('Backup is missing')
    if sha(BACKUP.read_bytes())!=j['original_sha256']: raise RuntimeError('Backup checksum mismatch')
    current=load().decode('utf-8')
    if MARKER not in current: raise RuntimeError('Marker missing from source')
    m=re.findall(r'^#define B86_DEADSTUB_EAGER_UNCHAIN ([01])$',current,re.M)
    if len(m)!=1: raise RuntimeError('Toggle marker missing or duplicated')
    if current.count('bb_deadstub_unlink(j, b->host)')!=1: raise RuntimeError('Invalidation callsite missing')
    if current.count('bb_deadstub_eviction_active = 1')!=1: raise RuntimeError('Eviction guard missing')
    print(f'VERIFIED: eager unlink {"ON" if m[0]=="1" else "OFF"}; original backup intact')


def set_mode(mode):
    verify()
    cur=load().decode('utf-8')
    a='1' if mode=='on' else '0'
    updated=re.sub(r'(?m)^#define B86_DEADSTUB_EAGER_UNCHAIN [01]$',
                   '#define B86_DEADSTUB_EAGER_UNCHAIN '+a,cur)
    if updated==cur: print('Already '+mode.upper());return
    SOURCE.write_bytes(updated.encode('utf-8'))
    print('Set eager unlink',mode.upper(),'- now rebuild and flash the firmware.')
    verify()


def restore():
    j=manifest()
    verify()
    # Restore only if current file differs from an expected OFF/ON variant solely
    # in the compile-time define. Do not clobber independent local edits.
    original=BACKUP.read_bytes()
    off=build(original.decode('utf-8'))
    on=off.replace('#define B86_DEADSTUB_EAGER_UNCHAIN 0',
                   '#define B86_DEADSTUB_EAGER_UNCHAIN 1')
    cur=load()
    if cur not in (off.encode('utf-8'),on.encode('utf-8')):
        raise RuntimeError('JIT changed independently since apply. No restore performed.')
    SOURCE.write_bytes(original)
    MANIFEST.unlink()
    BACKUP.unlink()
    print('Restored exact pre-experiment jit.c. Rebuild for original firmware behavior.')


def main():
    p=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    sp=p.add_subparsers(dest='action',required=True)
    for x in ('apply','verify','restore'): sp.add_parser(x)
    s=sp.add_parser('set');s.add_argument('mode',choices=['on','off'])
    a=p.parse_args()
    try:
        if a.action=='apply':apply()
        elif a.action=='verify':verify()
        elif a.action=='set':set_mode(a.mode)
        else:restore()
    except Exception as e:
        print('ERROR:',e,file=sys.stderr);sys.exit(1)

if __name__=='__main__':main()
