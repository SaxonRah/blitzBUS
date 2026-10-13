#!/usr/bin/env python3
"""blitzBUS / blitz86 native-chain A/B diagnostic (reversible full-file backups).

Place in C:\\blitzBUS and run:
  python bb_chain_audit.py apply
  python bb_chain_audit.py verify
  python bb_chain_audit.py run --profiles on,off,on
  python bb_chain_audit.py summary
  python bb_chain_audit.py restore

A diagnostic only: normal chaining is unchanged in profile 'on'. 'off' is a
control to quantify benefits from block chaining, NOT an optimization.
"""
import argparse
import csv
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "bb_chain_audit_manifest.json"
RESULTS = ROOT / "logs" / "bb-chain-audit.csv"
MARK = "BB_CHAIN_AUDIT_V1"
KEYS = ["dispatches", "fast", "patched", "exit_chain", "exit_ret", "exit_lookup", "exit_irq",
        "exit_other", "stale", "disabled", "plog_full", "plog_peak", "ret_refused"]
HEADERS = ["timestamp", "profile", "score", "render_ok", "log", "meta_used", "meta_failures"] + KEYS


def encoded(path):
    # Binary reads preserve all existing CRLFs and user edits.
    b = path.read_bytes()
    bom = b.startswith(b"\xef\xbb\xbf")
    t = b.decode("utf-8-sig")
    nl = "\r\n" if "\r\n" in t else "\n"
    return t, nl, bom


def pack(t, bom):
    return (b"\xef\xbb\xbf" if bom else b"") + t.encode("utf-8")


def sh(data):
    return hashlib.sha256(data).hexdigest()


def replace1(text, needle, replacement, what):
    n = text.count(needle)
    if n != 1:
        raise RuntimeError(f"{what}: expected exactly one anchor, found {n}; no changes made")
    return text.replace(needle, replacement, 1)


def patch_jit(t, nl):
    # Internal stats live in a ~40-byte .bss record. No new allocations, no J ABI change.
    add = r'''/* BB_CHAIN_AUDIT_V1 - bounded diagnostic counters; only the dispatcher writes these. */
#ifndef BB_CHAIN_PROFILE
#define BB_CHAIN_PROFILE 0
#endif
#if BB_CHAIN_PROFILE
enum {
  CH_EXIT_CHAIN, CH_EXIT_RET, CH_EXIT_LOOKUP, CH_EXIT_IRQ, CH_EXIT_OTHER,
  CH_STALE, CH_DISABLED, CH_PLOG_FULL, CH_PLOG_PEAK, CH_RET_REFUSED,
  CH_NCOUNTERS
};
static uint32_t bb_chain_audit[CH_NCOUNTERS];
void b86_chain_audit_read(uint32_t out[10])
{
    memcpy(out, bb_chain_audit, sizeof bb_chain_audit);
}
#endif
'''.replace("\n", nl)
    t = replace1(t, "#define PLOGN 4096u", "#define PLOGN 4096u" + nl + add.rstrip("\r\n"), "jit: PLOGN")

    old = '    if (j->nplog >= PLOGN) return 0;'
    new = '''    if (j->nplog >= PLOGN) {
#if BB_CHAIN_PROFILE
        bb_chain_audit[CH_PLOG_FULL]++;
#endif
        return 0;
    }'''.replace("\n",nl)
    t = replace1(t, old, new, "jit: patch-log-full")
    old = '    l->site = site; l->target = target; l->aux = aux; l->kind = kind;'
    new = '''    l->site = site; l->target = target; l->aux = aux; l->kind = kind;
#if BB_CHAIN_PROFILE
    if (j->nplog > bb_chain_audit[CH_PLOG_PEAK]) bb_chain_audit[CH_PLOG_PEAK] = j->nplog;
#endif'''.replace("\n",nl)
    t = replace1(t, old, new, "jit: log peak")

    old = '                if (j->evict && j->nplog + 2 > PLOGN) { /* log full: leave the RET cache unpatched */ }'
    new = '''                if (j->evict && j->nplog + 2 > PLOGN) {
#if BB_CHAIN_PROFILE
                    bb_chain_audit[CH_RET_REFUSED]++;
#endif
                    /* log full: leave the RET cache unpatched */
                }'''.replace("\n",nl)
    t = replace1(t, old, new, "jit: RET log capacity")

    anchor = '        if (patch_site && patch_gen == j->flush_gen && !j->no_chain && plog_add(j, PL_CHAIN, patch_site, host, NULL)) {'
    instrumentation = '''#if BB_CHAIN_PROFILE
        if (patch_site && patch_gen != j->flush_gen) bb_chain_audit[CH_STALE]++;
        if (patch_site && patch_gen == j->flush_gen && j->no_chain) bb_chain_audit[CH_DISABLED]++;
#endif
'''.replace("\n",nl)
    t = replace1(t, anchor, instrumentation+anchor, "jit: patchable outgoing chain")

    anchor = '        switch (r) {'
    # Ensure this particular switch is within b86_jit_run, not one earlier in the file.
    pos = t.find('B86_HOT int b86_jit_run(')
    if pos < 0 or t[pos:].count(anchor) != 1:
        raise RuntimeError("jit: exit reason switch not uniquely found within b86_jit_run")
    prefix, suffix = t[:pos], t[pos:]
    instrumentation = '''#if BB_CHAIN_PROFILE
        if (r == XR_CHAIN) ++bb_chain_audit[CH_EXIT_CHAIN];
        else if (r == XR_RETFILL) ++bb_chain_audit[CH_EXIT_RET];
        else if (r == XR_LOOKUP) ++bb_chain_audit[CH_EXIT_LOOKUP];
        else if (r == XR_IRQ) ++bb_chain_audit[CH_EXIT_IRQ];
        else ++bb_chain_audit[CH_EXIT_OTHER];
#endif
'''.replace("\n",nl)
    t = prefix + replace1(suffix, anchor, instrumentation+anchor, "jit: native exit switch")
    return t


