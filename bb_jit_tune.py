#!/usr/bin/env python3
"""blitzBUS hot-threshold sweep / eviction telemetry analysis.
Run on Windows from C:\blitzBUS. No source files are modified.
Commands:
  python bb_jit_tune.py run --thresholds 64,32,96,16,128
  python bb_jit_tune.py analyze --log C:\blitzBUS\logs\bb-live-...-console.txt
  python bb_jit_tune.py summary
"""
import argparse,csv,datetime as dt,os,re,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
RESULTS=ROOT/"logs"/"bb-jit-threshold-results.csv"
FIELDS=["timestamp","threshold","score","log","meta_used","meta_failures","evictions","evicted_blocks","unchains","retries","jit_reports","xip_miss","native_miss"]
def analyze(log):
    data=Path(log).read_text(encoding="utf-8",errors="replace")
    jit=re.findall(r"(?m)^\[bb-jit\][^\r\n]*",data)
    def count(lines,key):
        return sum(int(m.group(1)) for line in lines if (m:=re.search(r"(?<![\w-])"+re.escape(key)+r"=(\d+)",line)))
    meta=re.findall(r"(?m)^\[bb-meta-usage\][^\r\n]*",data)
    def last(key):
        found=re.findall(r"\b"+re.escape(key)+r"=(\d+)",meta[-1]) if meta else []
        return int(found[-1]) if found else ""
    return dict(meta_used=last("used"),meta_failures=last("failures"),
      evictions=count(jit,"evictions"),evicted_blocks=count(jit,"evicted"),
      unchains=count(jit,"unchains"),retries=count(jit,"retries"),jit_reports=len(jit),
      xip_miss=count(jit,"xip-miss"),native_miss=count(jit,"native-miss"))
def summary():
    if not RESULTS.exists():print("No results yet:",RESULTS);return
    rows=list(csv.DictReader(RESULTS.open(newline="",encoding="utf-8")))
    for threshold in sorted(set(r["threshold"] for r in rows),key=int):
        x=[r for r in rows if r["threshold"]==threshold]
        scores=sorted(float(r["score"]) for r in x if r["score"])
        if scores:
            median=scores[len(scores)//2] if len(scores)%2 else (scores[len(scores)//2-1]+scores[len(scores)//2])/2
        else:median=None
        print(f"threshold={threshold:>3s} runs={len(x)} scores={scores} median={median} "
              f"evictions={[r['evictions'] for r in x]} unchains={[r['unchains'] for r in x]}")
def main():
    ap=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    sub=ap.add_subparsers(dest="mode",required=True)
    run=sub.add_parser("run")
    run.add_argument("--thresholds",default="64,32,96,16,128")
    run.add_argument("--seconds",type=int,default=180)
    run.add_argument("--port",default="COM5")
    run.add_argument("--microdos",default=r"C:\microDOS")
    run.add_argument("--blitz86",default=r"C:\blitz86_v2")
    analyze_p=sub.add_parser("analyze");analyze_p.add_argument("--log",required=True)
    sub.add_parser("summary")
    a=ap.parse_args()
    if a.mode=="analyze":
        print(analyze(a.log));return
    if a.mode=="summary":summary();return
    thresholds=[int(x.strip()) for x in a.thresholds.split(",")]
    if not thresholds or any(t<0 or t>255 for t in thresholds):ap.error("threshold must be 0..255")
    runner=ROOT/"scripts"/"bb_live_run.ps1"
    if not runner.exists():ap.error("Run from C:\\blitzBUS with scripts/bb_live_run.ps1 present")
    logs=ROOT/"logs";logs.mkdir(exist_ok=True)
    base=os.environ.copy()
    base.update(BB_BBUF="1",BB_CODE_KB="232",BB_CPU="286",BB_SD_BOOT="1",
                BB_LCD_PERI_HZ="150000000",BB_LCD_SPI_HZ="75000000",BB_LCD_LACE="1",
                BB_PAGED="1")
    print("Preserved: SRAM bbuf=64KiB, code=232KiB, CPU=286, LCD 75MHz, PSRAM layout unchanged.")
    print("Run the same 3DBench workload once per firmware flash; Ctrl+X ends each interactive session.")
    print("Do not compare timings while verbose logging differs between runs.")
    for t in thresholds:
        print("\n"+"="*65+"\nTHRESHOLD",t)
        input("Press Enter to build and flash this firmware (Ctrl+C to stop)...")
        before={str(p) for p in logs.glob("bb-live-*-console.txt")}
        env=base.copy();env["BB_HOT_THRESHOLD"]=str(t)
        cmd=["powershell.exe","-NoProfile","-ExecutionPolicy","Bypass","-File",str(runner),
             "-MicroDOS",a.microdos,"-Blitz86",a.blitz86,"-Port",a.port,
             "-Seconds",str(a.seconds)]
        result=subprocess.run(cmd,cwd=str(ROOT),env=env)
        new=[p for p in logs.glob("bb-live-*-console.txt") if str(p) not in before]
        new.sort(key=lambda x:x.stat().st_mtime,reverse=True)
        if result.returncode or not new:
            print("Run failed or no console log; no row saved.",file=sys.stderr)
            continue
        log=new[0]
        metrics=analyze(log)
        raw=input("Enter displayed 3DBench score (blank if not completed): ").strip()
        try:score=float(raw) if raw else ""
        except ValueError:
            print("Invalid score, recording as blank.");score=""
        row=dict(timestamp=dt.datetime.now().isoformat(timespec="seconds"),
                 threshold=t,score=score,log=str(log),**metrics)
        exists=RESULTS.exists()
        with RESULTS.open("a",newline="",encoding="utf-8") as f:
            writer=csv.DictWriter(f,fieldnames=FIELDS)
            if not exists:writer.writeheader()
            writer.writerow(row)
        print("Recorded",row)
        summary()
    print("\nAll requested runs complete. For meaningful comparisons, repeat promising thresholds 2-3 times.")
if __name__=="__main__":
    main()
