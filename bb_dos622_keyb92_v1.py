#!/usr/bin/env python3
"""DOS 6.22 KEYB.COM IBM AT keyboard AH=92h compatibility, reversible full-file installer.

Commands: selftest | probe | apply | verify | restore
Place alongside bb_dos622_irq0_isolation_v1.py and all prior installer scripts,
under C:\\blitzBUS. Edits src/bb_live.c and existing manifest checksums only.
Does not use git patch. DOS2 and JIT behaviour are unchanged.
"""
from __future__ import annotations
import argparse, copy, hashlib, json, re, shutil, tempfile
from pathlib import Path
import bb_dos622_irq0_isolation_v1 as parent

HERE = Path(__file__).resolve().parent
TAG='BB_DOS622_KEYB92_V1'
STATE='.bb_dos622_keyb92_v1_state'
SRC=parent.SRC
PARENTS=(*parent.PARENTS,parent.STATE+'/manifest.json')
ANCHOR=b'    uint8_t ah=(uint8_t)(*ax>>8);'
SNIPPET=r'''    /* BB_DOS622_KEYB92_V1: MS-DOS KEYB probes IBM enhanced keyboard with
       an undocumented INT 16h/AH=92h. IBM AT-compatible BIOS returns
       AH=80h by falling through its decrement chain. Do not simply
       reject this probe: KEYB requires the exact IBM BIOS result. */
#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE
    if (ah == 0x92u && bb_sd_dos622_active()) {
        const uint16_t in_ax = *ax;
        static unsigned probes;
        *ax = (uint16_t)((in_ax & 0x00FFu) | 0x8000u);
        if (++probes <= 4u) {
            printf("[bb622-keyb92] KEYB INT16/AH=92 in-ax=%04X out-ax=%04X (IBM enhanced keyboard)\n",
                   (unsigned)in_ax, (unsigned)*ax);
            fflush(stdout);
        }
        return 1;
    }
#endif
'''.encode('ascii')

def sha(b:bytes)->str: return hashlib.sha256(b).hexdigest()
def jd(d:dict)->bytes: return json.dumps(d,indent=2).encode('utf-8')

def transform(src:bytes)->bytes:
    if TAG.encode() in src: raise ValueError('keyb92 already installed: use verify')
    pattern=rb'(?m)^'+re.escape(ANCHOR)+rb'(?P<nl>\r\n|\n|\r|$)'
    hits=list(re.finditer(pattern,src))
    if len(hits)!=1:
        near=[line[:160] for line in src.splitlines() if b'uint8_t ah=' in line]
        raise ValueError(f'expected exactly one keyboard AH declaration; found {len(hits)}: {near[:4]}')
    m=hits[0]
    nl=m.group('nl') or b'\n'
    snippet=SNIPPET.replace(b'\n',nl)
    result=src[:m.end()]+snippet+src[m.end():]
    if result.count(TAG.encode())!=1 or result.count(b'[bb622-keyb92]')!=1:
        raise ValueError('source assertion failed after transform')
    return result

def plan(root:Path):
    if (root/STATE).exists():raise ValueError(f'{STATE} exists; use verify/restore')
    parent.verify(root,quiet=True)
    old={p:(root/p).read_bytes() for p in (SRC,*PARENTS)}
    changed={SRC:transform(old[SRC])}
    for p in PARENTS:
        obj=copy.deepcopy(json.loads(old[p]))
        for tracked,entry in obj.get('files',{}).items():
            if tracked in changed:
                for key in ('installed','new','after'):
                    if key in entry:entry[key]=sha(changed[tracked])
        if p==parent.parent.parent.parent.rtc.DIAG:
            obj['parent_after']=sha(changed[parent.parent.parent.parent.rtc.IPL])
        changed[p]=jd(obj)
    return {p:(old[p],changed[p]) for p in (SRC,*PARENTS)}

def verify(root:Path,quiet=False):
    st=root/STATE
    m=json.loads((st/'manifest.json').read_text(encoding='utf-8'))
    if m.get('tag')!=TAG:raise ValueError('wrong stage tag')
    for p,e in m['files'].items():
        if sha((root/p).read_bytes())!=e['after']:raise ValueError(f'installed SHA mismatch: {p}')
        if sha((st/e['backup']).read_bytes())!=e['before']:raise ValueError(f'backup SHA mismatch: {p}')
    parent.verify(root,quiet=True)
    data=(root/SRC).read_bytes()
    if data.count(TAG.encode())!=1 or data.count(b'[bb622-keyb92]')!=1:
        raise ValueError('KEYB92 source markers missing')
    if not quiet:print('VERIFIED: IBM KEYB AH92 compatibility, 11 parent manifest chains, byte-exact backups')

def apply(root:Path):
    updates=plan(root)
    st=root/STATE
    st.mkdir()
    try:
        m={'tag':TAG,'files':{}}
        for i,(p,(before,after)) in enumerate(updates.items()):
            backup=f'original_{i:02d}.bin'
            (st/backup).write_bytes(before)
            m['files'][p]={'before':sha(before),'after':sha(after),'backup':backup}
        (st/'manifest.json').write_bytes(jd(m))
        for p,(before,after) in updates.items():
            if (root/p).read_bytes()!=before:raise ValueError(f'concurrent modification: {p}')
            (root/p).write_bytes(after)
        verify(root,quiet=True)
    except BaseException:
        for p,(before,_) in updates.items():(root/p).write_bytes(before)
        shutil.rmtree(st,ignore_errors=True)
        raise
    print('APPLIED: DOS622 KEYB AH92 enhanced-keyboard BIOS probe; IRQ0 AB, JIT, DOS2 unchanged')