def patch_live(t,nl):
    ex = '/* BB_CHAIN_AUDIT_V1 */'+nl+'extern void b86_chain_audit_read(uint32_t out[10]);'+nl
    t=replace1(t, '#include "b86.h"', '#include "b86.h"'+nl+ex.rstrip("\r\n"), "live: header")
    anchor='    printf("[bb-jit] native-ms='
    report = '''#if defined(BB_CHAIN_PROFILE) && BB_CHAIN_PROFILE
    /* Cumulative counters: divide by an equal amount of benchmark work when comparing runs. */
    {
        uint32_t d[10] = {0};
        b86_chain_audit_read(d);
        printf("[bb-chain] no-chain=%u dispatches=%llu fast=%llu patched=%llu exit-chain=%lu exit-ret=%lu exit-lookup=%lu exit-irq=%lu exit-other=%lu stale=%lu disabled=%lu plog-full=%lu plog-peak=%lu ret-refused=%lu\\n",
               (unsigned)BB_NO_CHAIN,
               (unsigned long long)s->dispatches, (unsigned long long)s->fast_dispatches,
               (unsigned long long)s->chains,
               (unsigned long)d[0], (unsigned long)d[1], (unsigned long)d[2],
               (unsigned long)d[3], (unsigned long)d[4], (unsigned long)d[5],
               (unsigned long)d[6], (unsigned long)d[7], (unsigned long)d[8],
               (unsigned long)d[9]);
    }
#endif
'''.replace("\n",nl)
    t=replace1(t, anchor,report+anchor,"live: periodic JIT output")
    anchor='    b86_jit_set_hot_threshold(J, BB_HOT_THRESHOLD);'
    t=replace1(t,anchor,anchor+nl+'#if defined(BB_CHAIN_PROFILE) && BB_CHAIN_PROFILE'+nl+'    b86_jit_set_no_chain(J, BB_NO_CHAIN);'+nl+'#endif',"live: hot threshold setter")
    return t


def patch_install(t,nl):
    # Insert new env read beside the existing threshold read. Preserve user default 32 or 64.
    m = re.search(r'(?m)^    hot=os\.environ\.get\("BB_HOT_THRESHOLD","(?:32|64)"\)', t)
    if m is None or len(re.findall(r'(?m)^    hot=os\.environ\.get\("BB_HOT_THRESHOLD",',t))!=1:
        raise RuntimeError("installer: hot-threshold anchor changed; no changes made")
    line=m.group()
    pre='''    # BB_CHAIN_AUDIT_V1: test the existing chain mechanism, do not change its logic.
    no_chain=os.environ.get("BB_NO_CHAIN","0")
    if no_chain not in ("0","1"):
        raise SystemExit("BB_NO_CHAIN must be 0 or 1")
'''.replace("\n",nl)
    t=replace1(t,line,pre+line,"installer: env configuration")
    anchor='BB_CPU_MODEL={cpu_model}u'
    t=replace1(t,anchor,anchor+' BB_NO_CHAIN={no_chain} BB_CHAIN_PROFILE=1',"installer: compiled definitions")
    return t


