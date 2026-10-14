#!/usr/bin/env python3
"""BLITZBUS DOS622 PIC pending-only experiment, optional Ctrl+Y runtime toggle.

Commands: selftest, probe, apply, verify, restore. No Git patches.
REQUIRES already-installed 13th BB622_DESCENT_SWAP_V1 layer.
No disk images or host scripts are modified. Do not toggle on from DOS normal use.
"""
from __future__ import annotations
import argparse, hashlib, json, os, shutil, sys, tempfile
from pathlib import Path
import bb622_descent_swap_v1 as prior

ROOT=Path(__file__).resolve().parent
TAG='BB622_PIC_PENDING_V1'
STATE='.bb622_pic_pending_v1_state'
DESC_STATE='.bb622_descent_swap_v1_state'
LIVE='src/bb_live.c'
IRQ='src/bb_irq.h'
SHA=lambda b:hashlib.sha256(b).hexdigest()

STATES_AFTER_DESC=[
 '.bb622_pic_pending_v1_state',
 '.bb622_descent_swap_v2_state',
 '.bb622_irq0_probe_v1_state',
]

PIC_STATE='''/* BB622_PIC_PENDING_V1: development-only IRQ0 IRR experiment.
 * Ctrl+Y turns pending-edge visibility on/off. Guest IRQ0 delivery remains
 * disabled; no guest stack is touched by this experiment.
 */
static uint8_t bb622_pic_pending_probe_enabled;
static uint32_t bb622_pic_pending_reads;
static uint32_t bb622_pic_pending_reports;
static uint8_t bb622_pic_pending_last=0xffu;
'''
PIC_IN='''static int bb_irq36_in(uint16_t port,uint8_t *val){
 if(port==0x20){
  *val=bb_irq36.read_isr?bb_irq36.isr:bb_irq36.irr;
  if(bb622_pic_pending_probe_enabled){
   ++bb622_pic_pending_reads;
   /* Trace initial reads, state transitions and sparse progress; cap USB I/O. */
   if(bb622_pic_pending_reports<48u &&
      (bb622_pic_pending_reads<=16u || *val!=bb622_pic_pending_last ||
       (bb622_pic_pending_reads&65535u)==0u)){
    ++bb622_pic_pending_reports;
    printf("[bb622-picprobe] IN20 #%lu val=%02X mode=%s irr=%02X imr=%02X isr=%02X scheduled=%llu delivered=%llu\\n",
       (unsigned long)bb622_pic_pending_reads,(unsigned)*val,
       bb_irq36.read_isr?"ISR":"IRR",(unsigned)bb_irq36.irr,
       (unsigned)bb_irq36.imr,(unsigned)bb_irq36.isr,
       (unsigned long long)bb_irq36.scheduled,
       (unsigned long long)bb_irq36.delivered);
    fflush(stdout);
   }
   bb622_pic_pending_last=*val;
  }
  return 1;
 }
 if(port==0x21){*val=bb_irq36.imr;return 1;}
 return 0;
}'''

TOGGLE='''    /* BB622_PIC_PENDING_V1: Ctrl+Y is private host control, not guest key.
     * This intentionally does not call bb_irq36_dispatch() or push FLAGS/CS/IP.
     */
    if(bb_sd_dos622_active() && c==0x19){
        bb622_pic_pending_probe_enabled^=1u;
        bb622_pic_pending_reads=0u;
        bb622_pic_pending_reports=0u;
        bb622_pic_pending_last=0xffu;
        if(!bb622_pic_pending_probe_enabled){
            bb_irq36.irr &= (uint8_t)~1u;
        }
        printf("[bb622-picprobe] Ctrl+Y %s pending-only (guest IRQ0 delivery still OFF) irr=%02X imr=%02X isr=%02X\\n",
               bb622_pic_pending_probe_enabled?"ON":"OFF",
               (unsigned)bb_irq36.irr,(unsigned)bb_irq36.imr,(unsigned)bb_irq36.isr);
        fflush(stdout);
        return;
    }
'''

SCHEDULE='''#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE && BB622_IRQ0_AB_DISABLE
        if (bb_sd_dos622_active()) {
            /* BB622_PIC_PENDING_V1: produce 8259 IRR edges at PIT ch0 rate
             * only when explicitly enabled with Ctrl+Y. No stack injection.
             */
            if(bb622_pic_pending_probe_enabled)bb_irq36_schedule(bb_now_us());
        } else bb_irq36_dispatch(rt, bb_now_us());
#else'''


def irq_patch(raw:bytes)->bytes:
    s,e,b=prior.prev.parse(raw)
    if TAG in s: raise ValueError('IRQ file already patched')
    s=prior.prev.one(s,'static BbIrq36 bb_irq36;',
        'static BbIrq36 bb_irq36;\n'+PIC_STATE.rstrip('\n'),'PIC state')
    old='''static int bb_irq36_in(uint16_t port,uint8_t *val){
 if(port==0x20){*val=bb_irq36.read_isr?bb_irq36.isr:bb_irq36.irr;return 1;}
 if(port==0x21){*val=bb_irq36.imr;return 1;}
 return 0;
}'''
    s=prior.prev.one(s,old,PIC_IN,'PIC port reader')
    return prior.prev.pack(s,e,b)


