#!/usr/bin/env python3
"""Turn [bb386-pcs-top] PC samples from a console log into a function profile.

  python scripts\\bb386_pcs_symbols.py LOG [--elf ELF] [--nm NM] [--last N] [--top 40]

LOG   console log (logs\\bb-live-...-console.txt)
ELF   firmware (default C:\\microDOS\\build-pico\\out\\blitzbus_pico_b86_dos.elf)
NM    arm-none-eabi-nm (default: searched under ~/.pico-sdk/toolchain, then PATH)
--last N   only the last N dumps (default: all)

Prints functions ranked by samples, with their region (flash = runs from XIP,
SRAM = already in RAM). Addresses inside large data objects (e.g. the
real-mode JIT code buffer) show that object's name.
"""
import argparse, bisect, glob, os, re, shutil, subprocess, sys
from collections import Counter

def find_nm(explicit):
    if explicit: return explicit
    home = os.path.expanduser("~")
    for pat in (os.path.join(home, ".pico-sdk", "toolchain", "*", "bin", "arm-none-eabi-nm*"),
                os.path.join(home, ".pico-sdk", "toolchain", "*", "*", "bin", "arm-none-eabi-nm*")):
        hits = sorted(glob.glob(pat))
        if hits: return hits[-1]
    return shutil.which("arm-none-eabi-nm") or "arm-none-eabi-nm"

def load_symbols(nm, elf):
    out = subprocess.run([nm, "-n", "-S", "-C", "--defined-only", elf], capture_output=True, text=True, check=True).stdout
    syms = []
    for line in out.splitlines():
        p = line.split(None, 3)
        if len(p) == 4:
            addr, size, typ, name = int(p[0], 16), int(p[1], 16), p[2], p[3]
        elif len(p) == 3:
            addr, size, typ, name = int(p[0], 16), 0, p[1], p[2]
        else:
            continue
        if typ in "tTwWdDbBrR" and addr:
            syms.append((addr & ~1, size, name))
    syms.sort()
    return syms

def lookup(syms, starts, pc):
    """function containing pc: a sized symbol that covers it, a zero-size label
    (veneer, asm entry) only right at its address; else '?' with the nearest name"""
    i = bisect.bisect_right(starts, pc) - 1
    near = None
    j = i
    while j >= 0 and pc - syms[j][0] <= 0x40000:
        a, sz, name = syms[j]
        if sz and pc < a + sz: return name
        if not sz and pc - a < 16: return name
        if near is None: near = (name, pc - a)
        j -= 1
    return "? (%s+0x%X)" % near if near else "?"

def region(pc):
    if 0x10000000 <= pc < 0x11000000: return "flash"
    if 0x20000000 <= pc < 0x20082000: return "SRAM"
    return "other"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("--elf", default=r"C:\microDOS\build-pico\out\blitzbus_pico_b86_dos.elf")
    ap.add_argument("--nm")
    ap.add_argument("--last", type=int, default=0)
    ap.add_argument("--top", type=int, default=40)
    a = ap.parse_args()
    dumps, callers = [], []
    with open(a.log, errors="replace") as f:
        for line in f:
            if line.startswith("[bb386-pcs-top]") or line.startswith("[bb386-pcs-callers]"):
                row = [(int(x.split(":")[0], 16), int(x.split(":")[1])) for x in line.split()[1:] if ":" in x]
                (dumps if line.startswith("[bb386-pcs-top]") else callers).append(row)
    if not dumps: raise SystemExit("no [bb386-pcs-top] lines in " + a.log)
    if a.last: dumps, callers = dumps[-a.last:], callers[-a.last:]
    nm = find_nm(a.nm)
    syms = load_symbols(nm, a.elf)
    starts = [s[0] for s in syms]
    per_fn, per_region = Counter(), Counter()
    total = 0
    for d in dumps:
        for pc, n in d:
            fn = lookup(syms, starts, pc)
            per_fn[(fn, region(pc))] += n
            per_region[region(pc)] += n
            total += n
    print("%d dumps, %d samples in the listed PCs (%s)" % (len(dumps), total,
          ", ".join("%s %.1f%%" % (r, 100.0 * n / total) for r, n in per_region.most_common())))
    print("%7s %6s  %-6s %s" % ("samples", "share", "where", "function"))
    for (fn, reg), n in per_fn.most_common(a.top):
        print("%7d %5.1f%%  %-6s %s" % (n, 100.0 * n / total, reg, fn))
    if callers:
        per_c, ctot = Counter(), 0
        for d in callers:
            for pc, n in d:
                per_c[(lookup(syms, starts, pc), region(pc))] += n; ctot += n
        print()
        print("callers (LR of the sampled C code; who calls the leaf functions above)")
        print("%7s %6s  %-6s %s" % ("samples", "share", "where", "function"))
        for (fn, reg), n in per_c.most_common(a.top):
            print("%7d %5.1f%%  %-6s %s" % (n, 100.0 * n / ctot, reg, fn))
    return 0

if __name__ == "__main__":
    sys.exit(main())
