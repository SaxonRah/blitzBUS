#!/usr/bin/env python3
"""blitzBUS / blitz86 bounded retranslation hot-promotion A/B experiment.

Requires the existing bb_jit_reuse_diag.py experiment to be APPLIED.
This experiment modifies only:
    C:\\blitz86_v2\\src\\jit.c
    C:\\blitzBUS\\src\\bb_live.c
    C:\\blitzBUS\\scripts\\install_live.py
It preserves existing PSRAM layout and eviction configuration edits.

Examples (run from C:\\blitzBUS):
    python bb_retranslation_promotion.py apply
    python bb_retranslation_promotion.py verify
    python bb_retranslation_promotion.py run --profiles 32,1,4,8,32
    python bb_retranslation_promotion.py summary
    python bb_retranslation_promotion.py restore

Promotion remains a threshold-only optimization. Eviction, SMC invalidation,
chain/RET patch undo, and native block data are unchanged.
"""
import argparse
import csv
import datetime as dt
import os
import re
import subprocess
import sys
from pathlib import Path

MARK = "BB_REUSE_PROMOTION_V1"
PROFILES = (32, 1, 4, 8)
FIELDS = ["time", "target", "score", "render_ok", "log", "reports",
          "early_hot", "early_compiled", "evicted_keys", "retranslated",
          "slot_collisions", "broken_patches", "evictions", "evicted",
          "unchains", "translate_ms", "meta_failures"]


def rd(p):
    return p.read_text(encoding="utf-8-sig")


def replace_one(s, old, new, desc):
    count = s.count(old)
    if count != 1:
        raise RuntimeError(f"{desc}: source anchor expected once, found {count}; nothing modified")
    return s.replace(old, new, 1)


def paths(a):
    root = Path(a.root).resolve()
    blitz = Path(a.blitz).resolve()
    return root, [blitz / "src" / "jit.c", root / "src" / "bb_live.c",
                  root / "scripts" / "install_live.py"]