def live_patch(raw:bytes)->bytes:
    s,e,b=prior.prev.parse(raw)
    if TAG in s: raise ValueError('LIVE already patched')
    if 'BB_DOS622_BOOT_EJECT_V1' not in s:
        raise ValueError('Required C boot/eject source marker missing')
    anchor='''    /* v33: once video owns the console, this poll is the only reader of the
       serial port, so Ctrl+] (0x1D) is handled here instead of reaching the
       guest keyboard queue. */'''
    s=prior.prev.one(s,anchor,TOGGLE.rstrip('\n')+anchor,'Ctrl+Y intercept')
    old='''#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE && BB622_IRQ0_AB_DISABLE
        if (!bb_sd_dos622_active()) bb_irq36_dispatch(rt, bb_now_us());
#else'''
    s=prior.prev.one(s,old,SCHEDULE,'PIT schedule under IRQ0 suppression')
    s=prior.prev.one(s,'    bb_irq36_init(bb_now_us());',
        '    bb_irq36_init(bb_now_us());\n    bb622_pic_pending_probe_enabled=0u; /* BB622_PIC_PENDING_V1: OFF on cold boot */',
        'Cold boot always begins with PIC probe OFF')
    return prior.prev.pack(s,e,b)


def atomic(path:Path,data:bytes):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.bb622-pic-new')
    try:tmp.write_bytes(data);os.replace(tmp,path)
    finally:tmp.unlink(missing_ok=True)


def descent_manifest_update(raw:bytes,updates:dict)->bytes:
    """Update only verified *current* hashes in 13th layer's file records.

    Uses path identities, not free-text SHA replacement, to avoid modifying
    original/backups and to detect non-corresponding state unambiguously.
    """
    parsed=json.loads(raw)
    if parsed.get('tag')!='BB622_DESCENT_SWAP_V1' or not isinstance(parsed.get('files'),list):
        raise ValueError('Unexpected Descent manifest schema')
    # Existing manifests use indentation 2; rewrite only where a tracked file
    # changed, so older checksum histories remain byte-exact in backups.
    touched=0
    for row in parsed['files']:
        rel=row['path']
        if rel in updates:
            old,new=updates[rel]
            if old is None or row['installed']!=SHA(old):
                raise ValueError(f'Descent checksum-chain precondition mismatch: {rel}')
            row['installed']=SHA(new);touched+=1
    # A previous-stage manifest must track its own modified metadata files;
    # confirm all paths from its manifest affected by upstream adjustments.
    expected=sum(1 for path in updates if any(x['path']==path for x in parsed['files']))
    assert touched==expected
    if not touched:return raw
    ending=b'\r\n' if b'\r\n' in raw else b'\n'
    out=(json.dumps(parsed,indent=2,ensure_ascii=False)+'\n').encode()
    return out.replace(b'\n',ending)


def prepare(root:Path=ROOT,verbose=True,fixture=False):
    if (root/STATE).exists():raise ValueError('Already installed: run verify/restore')
    desc=root/DESC_STATE/'manifest.json'
    if not desc.is_file():raise ValueError('Required 13th Descent swap state absent; apply Descent swap layer first')
    if json.loads(desc.read_bytes()).get('tag')!='BB622_DESCENT_SWAP_V1':
        raise ValueError('Unexpected predecessor tag')
    old_live=(root/LIVE).read_bytes();old_irq=(root/IRQ).read_bytes()
    updates={LIVE:(old_live,live_patch(old_live)),IRQ:(old_irq,irq_patch(old_irq))}
    if not fixture:
        # Treat the upstream SHA dependency graph as a strict precondition;
        # this includes old clockfix repair.json etc. and rewrites only supported
        # active-after digests, never historical-before digests.
        parents=prior.prev.parent.cascade(root,updates)
        if set(parents)&set(updates):raise ValueError('Overlapping upstream metadata and source')
        updates.update(parents)
    manifest_raw=desc.read_bytes()
    new_manifest=descent_manifest_update(manifest_raw,updates)
    if new_manifest!=manifest_raw:
        updates[f'{DESC_STATE}/manifest.json']=(manifest_raw,new_manifest)
    if verbose:print(f'PROBE PASS: 2 firmware files, {len(updates)-2} verified checksum metadata files; no HDD/SD/host changes')
    return updates


