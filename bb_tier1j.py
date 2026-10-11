#!/usr/bin/env python3
"""Tier 1J reversible A/B: batch IRET stack reads; preserve exact_wrap/paging via rd16."""
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT=Path(r"C:\blitzBUS")
B86=Path(r"C:\blitz86_v2")
OLD="case 0xCF: s->ip = pop(c); b86_set_seg(c, B86_CS, pop(c)); FL = (pop(c) & 0x0FD5u) | 0xF002u; break;"
NEW="""case 0xCF: { /* Tier1J: one SP update, three equivalent rd16 stack reads.
         rd16 retains exact_wrap, page mapping and memory tracing behavior. */
        uint16_t sp=(uint16_t)c->r[B86_SP];
        uint16_t new_ip=rd16(c,B86_SS,sp);
        uint16_t new_cs=rd16(c,B86_SS,(uint16_t)(sp+2u));
        uint16_t new_flags=rd16(c,B86_SS,(uint16_t)(sp+4u));
        c->r[B86_SP]=(uint16_t)(sp+6u);
        s->ip=new_ip;
        b86_set_seg(c,B86_CS,new_cs);
        FL=(new_flags & 0x0FD5u) | 0xF002u;
        break; }"""
def file_paths(blitz):
    return blitz/"src"/"interp.c", blitz/"tier1j-original-interp.c"

def install(blitz):
    src,back=file_paths(blitz)
    if not src.exists(): raise RuntimeError(f"Missing {src}")
    if back.exists(): raise RuntimeError(f"Backup already exists: {back}. Use mode restore first.")
    s=src.read_text(encoding="utf-8")
    if s.count(OLD)!=1: raise RuntimeError("Expected one unmodified IRET case. Restore Tier1I first; no edits made.")
    shutil.copy2(src,back)
    src.write_text(s.replace(OLD,NEW),encoding="utf-8",newline="")
    print(f"Tier1J OPT installed. Backup: {back}")
def baseline(blitz):
    src,back=file_paths(blitz)
    if not back.exists(): raise RuntimeError("First run mode install to create a backup.")
    original=back.read_text(encoding="utf-8")
    if original.count(OLD)!=1: raise RuntimeError("Saved baseline does not match expected IRET.")
    if not src.exists(): raise RuntimeError(f"Missing {src}")
    now=src.read_text(encoding="utf-8")
    if NEW not in now and OLD not in now: raise RuntimeError("Unknown local source changes; refusing overwrite.")
    shutil.copy2(back,src)
    print("Tier1J BASELINE enabled (original IRET).")
def optimized(blitz):
    src,back=file_paths(blitz)
    if not back.exists(): raise RuntimeError("First run mode install.")
    original=back.read_text(encoding="utf-8")
    if original.count(OLD)!=1: raise RuntimeError("Saved baseline unexpectedly changed.")
    now=src.read_text(encoding="utf-8")
    if now!=original and now!=original.replace(OLD,NEW):
        raise RuntimeError("Unknown local source edits; refusing overwrite.")
    src.write_text(original.replace(OLD,NEW),encoding="utf-8",newline="")
    print("Tier1J OPT enabled.")
def restore(blitz):
    src,back=file_paths(blitz)
    if not back.exists(): raise RuntimeError("Tier1J backup not found.")
    current=src.read_text(encoding="utf-8")
    original=back.read_text(encoding="utf-8")
    if current!=original and current!=original.replace(OLD,NEW):
        raise RuntimeError("Unexpected modifications in interp.c; refusing overwrite.")
    shutil.copy2(back,src)
    back.unlink()
    print("Tier1J original interp.c restored.")
def run(bus,blitz,port,seconds):
    script=bus/"scripts"/"bb_live_run.ps1"
    if not script.exists():raise RuntimeError(f"Missing {script}")
    env=os.environ.copy()
    env.update(BB_LCD_PERI_HZ="150000000",BB_LCD_SPI_HZ="75000000",
               BB_LCD_LACE="1",BB_BBUF="0",BB_CODE_KB="292",BB_HOT_THRESHOLD="32")
    cmd=["powershell.exe","-NoProfile","-ExecutionPolicy","Bypass","-File",str(script),
         "-MicroDOS",r"C:\microDOS","-Blitz86",str(blitz),"-Port",port,"-Seconds",str(seconds)]
    subprocess.run(cmd,env=env,check=True)
def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mode",choices=["install","baseline","optimized","restore","run"])
    ap.add_argument("--blitz86",type=Path,default=B86)
    ap.add_argument("--blitzbus",type=Path,default=ROOT)
    ap.add_argument("--port",default="COM5")
    ap.add_argument("--seconds",type=int,default=180)
    a=ap.parse_args()
    try:
        if a.mode=="install":install(a.blitz86)
        if a.mode=="baseline":baseline(a.blitz86)
        if a.mode=="optimized":optimized(a.blitz86)
        if a.mode=="restore":restore(a.blitz86)
        if a.mode=="run":run(a.blitzbus,a.blitz86,a.port,a.seconds)
    except Exception as e:
        print(f"ERROR: {e}",file=sys.stderr)
        return 1
    return 0
if __name__=="__main__":sys.exit(main())
