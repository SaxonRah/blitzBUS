#!/usr/bin/env python3
"""Reversible DOS622-only IRQ0 A/B isolation + keyboard dequeue diagnostics.

Commands: selftest | probe | apply | verify | restore
Must reside in C:\\blitzBUS alongside all preceding installer modules and manifests.
Full-file transactional installer; NOT a Git patch; modifies only src/bb_live.c
and updates manifests, leaving BIOS, textio, JIT and SD source unchanged.
"""
from __future__ import annotations
import argparse, copy, hashlib, json, re, shutil, tempfile
from pathlib import Path
import bb_dos622_sram_floor_v1 as parent

HERE = Path(__file__).resolve().parent
TAG = 'BB_DOS622_IRQ0_ISOLATION_V1'
STATE = '.bb_dos622_irq0_isolation_v1_state'
SRC = parent.SRC
PARENTS = (*parent.PARENTS, parent.STATE + '/manifest.json')

def sha(b: bytes) -> str: return hashlib.sha256(b).hexdigest()
def jd(d: dict) -> bytes: return json.dumps(d, indent=2).encode('utf-8')

def replace_exact_line_once(src: bytes, line: bytes, replacement: bytes, label: str) -> bytes:
    matches=list(re.finditer(rb'(?m)^'+re.escape(line)+rb'(?P<eol>\r\n|\n|\r|$)', src))
    if len(matches)!=1:
        near=[x.decode('utf-8','replace')[:140] for x in src.splitlines() if line.strip()[:20] in x]
        raise ValueError(f'{label}: expected 1 exact line, got {len(matches)}; similar lines={near[:5]}')
    m=matches[0]; nl=m.group('eol') or b'\n'
    return src[:m.start()] + replacement.replace(b'@NL@',nl) + src[m.end():]

def transform(src: bytes) -> bytes:
    if TAG.encode() in src: raise ValueError('IRQ0 A/B stage already installed; use verify')
    # Option available to compile with BB622_IRQ0_AB_DISABLE=0, but default is 1.
    # This changes only DOS622 when actually mounted, never DOS2 or host.
    src=replace_exact_line_once(src,
        b'    if(rt==R)bb_irq36_dispatch(rt,bb_now_us());',
        b'    /* BB_DOS622_IRQ0_ISOLATION_V1: A/B test native IRQ0 guest-stack delivery */@NL@'
        b'    if (rt == R) {@NL@'
        b'#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE && BB622_IRQ0_AB_DISABLE@NL@'
        b'        if (!bb_sd_dos622_active()) bb_irq36_dispatch(rt, bb_now_us());@NL@'
        b'#else@NL@'
        b'        bb_irq36_dispatch(rt, bb_now_us());@NL@'
        b'#endif@NL@'
        b'    }@NL@',
        'IRQ0 dispatch')
    src=replace_exact_line_once(src,
        b'        bb_v15_original_interrupt = bb622_bios_interrupt;',
        b'#ifndef BB622_IRQ0_AB_DISABLE@NL@'
        b'#define BB622_IRQ0_AB_DISABLE 1@NL@'
        b'#endif@NL@'
        b'        bb_v15_original_interrupt = bb622_bios_interrupt;@NL@'
        b'#if BB622_IRQ0_AB_DISABLE@NL@'
        b'        printf("[bb622-irq0-ab] IRQ0 delivery SUPPRESSED for DOS622 ONLY (diagnostic, not final fix)\\n"); fflush(stdout);@NL@'
        b'#else@NL@'
        b'        printf("[bb622-irq0-ab] IRQ0 delivery ENABLED for DOS622 (control)\\n"); fflush(stdout);@NL@'
        b'#endif@NL@',
        'DOS622 boot announcement')
    src=replace_exact_line_once(src,
        b'        *ax=bb_v22_word(m,0x400u+head);',
        b'        *ax=bb_v22_word(m,0x400u+head);@NL@'
        b'#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE@NL@'
        b'        if (bb_sd_dos622_active() && (ah==0u || ah==0x10u)) {@NL@'
        b'            printf("[bb622-key-ab] consumed AX=%04X head=%04X tail=%04X\\n", (unsigned)*ax, (unsigned)head, (unsigned)tail); fflush(stdout);@NL@'
        b'        }@NL@'
        b'#endif@NL@',
        'BIOS keyboard dequeue')
    if src.count(TAG.encode()) != 1 or src.count(b'[bb622-key-ab]') != 1:
        raise ValueError('post-transform source validation failed')
    return src