def modifications(j, l, installer):
    if "BB_REUSE_DIAG_V1" not in j or "BB_REUSE_DIAG_V1" not in l:
        raise RuntimeError("Apply bb_jit_reuse_diag.py first; diagnostic source anchors absent")
    if MARK in j or MARK in l or MARK in installer:
        raise RuntimeError("Promotion experiment already installed or partly installed")

    j = replace_one(j, "static uint32_t bbdiag_evicted_lost_chains;",
'''static uint32_t bbdiag_evicted_lost_chains;
/* BB_REUSE_PROMOTION_V1: recent eviction hint, NOT a cache of executable code. */
#ifndef BB_REUSE_PROMOTE
#define BB_REUSE_PROMOTE 32u
#endif
#if BB_REUSE_PROMOTE != 32u && BB_REUSE_PROMOTE != 1u && BB_REUSE_PROMOTE != 4u && BB_REUSE_PROMOTE != 8u
#error BB_REUSE_PROMOTE_must_be_32_1_4_or_8
#endif
/* Reuse the original 256-byte validity table as epoch timestamps.
   Promotion expires after 64 eviction passes, and validity is cleared
   before the uint8_t epoch wraps. This adds no per-slot RAM. */
static uint8_t bbpromo_epoch = 1u;
static uint32_t bbpromo_early_hot, bbpromo_early_compiled;
static void bbpromo_advance(void) {
    if (++bbpromo_epoch == 0u) {
        memset(bbdiag_evicted_valid, 0, sizeof bbdiag_evicted_valid);
        bbpromo_epoch = 1u;
    }
}
''', "promotion helpers and compile-time switch")

    j = replace_one(j,
        "static void bbdiag_evict(uint32_t key) {",
'''/* Only an exact recently-evicted guest CS:IP is eligible. */
static inline int bbpromo_recent(uint32_t key) {
    uint32_t s = bbdiag_slot(key);
    uint8_t t = bbdiag_evicted_valid[s];
    return t && bbdiag_evicted_keys[s] == key &&
           (unsigned)(bbpromo_epoch - t) <= 64u;
}
static void bbdiag_evict(uint32_t key) {''',
        "recent-eviction lookup")
    j = replace_one(j,
        "    bbdiag_evicted_valid[s]=1;",
        "    bbdiag_evicted_valid[s]=bbpromo_epoch;",
        "timestamp on eviction")
    j = replace_one(j,
        "    j->st.evictions++;\n    for (uint32_t i = 0; i < j->nblk; ++i) {",
        "    j->st.evictions++;\n    bbpromo_advance();\n    for (uint32_t i = 0; i < j->nblk; ++i) {",
        "advance bounded history at each eviction")

    j = replace_one(j,
        "    if (heat_bump(j, key) >= j->hot_threshold && !force) return 0;",
'''    unsigned bbpromo_heat = heat_bump(j, key);
    unsigned bbpromo_threshold = j->hot_threshold;
#if BB_REUSE_PROMOTE < 32u
    if (!force && bbpromo_threshold > BB_REUSE_PROMOTE && bbpromo_recent(key))
        bbpromo_threshold = BB_REUSE_PROMOTE;
    if (!force && bbpromo_threshold < j->hot_threshold &&
        bbpromo_heat >= bbpromo_threshold && bbpromo_heat < j->hot_threshold)
        ++bbpromo_early_hot;
#endif
    if (bbpromo_heat >= bbpromo_threshold && !force) return 0;''',
        "entry cold-run threshold")

    j = replace_one(j,
        "            if (heat_bump(j, (cs << 16) | (c->ip & 0xFFFFu)) >= j->hot_threshold) break;",
'''            {
                uint32_t bbpromo_next_key = (cs << 16) | (c->ip & 0xFFFFu);
                unsigned bbpromo_threshold = j->hot_threshold;
#if BB_REUSE_PROMOTE < 32u
                if (bbpromo_threshold > BB_REUSE_PROMOTE && bbpromo_recent(bbpromo_next_key))
                    bbpromo_threshold = BB_REUSE_PROMOTE;
#endif
                unsigned bbpromo_heat = heat_bump(j, bbpromo_next_key);
#if BB_REUSE_PROMOTE < 32u
                if (bbpromo_threshold < j->hot_threshold &&
                    bbpromo_heat >= bbpromo_threshold && bbpromo_heat < j->hot_threshold)
                    ++bbpromo_early_hot;
#endif
                if (bbpromo_heat >= bbpromo_threshold) break;
            }''',
        "taken-branch cold-run threshold")

    j = replace_one(j,
        "    if (!npre) bbdiag_translate(b->key);",
'''#if BB_REUSE_PROMOTE < 32u
    if (!npre && bbpromo_recent(b->key)) {
        uint32_t hs = (b->key * 2654435761u) >> (32 - HEAT_BITS);
        if (j->heat_key[hs] == b->key && j->heat[hs] < j->hot_threshold)
            ++bbpromo_early_compiled;
    }
#endif
    if (!npre) bbdiag_translate(b->key);''',
        "successful translation accounting")

    j = replace_one(j,
        "void b86_jit_reuse_diag(uint32_t *evicted, uint32_t *retranslated,",
'''void b86_jit_promotion_diag(uint32_t *early_hot, uint32_t *early_compiled) {
    if (early_hot) *early_hot = bbpromo_early_hot;
    if (early_compiled) *early_compiled = bbpromo_early_compiled;
}
void b86_jit_reuse_diag(uint32_t *evicted, uint32_t *retranslated,''',
        "public cumulative counters")

    l = replace_one(l,
        '    printf("[bb-jit] native-ms=',
'''#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE
    /* BB_REUSE_PROMOTION_V1: two cumulative counters, same JIT report cadence. */
    { uint32_t hot=0,compiled=0;
      extern void b86_jit_promotion_diag(uint32_t *, uint32_t *);
      b86_jit_promotion_diag(&hot, &compiled);
      printf("[bb-promo] target=%lu early-hot=%lu early-compiled=%lu\\n",
             (unsigned long)BB_REUSE_PROMOTE, (unsigned long)hot, (unsigned long)compiled);
    }
#endif
    printf("[bb-jit] native-ms=''',
        "periodic promotion report")

    # Preserve any prior PSRAM layout / eviction tuning modifications.
    tpat = re.compile(r'(?m)^    hot=os\.environ\.get\("BB_HOT_THRESHOLD","\d+"\).*$')
    matches = list(tpat.finditer(installer))
    if len(matches) != 1:
        raise RuntimeError(f"installer threshold setting anchor expected once, found {len(matches)}")
    addition = '''    # BB_REUSE_PROMOTION_V1 - exact code-reuse promotion threshold.
    promotion_target=int(os.environ.get("BB_REUSE_PROMOTE", "32"))
    if promotion_target not in (32, 1, 4, 8):
        raise SystemExit("BB_REUSE_PROMOTE must be 32,1,4,8")
'''
    m = matches[0]
    installer = installer[:m.start()] + addition + installer[m.start():]
    installer = replace_one(installer,
        "    B86_MAXB=2048 B86_MAP_BITS=12 B86_FAST_BITS=10",
        "    B86_MAXB=2048 B86_MAP_BITS=12 B86_FAST_BITS=10 BB_REUSE_PROMOTE={promotion_target}u",
        "per-target JIT compile define")
    return j, l, installer


