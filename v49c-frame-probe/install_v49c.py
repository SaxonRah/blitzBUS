#!/usr/bin/env python3
"""Guarded install of v49c frame diagnostic; accepts exactly v49b source."""
import argparse, hashlib, shutil, pathlib, sys
EXPECTED="29749285e582386157f6bf723f3a8918c09e803350d4e7dabb0867395aeafc43"
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--blitzbus",type=pathlib.Path,required=True)
    grp=ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--check",action="store_true")
    grp.add_argument("--apply",action="store_true")
    grp.add_argument("--restore",action="store_true")
    a=ap.parse_args(); target=a.blitzbus/"src"/"bb_v49_pc.h"
    backup=target.with_name(target.name+".before_v49c")
    replacement=pathlib.Path(__file__).resolve().parent/"bb_v49_pc.h"
    if a.restore:
        if not backup.exists(): sys.exit("ERROR: no v49c backup exists")
        if not target.exists() or sha(target)!=sha(replacement): sys.exit("ERROR: current file changed; refusing rollback")
        shutil.copy2(backup,target);print("RESTORED",target);return
    if not target.exists(): sys.exit("ERROR: missing "+str(target))
    if sha(target)!=EXPECTED: sys.exit("ERROR: source does not exactly match tested v49b header; no changes")
    if not replacement.exists(): sys.exit("ERROR: replacement missing")
    print("CHECK PASS: exact v49b header found")
    if a.apply:
        if backup.exists(): sys.exit("ERROR: backup already exists; refusing to overwrite")
        shutil.copy2(target,backup)
        shutil.copy2(replacement,target)
        print("INSTALLED",target,"BACKUP",backup)
if __name__=="__main__": main()