def verify(root:Path=ROOT):
    path=root/STATE/'manifest.json'
    if not path.is_file():raise ValueError('Missing experiment state')
    obj=json.loads(path.read_bytes())
    if obj.get('tag')!=TAG or not isinstance(obj.get('files'),list):raise ValueError('Invalid experiment manifest')
    for row in obj['files']:
        rel=row['path'];p=root/rel
        if not p.is_file() or SHA(p.read_bytes())!=row['installed']:
            raise ValueError('Installed source or metadata checksum mismatch: '+rel)
        if row['original'] is not None:
            bp=root/STATE/row['backup']
            if SHA(bp.read_bytes())!=row['original']:
                raise ValueError('Byte-exact backup mismatch: '+rel)
    print(f'VERIFY PASS: {len(obj["files"])} current source+metadata entries and backups')


def apply(root:Path=ROOT,fixture=False):
    changes=prepare(root,fixture=fixture)
    state=root/STATE;state.mkdir();written=[];rows=[]
    try:
        for i,(rel,(before,after)) in enumerate(changes.items()):
            bk=f'backup_{i:03d}.bin' if before is not None else None
            if bk:atomic(state/bk,before)
            rows.append({'path':rel,'backup':bk,'original':SHA(before) if before is not None else None,'installed':SHA(after)})
        atomic(state/'manifest.json',(json.dumps({'tag':TAG,'files':rows},indent=2)+'\n').encode())
        for rel,(old,new) in changes.items():atomic(root/rel,new);written.append(rel)
        verify(root)
    except BaseException:
        for rel in reversed(written):
            old=changes[rel][0]
            if old is None:(root/rel).unlink(missing_ok=True)
            else:atomic(root/rel,old)
        shutil.rmtree(state,ignore_errors=True)
        raise
    print('APPLIED: opt-in Ctrl+Y PIC pending-only probe. No disk images touched.')


def restore(root:Path=ROOT):
    verify(root)
    rows=json.loads((root/STATE/'manifest.json').read_bytes())['files']
    for row in reversed(rows):
        rel=row['path']; old=(root/STATE/row['backup']).read_bytes() if row['original'] else None
        if old is None:(root/rel).unlink()
        else:atomic(root/rel,old)
    shutil.rmtree(root/STATE)
    print('RESTORE PASS: previous source and SHA metadata restored byte-exactly')


def selftest():
    srcirq='''#ifndef BB_V36_IRQ_H
#define BB_V36_IRQ_H
static BbIrq36 bb_irq36;
static int bb_irq36_in(uint16_t port,uint8_t *val){
 if(port==0x20){*val=bb_irq36.read_isr?bb_irq36.isr:bb_irq36.irr;return 1;}
 if(port==0x21){*val=bb_irq36.imr;return 1;}
 return 0;
}
#endif
'''
    srclive='''/* BB_DOS622_BOOT_EJECT_V1 */
    bb_irq36_init(bb_now_us());
    /* v33: once video owns the console, this poll is the only reader of the
       serial port, so Ctrl+] (0x1D) is handled here instead of reaching the
       guest keyboard queue. */
#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE && BB622_IRQ0_AB_DISABLE
        if (!bb_sd_dos622_active()) bb_irq36_dispatch(rt, bb_now_us());
#else
'''
    for ending in ('\n','\r\n'):
        for dat,fn in [(srcirq.encode(),irq_patch),(srclive.encode(),live_patch)]:
            raw=dat.replace(b'\n',ending.encode());out=fn(raw)
            text2,nl,bom=prior.prev.parse(out)
            assert nl==ending and TAG in text2
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            for rel,data in [(IRQ,srcirq),(LIVE,srclive)]:
                dst=root/rel;dst.parent.mkdir(parents=True,exist_ok=True)
                dst.write_bytes(data.replace('\n',ending).encode())
            desc=root/DESC_STATE;desc.mkdir()
            (desc/'manifest.json').write_bytes((json.dumps({'tag':'BB622_DESCENT_SWAP_V1','files':[
                {'path':LIVE,'installed':SHA((root/LIVE).read_bytes()),'original':'abc','backup':'a'},
                {'path':'other.file','installed':'f'*64,'original':'1'*64,'backup':'b'}
                ]},indent=2)+'\n').encode())
            baseline={rel:(root/rel).read_bytes() for rel in [IRQ,LIVE,f'{DESC_STATE}/manifest.json']}
            changed=prepare(root,False,True)
            assert len(changed)==3 and f'{DESC_STATE}/manifest.json' in changed
            apply(root,True);verify(root);restore(root)
            for rel,raw in baseline.items():assert (root/rel).read_bytes()==raw
            assert not (root/STATE).exists()
    print('SELFTEST PASS: LF/CRLF, Ctrl+Y toggle, transactional checksum-chain, byte-exact rollback')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action',choices=['selftest','probe','apply','verify','restore'])
    args=ap.parse_args()
    try: {'selftest':selftest,'probe':prepare,'apply':apply,'verify':verify,'restore':restore}[args.action]()
    except (ValueError,KeyError,OSError,AssertionError) as e:
        print('ERROR:',e,file=sys.stderr);sys.exit(1)

if __name__=='__main__':main()