def apply(a):
    root, src = paths(a)
    if not all(p.is_file() for p in src):
        raise RuntimeError("Missing local source: " + ", ".join(str(p) for p in src if not p.is_file()))
    old = [p.read_bytes() for p in src]
    new = modifications(*[rd(p) for p in src])  # validate ALL anchors before writing anything
    backups = [Path(str(p) + ".promo-v1.bak") for p in src]
    if any(b.exists() for b in backups):
        raise RuntimeError("Backup already exists; refusing to overwrite. Use verify/restore first")
    for p,b in zip(src,backups):
        b.write_bytes(p.read_bytes())
    try:
        for p,s in zip(src,new):
            p.write_text(s,encoding="utf-8")
    except BaseException:
        for p,b in zip(src,old):
            p.write_bytes(b)
        raise
    print("Promotion support installed. Files modified:")
    for p in src: print(" ",p)
    print("Existing eviction and PSRAM layout changes preserved in original source.")


def verify(a):
    _,src=paths(a)
    for p in src:
        print(p, ":", "promotion present" if p.is_file() and MARK in rd(p) else "promotion ABSENT")
    if all(p.is_file() and MARK in rd(p) for p in src):
        print("Profiles: control=32, promote=1/4/8; BB_HOT_THRESHOLD must remain 32")


def restore(a):
    _,src=paths(a)
    backups=[Path(str(p)+".promo-v1.bak") for p in src]
    for p,b in zip(src,backups):
        if not b.is_file() or not p.is_file() or MARK not in rd(p):
            raise RuntimeError("Restore preflight failed at "+str(p)+"; nothing changed")
    for p,b in zip(src,backups):
        p.write_bytes(b.read_bytes())
    for b in backups:b.unlink()
    print("Restored all three pre-promotion files. Previous reuse diagnostic and installer experiments remain.")
    print("Rebuild the firmware to deploy the restored code.")


def metrics(log):
    raw=log.read_text(encoding="utf-8",errors="replace")
    def reports(prefix):return re.findall(r"(?m)^\["+re.escape(prefix)+r"\][^\r\n]*",raw)
    jits=reports("bb-jit")
    promos=reports("bb-promo")
    reuse=reports("bb-reuse")
    meta=reports("bb-meta-usage")
    def field(lines,k,default=0):
        if not lines:return default
        m=re.search(r"(?<![\w-])"+re.escape(k)+r"=(\d+)",lines[-1])
        return int(m.group(1)) if m else default
    # bb-jit reports interval deltas, not cumulative; sum them.
    def subtotal(k):
        return sum(int(m.group(1)) for line in jits if
                   (m:=re.search(r"(?<![\w-])"+re.escape(k)+r"=(\d+)",line)))
    return dict(reports=len(jits), early_hot=field(promos,"early-hot"),
      early_compiled=field(promos,"early-compiled"),
      evicted_keys=field(reuse,"evicted-keys"),
      retranslated=field(reuse,"retranslated"),
      slot_collisions=field(reuse,"slot-collisions"),
      broken_patches=field(reuse,"broken-patches"),
      evictions=subtotal("evictions"),evicted=subtotal("evicted"),
      unchains=subtotal("unchains"),translate_ms=subtotal("translate-ms"),
      meta_failures=field(meta,"failures",default=""))