def paths(args):
    return {
      "jit":Path(args.blitz86)/"src"/"jit.c",
      "live":ROOT/"src"/"bb_live.c",
      "installer":ROOT/"scripts"/"install_live.py",
    }


def apply(args):
    if MANIFEST.exists():
        raise RuntimeError("Experiment manifest already exists; run 'verify' or 'restore'")
    ps=paths(args)
    for k,p in ps.items():
        if not p.is_file():raise RuntimeError(f"Missing {k}: {p}")
    images={}; originals={}; modified={}
    for k,p in ps.items():
        t,nl,bom=encoded(p)
        if MARK in t:raise RuntimeError(f"{p}: experiment marker already present; no files changed")
        result={"jit":patch_jit,"live":patch_live,"installer":patch_install}[k](t,nl)
        before=p.read_bytes(); after=pack(result,bom)
        originals[k]=before; modified[k]=after
        images[k]=dict(path=str(p),backup=str(p)+".chain-audit-baseline.bak",before_sha=sh(before),after_sha=sh(after))
    for k, info in images.items():
        if Path(info["backup"]).exists():raise RuntimeError(f"Backup path already exists: {info['backup']}; no edits made")
    try:
        for k,info in images.items():Path(info['backup']).write_bytes(originals[k])
        for k,info in images.items():Path(info['path']).write_bytes(modified[k])
        MANIFEST.write_text(json.dumps({"marker":MARK,"files":images,"blitz86":str(args.blitz86)},indent=2),encoding="utf-8")
    except Exception:
        for k,info in images.items():
            if Path(info["backup"]).exists():Path(info["path"]).write_bytes(Path(info["backup"]).read_bytes())
        raise
    print("Installed chain diagnostics. Existing JIT reuse instrumentation and PSRAM layout preserved.")
    print("Manifest:",MANIFEST)
    verify(args)


def verify(args):
    if not MANIFEST.is_file():raise RuntimeError("No manifest; run 'apply' first")
    data=json.loads(MANIFEST.read_text(encoding="utf-8"))
    for k,item in data["files"].items():
        p=Path(item["path"])
        actual=sh(p.read_bytes()) if p.is_file() else None
        print(k,"OK" if actual==item["after_sha"] else "MODIFIED",str(p))
        if actual!=item["after_sha"]:
            raise RuntimeError("Source file changed after application. Preserve it; automatic restore disabled.")
    print("Diagnostics installed; compilation and hardware behavior not yet verified.")


def restore(args):
    verify(args)
    data=json.loads(MANIFEST.read_text(encoding="utf-8"))
    for name,item in data["files"].items():
        p=Path(item["path"]); b=Path(item["backup"])
        if not b.is_file() or sh(b.read_bytes())!=item["before_sha"]:
            raise RuntimeError(f"Baseline backup changed for {name}; refusing restore")
    for item in data["files"].values():
        Path(item["path"]).write_bytes(Path(item["backup"]).read_bytes())
        Path(item["backup"]).unlink()
    MANIFEST.unlink()
    print("Restored all 3 files to their pre-experiment versions. Rebuild/flash to restore original firmware.")


def parse(log):
    text=Path(log).read_text(encoding="utf-8",errors="replace")
    logs=re.findall(r'\[bb-chain\][^\r\n]*',text)
    out={k:"" for k in KEYS}
    if logs:
        for k,v in re.findall(r'([\w-]+)=(\d+)',logs[-1]):
            normalized=k.replace("-","_")
            if normalized in out:out[normalized]=int(v)
    meta=re.findall(r'\[bb-meta-usage\][^\r\n]*',text)
    for key in ("used","failures"):
        m=re.search(r'\b'+key+r'=(\d+)',meta[-1]) if meta else None
        out["meta_"+("used" if key=="used" else "failures")]=int(m.group(1)) if m else ""
    return out