def plan(root: Path):
    if (root/STATE).exists(): raise ValueError(f'{STATE} exists; use verify/restore')
    parent.verify(root, quiet=True)
    old={p:(root/p).read_bytes() for p in (SRC,*PARENTS)}
    changed={SRC:transform(old[SRC])}
    for p in PARENTS:
        obj=copy.deepcopy(json.loads(old[p]))
        for tracked, entry in obj.get('files',{}).items():
            if tracked in changed:
                for key in ('installed','new','after'):
                    if key in entry:entry[key]=sha(changed[tracked])
        if p == parent.parent.parent.rtc.DIAG:
            obj['parent_after']=sha(changed[parent.parent.parent.rtc.IPL])
        changed[p]=jd(obj)
    return {p:(old[p],changed[p]) for p in (SRC,*PARENTS)}

def verify(root: Path, quiet=False):
    st=root/STATE
    m=json.loads((st/'manifest.json').read_text(encoding='utf-8'))
    if m.get('tag')!=TAG: raise ValueError('incorrect stage manifest tag')
    for p,it in m['files'].items():
        if sha((root/p).read_bytes())!=it['after']:raise ValueError(f'installed hash mismatch: {p}')
        if sha((st/it['backup']).read_bytes())!=it['before']:raise ValueError(f'backup mismatch: {p}')
    parent.verify(root, quiet=True)
    src=(root/SRC).read_bytes()
    if src.count(TAG.encode())!=1 or src.count(b'[bb622-irq0-ab] IRQ0 delivery SUPPRESSED')!=1:
        raise ValueError('IRQ0 A/B source markers missing')
    if not quiet:print('VERIFIED: DOS622-only IRQ0 A/B + key consume trace, all 10 parent manifests & backups')

def apply(root: Path):
    updates=plan(root)
    st=root/STATE
    st.mkdir()
    try:
        m={'tag':TAG, 'files':{}}
        for i,(p,(before,after)) in enumerate(updates.items()):
            bak=f'original_{i:02d}.bin'
            (st/bak).write_bytes(before)
            m['files'][p]={'before':sha(before),'after':sha(after),'backup':bak}
        (st/'manifest.json').write_bytes(jd(m))
        for p,(before,after) in updates.items():
            if (root/p).read_bytes()!=before:raise ValueError(f'concurrent modification: {p}')
            (root/p).write_bytes(after)
        verify(root,quiet=True)
    except BaseException:
        for p,(before,_) in updates.items():(root/p).write_bytes(before)
        shutil.rmtree(st,ignore_errors=True)
        raise
    print('APPLIED: opt-in DOS622 IRQ0 suppression + keyboard dequeue trace, no JIT/BIOS/SD changes')

def restore(root: Path):
    verify(root,quiet=True)
    st=root/STATE
    m=json.loads((st/'manifest.json').read_text(encoding='utf-8'))
    for p,it in m['files'].items(): (root/p).write_bytes((st/it['backup']).read_bytes())
    shutil.rmtree(st)
    parent.verify(root,quiet=True)
    print('RESTORED: all source and 10 parent manifests byte-exact')

def selftest():
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
    tests=(('LF',base),('CRLF',base.replace(b'\n',b'\r\n')),('MIXED',base.replace(b'                ++trpool_used;\n',b'                ++trpool_used;\r\n')),('CRLF_LF',base.replace(b'\n',b'\r\n').replace(b'    if(rt==R)bb_irq36_dispatch(rt,bb_now_us());\r\n',b'    if(rt==R)bb_irq36_dispatch(rt,bb_now_us());\n')))
    for name,raw in tests:
        with tempfile.TemporaryDirectory(prefix='bb622_irq0ab_') as tmp:
            root=Path(tmp)
            parent.parent.parent.fixture(root,raw)
            parent.parent.parent.apply(root,inc_old)
            parent.parent.apply(root,inc_new)
            parent.apply(root)
            before={p:(root/p).read_bytes() for p in (SRC,*PARENTS)}
            n=plan(root)
            assert len(n)==len(PARENTS)+1
            apply(root)
            verify(root,quiet=True)
            assert b'BB622_IRQ0_AB_DISABLE 1' in (root/SRC).read_bytes()
            restore(root)
            assert all((root/p).read_bytes()==b for p,b in before.items())
            assert not (root/STATE).exists()
            parent.verify(root,quiet=True)
            print(f'SELFTEST {name}: source+all parent manifests exact install/verify/restore PASS')
    print('SELFTEST PASS')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=('selftest','probe','apply','verify','restore'))
    p.add_argument('--root',type=Path,default=HERE)
    args=p.parse_args()
    root=args.root.resolve()
    try:
        if args.command=='selftest':selftest()
        elif args.command=='probe':
            changes=plan(root)
            for p,(old,new) in changes.items():
                print(f'{p}: {len(old)} -> {len(new)} bytes SHA {sha(old)[:12]} -> {sha(new)[:12]}')
            print('PROBE PASS: verified parent checksum chain; no changes made')
        elif args.command=='apply':apply(root)
        elif args.command=='verify':verify(root)
        else:restore(root)
    except Exception as e:
        print(f'ERROR: {e}')
        raise SystemExit(1)
if __name__=='__main__':main()