def summary(a):
    root,_=paths(a)
    csvp=root/"logs"/"bb-retranslation-promotion.csv"
    if not csvp.exists():
        print("No results yet:",csvp);return
    rows=list(csv.DictReader(csvp.open(encoding="utf-8",newline="")))
    for target in PROFILES:
        rs=[r for r in rows if int(r["target"])==target]
        if not rs:continue
        scores=sorted(float(r["score"]) for r in rs if r["render_ok"]=="yes" and r["score"])
        median=(scores[len(scores)//2] if len(scores)%2 else
                (scores[len(scores)//2-1]+scores[len(scores)//2])/2) if scores else None
        print(f"target={target:>2} runs={len(rs)} valid={len(scores)} scores={scores} median={median} "
              f"early_compiled={[r['early_compiled'] for r in rs]} "
              f"retranslated={[r['retranslated'] for r in rs]} "
              f"translate_ms={[r['translate_ms'] for r in rs]}")


def run(a):
    root,src=paths(a)
    if not all(p.is_file() and MARK in rd(p) for p in src):
        raise RuntimeError("Run 'apply' first")
    targets=[int(v.strip()) for v in a.profiles.split(",")]
    if not targets or any(x not in PROFILES for x in targets):
        raise RuntimeError("Profiles must be comma-separated 32,1,4,8")
    logs=root/"logs";logs.mkdir(parents=True,exist_ok=True)
    out=logs/"bb-retranslation-promotion.csv"
    runner=root/"scripts"/"bb_live_run.ps1"
    if not runner.is_file():raise RuntimeError("Missing live-run script")
    env=os.environ.copy()
    env.update(BB_BBUF="1",BB_CODE_KB="232",BB_CPU="286",BB_SD_BOOT="1",
       BB_LCD_PERI_HZ="150000000",BB_LCD_SPI_HZ="75000000",BB_LCD_LACE="1",
       BB_PAGED="1", BB_HOT_THRESHOLD="32",BB_EVICT_CHUNK="4096",BB_EVICT_ROOM="2048")
    print("Threshold=32, chunk=4096, room=2048, BBUF=1, code=232 KiB, optimized PSRAM layout retained")
    print("Important: Only enter a benchmark score if the ENTIRE 3D viewport renders correctly.")
    for target in targets:
        print("\n==="+f" promotion target {target}"+" ===")
        input("Press Enter to build and flash (Ctrl+C to cancel)...")
        before={str(p) for p in logs.glob("bb-live-*-console.txt")}
        runenv=env.copy();runenv["BB_REUSE_PROMOTE"]=str(target)
        cmd=["powershell.exe","-NoProfile","-ExecutionPolicy","Bypass","-File",str(runner),
            "-MicroDOS",a.microdos,"-Blitz86",a.blitz,"-Port",a.port,"-Seconds",str(a.seconds)]
        status=subprocess.run(cmd,cwd=str(root),env=runenv)
        new=[p for p in logs.glob("bb-live-*-console.txt") if str(p) not in before]
        new.sort(key=lambda p:p.stat().st_mtime,reverse=True)
        if status.returncode or not new:
            print("Build or capture failed, not recording a result");continue
        log=new[0]
        render=input("Was the full 3D viewport rendered correctly? [y/N]: ").strip().lower() in ("y","yes")
        s=input("Displayed 3DBench score (blank if not completed): ").strip()
        try:score=float(s) if s else ""
        except ValueError:score=""
        got=metrics(log)
        if got["reports"]==0:
            print("WARNING: no JIT reports; counters unavailable")
        row=dict(time=dt.datetime.now().isoformat(timespec="seconds"),target=target,
                 score=score,render_ok="yes" if render else "no",log=str(log),**got)
        exists=out.exists()
        with out.open("a",encoding="utf-8",newline="") as f:
            w=csv.DictWriter(f,fieldnames=FIELDS)
            if not exists:w.writeheader()
            w.writerow(row)
        print("Recorded",row)
        summary(a)
    print("Run complete. Flash the control (32) or validated winner before further work.")


def main():
    ap=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root",default=r"C:\blitzBUS")
    ap.add_argument("--blitz",default=r"C:\blitz86_v2")
    sp=ap.add_subparsers(dest="cmd",required=True)
    for x in ("apply","verify","restore","summary"):sp.add_parser(x)
    r=sp.add_parser("run")
    r.add_argument("--profiles",default="32,1,4,8,32")
    r.add_argument("--microdos",default=r"C:\microDOS")
    r.add_argument("--port",default="COM5")
    r.add_argument("--seconds",type=int,default=180)
    a=ap.parse_args()
    try:
        {"apply":lambda:apply(a),"verify":lambda:verify(a),"restore":lambda:restore(a),
         "summary":lambda:summary(a),"run":lambda:run(a)}[a.cmd]()
    except (RuntimeError, KeyboardInterrupt) as exc:
        print("STOPPED:",exc,file=sys.stderr);sys.exit(1)

if __name__=="__main__":main()