def summary():
    if not RESULTS.exists():print("No results yet:",RESULTS);return
    records=list(csv.DictReader(RESULTS.open(encoding="utf-8",newline="")))
    for name in ("on","off"):
        rows=[r for r in records if r["profile"]==name]
        scores=sorted(float(r["score"]) for r in rows if r["render_ok"]=="yes" and r["score"])
        med=(scores[len(scores)//2] if len(scores)%2 else (scores[len(scores)//2-1]+scores[len(scores)//2])/2) if scores else None
        print(f"{name:3s} runs={len(rows)} valid={len(scores)} scores={scores} median={med}")
        for r in rows:
            print("  ",Path(r["log"]).name,"dispatch",r["dispatches"],"fast",r["fast"],
              "chains",r["patched"],"chain-exits",r["exit_chain"],"lookup-exits",r["exit_lookup"],
              "ret",r["exit_ret"],"stale",r["stale"],"plog-full",r["plog_full"],
              "peak",r["plog_peak"])


def run(args):
    verify(args)
    names=[s.strip().lower() for s in args.profiles.split(",")]
    if any(n not in ("on","off") for n in names):raise RuntimeError("Profiles must be 'on' or 'off'")
    base=os.environ.copy()
    base.update(BB_BBUF="1",BB_CODE_KB="232",BB_CPU="286",BB_SD_BOOT="1",
                BB_LCD_PERI_HZ="150000000",BB_LCD_SPI_HZ="75000000",BB_LCD_LACE="1",
                BB_HOT_THRESHOLD="32",BB_EVICT_CHUNK="4096",BB_EVICT_ROOM="2048")
    runner=ROOT/"scripts"/"bb_live_run.ps1"
    if not runner.exists():raise RuntimeError("Missing bb_live_run.ps1")
    RESULTS.parent.mkdir(parents=True,exist_ok=True)
    for name in names:
        env=base.copy();env["BB_NO_CHAIN"]="0" if name=="on" else "1"
        input(f"\nProfile {name.upper()}: chain={'ENABLED' if name=='on' else 'DISABLED'}. Press Enter to build/flash (Ctrl+C to stop)...")
        seen={str(p) for p in RESULTS.parent.glob("bb-live-*-console.txt")}
        cmd=["powershell.exe","-NoProfile","-ExecutionPolicy","Bypass","-File",str(runner),
             "-MicroDOS",args.microdos,"-Blitz86",args.blitz86,"-Port",args.port,"-Seconds",str(args.seconds)]
        ret=subprocess.run(cmd,cwd=str(ROOT),env=env)
        created=[p for p in RESULTS.parent.glob("bb-live-*-console.txt") if str(p) not in seen]
        created.sort(key=lambda p:p.stat().st_mtime,reverse=True)
        if ret.returncode or not created:
            print("Firmware run failed or no console log; skipping",name,file=sys.stderr)
            continue
        log=created[0]
        ok=input("Was all 3D geometry correctly rendered during 3DBench? [y/N]: ").strip().lower() in ("y","yes")
        s=input("Displayed 3DBench score (empty if unavailable): ").strip()
        try:score=float(s) if s else ""
        except ValueError:score=""
        data={"timestamp":datetime.datetime.now().isoformat(timespec="seconds"),
              "profile":name,"score":score,"render_ok":"yes" if ok else "no","log":str(log),**parse(log)}
        first=not RESULTS.exists()
        with RESULTS.open("a",newline="",encoding="utf-8") as f:
            w=csv.DictWriter(f,fieldnames=HEADERS)
            if first:w.writeheader()
            w.writerow(data)
        print("Recorded",data);summary()
    print("Test sequence complete. Reflash 'on' before normal development if the last profile was 'off'.")


def main():
    ap=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    sub=ap.add_subparsers(dest="action",required=True)
    for a in ("apply","verify","restore","summary"):
        sp=sub.add_parser(a)
        sp.add_argument("--blitz86",default=r"C:\blitz86_v2")
    p=sub.add_parser("run")
    p.add_argument("--profiles",default="on,off,on")
    p.add_argument("--seconds",type=int,default=180)
    p.add_argument("--port",default="COM5")
    p.add_argument("--microdos",default=r"C:\microDOS")
    p.add_argument("--blitz86",default=r"C:\blitz86_v2")
    args=ap.parse_args()
    try:
        if args.action=="apply":apply(args)
        elif args.action=="verify":verify(args)
        elif args.action=="restore":restore(args)
        elif args.action=="summary":summary()
        elif args.action=="run":run(args)
    except (RuntimeError, KeyboardInterrupt) as e:
        print("STOPPED:",e,file=sys.stderr);return 1
    return 0
if __name__=="__main__":sys.exit(main())
