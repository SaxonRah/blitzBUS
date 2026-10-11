#!/usr/bin/env python3
"""Tier 1L native Thumb-2 IRET experimental A/B. Complete backup/restore."""
from pathlib import Path
import argparse, shutil, sys, subprocess
B86=Path(r'C:\blitz86_v2')
BUS=Path(r'C:\blitzBUS')
MARK='/* BB_TIER1L_NATIVE_IRET */'
CLASS='    case 0xCE: case 0xCF: case 0xEA:'
CLASSNEW='    case 0xCE: case 0xEA:'
CLASSINSERT='    case 0xCF: d->cls = C_END; d->native = 1; d->fuse = 0; d->fdef = ALLF; return; '+MARK
LOWER_ANCHOR='    if (op < 0x40 && (op & 7) < 6) {'
FAST=r'''    /* BB_TIER1L_NATIVE_IRET */
    if (op == 0xCFu) {
        /* Full guest decode semantics remain on fallback. Exact-wrap, segment
           crossing, 4 KiB page crossing and A20 boundary are guarded. */
        if (d->nprefix) return 0;
        uint8_t *slow[4];
        be_ldctx(e,V_T0,OFF(exact_wrap));
        slow[0]=be_cbnz(e,V_T0);
        be_cmpi_sh(e,V_T0,B86_SP,65530u,0,V_T1);
        slow[1]=be_jcc(e,AC_HI);
        be_ea(e,V_T0,B86_SS,B86_SP,-1,0);
        be_opi(e,AOP_AND,V_T1,V_T0,4095u);
        be_cmpi_sh(e,V_T1,V_T1,4090u,0,V_T2);
        slow[2]=be_jcc(e,AC_HI);
        /* Respect address-mask wrapping; only direct in-range access is native. */
        be_ldctx(e,V_T1,OFF(mem));
        be_op(e,AOP_SUB,V_T1,V_T0,V_T1);
        be_ldctx(e,V_T2,OFF(amask));
        be_opi(e,AOP_SUB,V_T2,V_T2,5u);
        be_cmp_sh(e,V_T1,V_T1,V_T2,0);
        slow[3]=be_jcc(e,AC_HI);
        emit_deferred(t,t->cur-1,d->live);
        /* Guest stack is unmapped by embedder contract; direct reads are valid
           only after the four boundary guards above. */
        be_ea(e,V_T0,B86_SS,B86_SP,-1,0);
        be_load(e,1,V_T1,V_T0);
        be_stctx(e,V_T1,OFF(ip));
        be_ea(e,V_T0,B86_SS,B86_SP,-1,4);
        be_load(e,1,V_T1,V_T0);
        be_opi(e,AOP_AND,V_T1,V_T1,0x0FD5u);
        be_opi(e,AOP_ORR,V_T1,V_T1,0xF002u);
        be_stctx(e,V_T1,OFF(flags));
        be_stctx_imm(e,0,OFF(lz_kind));
        be_stctx_imm(e,0,OFF(lz_ikind));
        be_ea(e,V_T0,B86_SS,B86_SP,-1,2);
        be_load(e,1,V_T1,V_T0);
        be_set_seg(e,B86_CS,V_T1);
        be_opi(e,AOP_ADD,B86_SP,B86_SP,6u);
        be_exit_dyn(e);
        uint8_t *fallback=e->p;
        for (unsigned k=0;k<4;++k) be_bind(e,slow[k],fallback);
        be_call_step(e,d->ip,d->next);
        be_exit_dyn(e);
        return 1;
    }
'''
def source_paths(root):
    return [(root/'src'/'jit.c',root/'tier1l-original-jit.c')]
def transform(s):
    for anchor in (CLASS,):
        if s.count(anchor)!=1:raise ValueError('Unexpected source, anchor count %d: %s'%(s.count(anchor),anchor))
    s=s.replace(CLASS,CLASSNEW,1)
    # Insert case into classify switch before CF grouped cases, with unique location.
    group='    case 0x9A: case 0xCA: case 0xC8: case 0xCB: case 0xC9: case 0xCC: case 0xCD:'
    if s.count(group)!=1:raise ValueError('classify group missing/ambiguous')
    s=s.replace(group,CLASSINSERT+'\n'+group,1)
    # Anchor lower() specifically, not earlier code that may share the same condition.
    start=s.index('B86_COLD static int lower(Tx *t, Insn *d)')
    prefix,tail=s[:start],s[start:]
    if tail.count(LOWER_ANCHOR)!=1:raise ValueError('lower anchor changed')
    return prefix+tail.replace(LOWER_ANCHOR,FAST+LOWER_ANCHOR,1)
def install(root):
    for src,bak in source_paths(root):
        if bak.exists():raise ValueError('Backup exists. restore first: '+str(bak))
        orig=src.read_text(encoding='utf-8')
        if MARK in orig:raise ValueError('Tier1L already present')
        new=transform(orig)
        shutil.copy2(src,bak)
        try:src.write_text(new,encoding='utf-8',newline='')
        except BaseException:shutil.copy2(bak,src);bak.unlink();raise
    print('Tier1L experimental native IRET installed; complete jit.c backup saved.')
def switch(root,opt):
    src,bak=source_paths(root)[0]
    if not bak.exists():raise ValueError('Backup missing: install first')
    orig=bak.read_text(encoding='utf-8');native=transform(orig)
    if src.read_text(encoding='utf-8') not in (orig,native):raise ValueError('Source changed unexpectedly; refusing overwrite')
    src.write_text(native if opt else orig,encoding='utf-8',newline='')
    print('Tier1L:', 'native' if opt else 'original')
def restore(root):
    switch(root,False)
    for _,bak in source_paths(root):bak.unlink()
    print('Original jit.c restored')
def main():
    p=argparse.ArgumentParser()
    p.add_argument('mode',choices=['install','baseline','native','restore','run'])
    p.add_argument('--blitz86',type=Path,default=B86)
    p.add_argument('--blitzbus',type=Path,default=BUS)
    a=p.parse_args()
    try:
        if a.mode=='install':install(a.blitz86)
        elif a.mode=='baseline':switch(a.blitz86,False)
        elif a.mode=='native':switch(a.blitz86,True)
        elif a.mode=='restore':restore(a.blitz86)
        else:
            subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(a.blitzbus/'scripts'/'bb_live_run.ps1'),'-MicroDOS',r'C:\microDOS','-Blitz86',str(a.blitz86),'-Port','COM5','-Seconds','180'],check=True)
    except Exception as exc:
        print('ERROR:',exc,file=sys.stderr);return 1
    return 0
if __name__=='__main__':sys.exit(main())