def restore(root:Path):
    verify(root,quiet=True)
    st=root/STATE
    m=json.loads((st/'manifest.json').read_text(encoding='utf-8'))
    for p,e in m['files'].items():(root/p).write_bytes((st/e['backup']).read_bytes())
    shutil.rmtree(st)
    parent.verify(root,quiet=True)
    print('RESTORED: source and 11 parent manifests byte-exact')

def selftest():
    # Run the same real parent-install stack as the preceding diagnostic
    # before applying our own modification, then verify complete rollback.
    inc_old=(HERE/'bb_dos622_textio_v1_original.inc').read_bytes()
    inc_new=(HERE/'bb_dos622_textio_psram_include.inc').read_bytes()
    heap_decl='''/* BB_DOS622_HEAP_RESCUE_V1: reclaim core SRAM for the JIT calloc heap.
 * Keep the first 16 translated-page bitmaps in fast SRAM (DOS2 peaked at 15).
 * The remaining BB_TR_PAGES - 16 entries are in PSRAM; each is zeroed on use.
 * No changes to BB_CODE_BYTES, JIT entry code, or the CPU interpreter. */
#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE
#define BB_TR_HOT_PAGES ((BB_TR_PAGES) > 16u ? 16u : (BB_TR_PAGES))
static uint8_t trpool[BB_TR_HOT_PAGES][MD_X86_CODE_PAGE_SIZE / 8u] __attribute__((aligned(4)));
#if BB_TR_PAGES > BB_TR_HOT_PAGES
static uint8_t __uninitialized_psram("bb_trpool_cold")
    trpool_cold[BB_TR_PAGES - BB_TR_HOT_PAGES][MD_X86_CODE_PAGE_SIZE / 8u] __attribute__((aligned(4)));
#endif
#else
static uint8_t trpool[BB_TR_PAGES][MD_X86_CODE_PAGE_SIZE / 8u] __attribute__((aligned(4)));
#endif
static unsigned trpool_used;
'''
    heap_use='''#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE && (BB_TR_PAGES > 16u)
                trbits[p] = trpool_used < 16u ? trpool[trpool_used]
                            : trpool_cold[trpool_used - 16u];
#else
                trbits[p] = trpool[trpool_used];
#endif
                ++trpool_used;
'''
    base=('''static void bb_v23_poll_input(void) {
    if(!bb_video_seen||!R)return;
    ++bb_v23_polls;
}
static int bb_v22_keyboard(void) {
    uint8_t ah=(uint8_t)(*ax>>8);
    bb_v23_poll_input();
    } else {
        *ax=bb_v22_word(m,0x400u+head);
    }
    return 1;
}
'''+heap_decl+'''void foo(unsigned p) {
 if (trpool_used < BB_TR_PAGES) {
'''+heap_use+''' }
}
'''+'''static int start(MdRuntime *rt) {
    if (bb_sd_dos622_active()) {
        bb_v15_original_interrupt = bb622_bios_interrupt;
    }
    return 1;
}
B86_HOT int bb_live_try(MdRuntime *rt, uint64_t left)
{
    if (R == NULL && !start(rt)) return 0;
    bb_v23_poll_input();
    if(rt==R)bb_irq36_dispatch(rt,bb_now_us());
    return 1;
}
''').encode('ascii')
    cases=(('LF',base),('CRLF',base.replace(b'\n',b'\r\n')),
           ('MIXED',base.replace(b'                ++trpool_used;\n',b'                ++trpool_used;\r\n')),
           ('CRLF_LF',base.replace(b'\n',b'\r\n').replace(b'    if(rt==R)bb_irq36_dispatch(rt,bb_now_us());\r\n',b'    if(rt==R)bb_irq36_dispatch(rt,bb_now_us());\n')))
    for name,raw in cases:
        with tempfile.TemporaryDirectory(prefix='bb622_keyb92_') as temp:
            root=Path(temp)
            parent.parent.parent.parent.fixture(root,raw)
            parent.parent.parent.parent.apply(root,inc_old)
            parent.parent.parent.apply(root,inc_new)
            parent.parent.apply(root)
            parent.apply(root)
            prior={p:(root/p).read_bytes() for p in (SRC,*PARENTS)}
            changes=plan(root)
            assert len(changes)==len(PARENTS)+1
            apply(root)
            verify(root,quiet=True)
            result=(root/SRC).read_bytes()
            assert result.count(TAG.encode())==1
            restore(root)
            assert all((root/p).read_bytes()==v for p,v in prior.items())
            assert not (root/STATE).exists()
            parent.verify(root,quiet=True)
            print(f'SELFTEST {name}: full parent chain + apply/verify/byte-exact restore PASS')
    print('SELFTEST PASS')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=('selftest','probe','apply','verify','restore'))
    p.add_argument('--root',type=Path,default=HERE)
    a=p.parse_args();root=a.root.resolve()
    try:
        if a.command=='selftest':selftest()
        elif a.command=='probe':
            changes=plan(root)
            for path,(old,new) in changes.items():
                print(f'{path}: {len(old)} -> {len(new)} bytes SHA {sha(old)[:12]} -> {sha(new)[:12]}')
            print('PROBE PASS: previous stage verified; no changes made')
        elif a.command=='apply':apply(root)
        elif a.command=='verify':verify(root)
        else:restore(root)
    except Exception as e:
        print(f'ERROR: {e}')
        raise SystemExit(1)
if __name__=='__main__':main()
