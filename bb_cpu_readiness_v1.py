#!/usr/bin/env python3
r"""blitz86 186/286/386/486 readiness and Pico memory-budget audit.

READ ONLY: scans C:\blitz86_v2, C:\blitzBUS, and optional build logs.
It never changes the source, firmware, DOS image, or SD card.

PowerShell:
  python .\bb_cpu_readiness_v1.py audit
  python .\bb_cpu_readiness_v1.py audit --log C:\blitzBUS\logs\bb-live-...-console.txt
  python .\bb_cpu_readiness_v1.py guard --log C:\blitzBUS\logs\bb-live-...-console.txt
  python .\bb_cpu_readiness_v1.py selftest
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

VERSION = "1.0.0"
DEFAULT_BLITZ = r"C:\blitz86_v2"
DEFAULT_BUS = r"C:\blitzBUS"
RAM_LIMIT = 524288
MIN_HEADROOM = 2048


def parse_regions(log_text: str) -> dict:
    data = {}
    for name in ("FLASH", "PSRAM", "XIP_RAM", "RAM", "SCRATCH_X", "SCRATCH_Y"):
        m = re.search(rf"(?m)^\s*{name}:\s*(\d+)\s+B\s+([^\r\n]+)", log_text)
        if m:
            data[name.lower()] = int(m.group(1))
    return data


def last_line(text: str, label: str) -> str:
    items = re.findall(r"(?m)^\[" + re.escape(label) + r"\][^\r\n]*", text)
    return items[-1] if items else ""


def field(line: str, key: str):
    m = re.search(r"(?<![\w-])"+re.escape(key)+r"=(\d+)", line)
    return int(m.group(1)) if m else None


def slurp(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"Missing source: {path}")
    return path.read_text(encoding="utf-8-sig", errors="replace")


def capability_checks(header: str, interp: str, jit: str):
    def has(pattern, text): return re.search(pattern, text, re.S) is not None
    models = {}
    for model in ("8086", "186", "286", "386", "486"):
        models[model] = has(r"\bB86_CPU_" + model + r"\b\s*(?:=|,|\})", header)
    checks = [
        ("80186 interpreter dispatch", has(r"static\s+int\s+step186\s*\(", interp) and has(r"step186\s*\(s,\s*op", interp)),
        ("80186 PUSHA/POPA", has(r"case\s+0x60\s*:", interp) and has(r"case\s+0x61\s*:", interp)),
        ("80186 BOUND", has(r"case\s+0x62\s*:", interp)),
        ("80186 PUSH immediate", has(r"case\s+0x68\s*:", interp) and has(r"case\s+0x6A\s*:", interp)),
        ("80186 IMUL immediate", has(r"case\s+0x69\s*:\s*case\s+0x6B", interp)),
        ("80186 INS/OUTS", has(r"case\s+0x6C\s*:\s*case\s+0x6D", interp) and has(r"case\s+0x6E\s*:\s*case\s+0x6F", interp)),
        ("80186 shift immediate", has(r"case\s+0xC0\s*:\s*case\s+0xC1", interp)),
        ("80186 ENTER/LEAVE", has(r"case\s+0xC8\s*:\s*\{", interp) and has(r"case\s+0xC9\s*:", interp)),
        ("80286 0F system decoder", has(r"static\s+int\s+step0f\s*\(", interp)),
        ("80286 SGDT/SIDT/LGDT/LIDT", all(x in interp for x in ("SGDT", "SIDT", "LGDT", "LIDT"))),
        ("80286 SMSW/LMSW/CLTS", all(x in interp for x in ("SMSW", "LMSW", "CLTS"))),
        ("80286 real-mode fault distinctions", "DE_IP(s)" in interp and "b86_interrupt(c, 6)" in interp),
        ("native 186 PUSH imm + LEAVE", "x186 == 0xC9" in jit and "d->op = 0xF1" in jit),
        ("native Thumb-2 186 count handling", "B86_CPU_186" in jit and "be_shift_reg" in jit),
        ("80386 CPU model", models["386"]),
        ("80386 operand-size prefix in interpreter fetch", has(r"op\s*==\s*0x66", interp[interp.find("int b86_step("):])),
        ("80386 address-size prefix in interpreter fetch", has(r"op\s*==\s*0x67", interp[interp.find("int b86_step("):])),
        ("80386 extended GPR and segment state", any(k in header for k in ("B86_EAX", "seg_cache[", "seg_limit[", "cr0"))),
        ("80386 32-bit JIT decode", "B86_CPU_386" in jit and ("op_size" in jit or "operand32" in jit)),
        ("80486 CPU model", models["486"]),
    ]
    return models, checks


def analyze(blitz: Path, bus: Path, log: Path | None) -> dict:
    header = slurp(blitz / "include" / "b86.h")
    interp = slurp(blitz / "src" / "interp.c")
    jit = slurp(blitz / "src" / "jit.c")
    models, checks = capability_checks(header, interp, jit)
    r = {"tool_version": VERSION, "timestamp": dt.datetime.now().astimezone().isoformat(),
         "source": {"blitz86": str(blitz), "blitzBUS": str(bus)},
         "models": models,
         "source_indicators": [{"name": n, "present": bool(x)} for n, x in checks],
         "cautions": [
             "Source checks show code paths, not architectural correctness or full ISA support.",
             "Published r53/r54 tests are historical; rerun against the local checkout.",
             "PUSHA/POPA etc. may run through the interpreter even when supported.",
             "286 protected mode is not supported by the reviewed code; 386/486 require new architecture.",
             "The DOS 2.00 environment and ~1.1 MiB guest memory do not meet Descent's published requirements.",
         ]}
    if log:
        if not log.is_file(): raise FileNotFoundError(f"Log not found: {log}")
        txt = slurp(log)
        regions = parse_regions(txt)
        jitline = last_line(txt,"bb-jit")
        reuse = last_line(txt,"bb-reuse")
        meta = last_line(txt,"bb-meta-usage")
        rcx = "RCXTEST PASS 64 / 64" in txt
        test = "T2E CHECKSUM=8642 T2E END" in txt
        r["hardware_log"] = {"path":str(log), "memory_regions":regions,
           "sram_available_bytes": RAM_LIMIT - regions["ram"] if "ram" in regions else None,
           "sram_meets_floor": regions.get("ram",RAM_LIMIT+1) <= RAM_LIMIT - MIN_HEADROOM,
           "last_jit": jitline, "last_reuse":reuse, "last_meta":meta,
           "rcxtest_pass":rcx, "t2e_pass":test,
           "evictions_last_interval":field(jitline,"evictions"),
           "evicted_blocks_last_interval":field(jitline,"evicted"),
           "retranslated_observed":field(reuse,"retranslated"),
           "dead_stub_exits":field(last_line(txt,"bb-exit-hotspot"),"dead-stub")}
    return r


def markdown(r:dict) -> str:
    lines=["# blitz86 CPU readiness and SRAM budget", "", f"Generated: {r['timestamp']}",
    "", "Source tree: `"+r["source"]["blitz86"]+"`", "", "## CPU models", "",
    "| Model | Declared locally |", "|---|---|"]
    for k,v in r["models"].items():lines.append(f"| {k} | {'Yes' if v else 'No'} |")
    lines += ["", "## Code-presence indicators", "",
              "Code-presence is **not** a pass/fail CPU compatibility test.", "",
              "| Indicator | In local source |", "|---|---|"]
    for x in r["source_indicators"]:lines.append(f"| {x['name']} | {'Yes' if x['present'] else 'No'} |")
    if "hardware_log" in r:
        l=r["hardware_log"]
        lines += ["", "## Hardware log", "", "Log: `"+l["path"]+"`", "",
                  "| Metric | Observed |", "|---|---|"]
        for key,val in l["memory_regions"].items():lines.append(f"| {key} bytes | {val:,} |")
        for key in ("sram_available_bytes","evictions_last_interval","evicted_blocks_last_interval","retranslated_observed","dead_stub_exits"):
            lines.append(f"| {key} | {l[key]} |")
        lines += ["", f"SRAM policy: <= {RAM_LIMIT - MIN_HEADROOM:,} bytes used, keeping >= {MIN_HEADROOM:,} bytes linker headroom.",
                  "", "`Sram guard` result: " + ("PASS" if l["sram_meets_floor"] else "FAIL / memory region unknown"), ""]
    lines += ["", "## Recommended order", "",
              "1. Freeze 232 KiB native code-cache and eager unchaining. Keep RCL/RCR native ON.",
              "2. Establish 186/286 historical CPU-vector regression on the local checkout; keep existing real mode correct.",
              "3. Add B86_CPU_386 with 32-bit architectural register/flag/segment state, but do not route code to unimplemented 386 semantics.",
              "4. Implement operand-size/address-size prefixes plus a 386 real-mode interpreter oracle, with differential tests.",
              "5. Implement real protected-mode segmentation, GDT/IDT, interrupts, privilege/fault handling, CR0, then DOS extender interoperability.",
              "6. Expand accessible guest RAM beyond 4 MiB using PSRAM planning, preserve executable SRAM cache, and provide DOS 5+ services.",
              "7. Add 386 JIT lowering behind interpreter parity; then 486-specific differences only as needed.",
              "", "## Limits", ""]
    lines += ["- " + c for c in r["cautions"]]
    return "\n".join(lines)+"\n"


def selftest():
    example='''Memory region         Used Size  Region Size  %age Used
 FLASH: 686820 B 16 MB 4.09%
 PSRAM: 4235296 B 8 MB 50.49%
 RAM: 521860 B 512 KB 99.54%
[bb-jit] evictions=105 evicted=1399 native-ms=8250
[bb-reuse] retranslated=1099
[bb-exit-hotspot] dead-stub=0'''
    p=parse_regions(example)
    assert p['ram']==521860 and p['psram']==4235296
    assert field(last_line(example,'bb-jit'),'evictions')==105
    assert field(last_line(example,'bb-reuse'),'retranslated')==1099
    assert field(last_line(example,'bb-exit-hotspot'),'dead-stub')==0
    assert RAM_LIMIT - p['ram'] == 2428
    fakeh='enum { B86_CPU_8086 = 0, B86_CPU_186 = 1, B86_CPU_286 = 2 };'
    models,checks=capability_checks(fakeh,'','')
    assert models['286'] and not models['386'] and not models['486']
    print('SELFTEST PASS: log parsing, SRAM headroom, enum guards, counters')


def main():
    ap=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('command',nargs='?',choices=('audit','guard','selftest'),default='audit')
    ap.add_argument('--blitz',default=DEFAULT_BLITZ,help='local blitz86_v2 source root')
    ap.add_argument('--bus',default=DEFAULT_BUS,help='local blitzBUS root')
    ap.add_argument('--log',type=Path,help='local console log including linker memory regions (recommended)')
    ap.add_argument('--out',type=Path,help='output Markdown report; default: C:\\blitzBUS\\logs\\cpu-readiness.md')
    a=ap.parse_args()
    if a.command=='selftest': selftest();return 0
    blitz,bus=Path(a.blitz),Path(a.bus)
    report=analyze(blitz,bus,a.log)
    if a.command=='guard':
        if 'hardware_log' not in report or 'ram' not in report['hardware_log']['memory_regions']:
            print('FAIL: memory-region report missing. Pass a complete build+link console log.');return 2
        headroom=report['hardware_log']['sram_available_bytes']
        print(f'SRAM used: {RAM_LIMIT-headroom:,} / {RAM_LIMIT:,} B; headroom: {headroom:,} B; minimum: {MIN_HEADROOM:,} B')
        return 0 if headroom >= MIN_HEADROOM else 1
    out=a.out or bus/'logs'/'cpu-readiness.md'
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(markdown(report),encoding='utf-8')
    js=out.with_suffix('.json')
    js.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('Wrote',out,'and',js)
    for m,v in report['models'].items():print(f'CPU {m}: {"DECLARED" if v else "NOT DECLARED"}')
    if 'hardware_log' in report:
        l=report['hardware_log']
        print('SRAM free:',l['sram_available_bytes'],'bytes; reserve>=',MIN_HEADROOM,'bytes')
    print('This is a static source audit, not a CPU correctness test.')
    return 0

if __name__=='__main__':
    try: sys.exit(main())
    except (FileNotFoundError,PermissionError,ValueError) as e:
        print('ERROR:',e,file=sys.stderr);sys.exit(1)
