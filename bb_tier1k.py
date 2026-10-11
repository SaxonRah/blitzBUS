#!/usr/bin/env python3
"""Tier1K fast-IRET helper A/B, conservative guest semantics, reversible files."""
import argparse, os, shutil, subprocess, sys
from pathlib import Path
B86=Path(r"C:\blitz86_v2")
BUS=Path(r"C:\blitzBUS")
ANCHOR="B86_HOT uint32_t b86h_step(B86Cpu *c, uint32_t ip_next, uint32_t blk)"
LINE="    int r = b86_step(c);"
FASTLINE="""    int r;
    /* T1K: dispatch plain (no-prefix) IRET through a narrow helper.
       Prefixed opcodes still use b86_step, preserving all decode behavior. */
    const uint32_t pc=((c->seg[B86_CS]<<4)+(ip_next & 0xFFFFu)) & c->amask;
    if (*b86_host(c,pc)==0xCFu) r=b86_fast_iret(c);
    else r=b86_step(c);"""
PROTOTYPE="/* T1K fast IRET entry, implemented in interp.c */\nextern int b86_fast_iret(B86Cpu *c);\n"
HELPER="""/* T1K fast IRET: exactly the three original pop operations and flag mask.
 * Only called for opcode CF without prefixes. No bypass of guest memory rules.
 */
B86_HOT int b86_fast_iret(B86Cpu *c)
{
    if (c->lz_kind != LZ_NONE || c->lz_ikind != LZ_NONE)
        b86_flags_materialize(c);
    c->step_op=0xCFu;
    c->step_oip=(uint16_t)c->ip;
    c->icount++;
    uint16_t new_ip=pop(c);
    uint16_t new_cs=pop(c);
    uint16_t new_flags=pop(c);
    b86_set_seg(c,B86_CS,new_cs);
    c->flags=(new_flags & 0x0FD5u) | 0xF002u;
    c->ip=new_ip;
    return B86_OK;
}

"""
def safe_read(p): return p.read_text(encoding="utf-8")
def paths(b86):return [(b86/"src"/"interp.c",b86/"tier1k-original-interp.c"),(b86/"src"/"jit.c",b86/"tier1k-original-jit.c")]
def mk_variant(interp,jit):
    if interp.count("B86_HOT static inline uint16_t pop(B86Cpu *c)")!=1: raise ValueError("pop helper anchor not unique")
    if jit.count(ANCHOR)!=1: raise ValueError("b86h_step anchor not unique")
    if jit.count(LINE)<1: raise ValueError("b86_step call not found")
    idx=jit.index(ANCHOR); tail=jit[idx:]
    if tail.count(LINE)<1:raise ValueError("step call missing after b86h_step")
    tail=tail.replace(LINE,FASTLINE,1)
    jit=jit[:idx]+tail
    jit=jit.replace(ANCHOR,PROTOTYPE+ANCHOR,1)
    # append helper after pop, immediately before section marker; constrained anchor
    pop_start=interp.index("B86_HOT static inline uint16_t pop(B86Cpu *c)")
    pos=interp.index("/* ------------------------------------------------------------------------ */",pop_start)
    interp=interp[:pos]+HELPER+interp[pos:]
    return interp,jit
def install(b86):
    entries=paths(b86)
    for src,bak in entries:
        if not src.exists():raise ValueError(f"Missing {src}")
        if bak.exists():raise ValueError(f"Backup exists: {bak}")
    original=[safe_read(src) for src,_ in entries]
    if "T1K" in original[0] or "T1K" in original[1]: raise ValueError("Tier1K already installed")
    variants=mk_variant(*original)
    for (src,bak),s in zip(entries,original):shutil.copy2(src,bak)
    try:
        for (src,_),content in zip(entries,variants):src.write_text(content,encoding="utf-8",newline="")
    except Exception:
        for src,bak in entries:shutil.copy2(bak,src)
        raise
    print("Installed Tier1K optimized helper in interp.c and jit.c. Original files backed up.")
def switch(b86,optimized):
    entries=paths(b86)
    for src,bak in entries:
        if not bak.exists():raise ValueError(f"Missing backup {bak}; first install")
    originals=[safe_read(bak) for _,bak in entries]
    variants=mk_variant(*originals)
    for (src,_),original,variant in zip(entries,originals,variants):
        if safe_read(src) not in (original,variant):raise ValueError(f"Unknown edits in {src}; refusing overwrite")
    for (src,_),s in zip(entries,variants if optimized else originals):
        src.write_text(s,encoding="utf-8",newline="")
    print("Tier1K mode:", "FAST HELPER" if optimized else "ORIGINAL b86_step")
def restore(b86):
    switch(b86,False)
    for _,bak in paths(b86):bak.unlink()
    print("Tier1K source restored; backups removed.")
def run(bus,b86):
    script=bus/"scripts"/"bb_live_run.ps1"
    if not script.exists():raise ValueError(f"Missing {script}")
    env=os.environ.copy()
    env.update(BB_LCD_PERI_HZ="150000000",BB_LCD_SPI_HZ="75000000",BB_LCD_LACE="1",
               BB_BBUF="0",BB_CODE_KB="292",BB_HOT_THRESHOLD="32")
    cmd=["powershell.exe","-NoProfile","-ExecutionPolicy","Bypass","-File",str(script),
         "-MicroDOS",r"C:\microDOS","-Blitz86",str(b86)]
    subprocess.run(cmd,env=env,check=True)
def main():
    p=argparse.ArgumentParser()
    p.add_argument("mode",choices=["install","baseline","optimized","run","restore"])
    p.add_argument("--blitz86",type=Path,default=B86)
    p.add_argument("--blitzbus",type=Path,default=BUS)
    a=p.parse_args()
    try:
        if a.mode=="install":install(a.blitz86)
        elif a.mode=="baseline":switch(a.blitz86,False)
        elif a.mode=="optimized":switch(a.blitz86,True)
        elif a.mode=="run":run(a.blitzbus,a.blitz86)
        else:restore(a.blitz86)
    except Exception as e:
        print("ERROR:",e,file=sys.stderr);return 1
    return 0
if __name__=="__main__":sys.exit(main())
