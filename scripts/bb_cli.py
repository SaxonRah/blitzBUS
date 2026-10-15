#!/usr/bin/env python3
"""Unified blitzBUS command dispatcher. Does not change emulator internals.

All paths resolve relative to this script, not the shell working directory.
No shell command construction; external commands receive separate argv entries.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


HELP = """blitzBUS unified commands (V1)

Existing commands (unchanged):
  bb.bat install | upgrade | restore | build | run

DOS 6.22:
  bb.bat dos boot [-NoBuild] [-NoFlash] [-Port COM5] [-Seconds 0] [-ConsoleView Screen]
  bb.bat dos verify
  bb.bat dos diagnose [--log PATH] [--tail N]

CPU (read-only synthetic/installer tests, NOT full x86 compatibility tests):
  bb.bat cpu test [--quick]
  bb.bat cpu audit [--blitz PATH] [--log PATH]

Tools:
  bb.bat tools list
  bb.bat tools audit [--json]
  bb.bat tools run FILE.py [tool-arguments...]

Notes:
  - DOS boot uses scripts/bb_live_run_dos622_irqtrial.ps1, which is EXPERIMENTAL.
    It builds/flashes by default. Stop other COM5 owners before starting it.
    Guest IRQ0 one-shot remains OFF until explicitly armed by its separate tool.
  - diagnose, verify, CPU test/audit and tools list/audit do not open COM5.
  - Existing legacy bb.bat commands retain their original implementations.
"""


def execute(args: list[str], *, label: str = "") -> int:
    if label:
        print(f"=== {label} ===", flush=True)
    print("RUN:", subprocess.list2cmdline(args), flush=True)
    try:
        return subprocess.run(args, cwd=ROOT, check=False).returncode
    except FileNotFoundError as exc:
        print(f"ERROR: required executable unavailable: {exc.filename}", file=sys.stderr)
        return 127
    except OSError as exc:
        print(f"ERROR: could not start command: {exc}", file=sys.stderr)
        return 126


def python_script(relative: str, args: list[str], label: str) -> int:
    p = ROOT / relative
    if not p.is_file():
        print(f"ERROR: required file missing: {p}", file=sys.stderr)
        return 2
    return execute([sys.executable, str(p), *args], label=label)


def dos_boot(argv: list[str]) -> int:
    script = ROOT / "scripts" / "bb_live_run_dos622_irqtrial.ps1"
    if not script.is_file():
        print(f"ERROR: DOS 6.22 runner missing: {script}", file=sys.stderr)
        return 2
    # No argument interpretation: the original PowerShell runner validates parameters.
    # Explicit --dry-run is accepted only by our new CLI and never starts anything.
    if "--dry-run" in argv:
        args = [x for x in argv if x != "--dry-run"]
        print("DRY RUN: experimental DOS 6.22 runner; no build, flash, or COM port open")
        print("RUN:", subprocess.list2cmdline([
            "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), *args]))
        return 0
    print("Experimental DOS 6.22 runner. Stop other COM5 users; build/flash enabled unless -NoBuild/-NoFlash.", flush=True)
    return execute(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), *argv], label="DOS 6.22 BOOT")


def dos_verify(argv: list[str]) -> int:
    if argv:
        print("Usage: bb.bat dos verify (no arguments)", file=sys.stderr)
        return 2
    cmds = [
        ("bb622_lineage_verify_v13.py", "DOS 6.22 SHA lineage"),
        ("bb622_irq0_trial_v1.py", "IRQ0 experimental source and rollback", ["verify"]),
    ]
    for row in cmds:
        fname, label = row[:2]
        params = row[2] if len(row) > 2 else ["verify"]
        rc = python_script(fname, params, label)
        if rc:
            print(f"VERIFY FAIL: {label} (exit {rc})", file=sys.stderr)
            return rc
    print("VERIFY PASS: lineage and IRQ0 source/backup state (not guest runtime correctness)")
    return 0


def latest_log() -> Path | None:
    folder = ROOT / "logs"
    if not folder.is_dir():
        return None
    matches = list(folder.glob("bb-live-*-console.txt"))
    return max(matches, key=lambda p: (p.stat().st_mtime_ns, p.name)) if matches else None


def diagnose_text(text: str, tail: int) -> dict[str, list[str]]:
    # Keep only a bounded number of matching lines. No guest/media modification.
    pats = {
        "CPU watchdog": re.compile(r"^\[bb622-watch\]"),
        "IRQ0 trial": re.compile(r"^\[bb622-irqtrial\]"),
        "PIC reads": re.compile(r"^\[bb622-picprobe\]"),
        "Disk/media": re.compile(r"^\[(?:bb-sd-b|bb622-swap|bb622-bmedia|bb622-hddv2)\]"),
        "Faults": re.compile(r"^\[(?:bb-v42-diag|bb-v51-fault|EMU ALERT)\]|HardFault|HARDFAULT|guest stopped", re.I),
    }
    found: dict[str, list[str]] = {k: [] for k in pats}
    for line in text.splitlines():
        for k, expr in pats.items():
            if expr.search(line):
                s = found[k]
                s.append(line[:700])
                if len(s) > tail:
                    del s[0]
    return found


def dos_diagnose(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="bb.bat dos diagnose", description="Read latest DOS log; no COM/guest changes")
    p.add_argument("--log", type=Path)
    p.add_argument("--tail", type=int, default=5)
    args = p.parse_args(argv)
    if not 1 <= args.tail <= 100:
        p.error("--tail must be from 1 to 100")
    target = args.log if args.log else latest_log()
    if target is None or not target.is_file():
        print("ERROR: no DOS console log found; use --log PATH or run a DOS session", file=sys.stderr)
        return 2
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"ERROR: cannot read {target}: {exc}", file=sys.stderr)
        return 2
    print(f"DOS LOG: {target} ({len(content):,} characters)")
    sections = diagnose_text(content, args.tail)
    for name, lines in sections.items():
        print(f"\n=== {name}: {len(lines)} recent samples ===")
        for line in lines:
            print(line)
        if not lines:
            print("(none observed)")
    last_watch = sections["CPU watchdog"][-1] if sections["CPU watchdog"] else ""
    if "cs:ip=0000:0000" in last_watch:
        print("\nWARNING: Last sample executes at 0000:0000; possible invalid IRQ return/control flow.")
    if "[bb622-irqtrial] DELIVERED" in content:
        print("\nIRQ0 was delivered in this log; delivery alone does not prove IRET integrity.")
    print("\nRead-only diagnostic complete. No COM5 access or disk changes.")
    return 0


def cpu_test(argv: list[str]) -> int:
    if argv not in ([], ["--quick"]):
        print("Usage: bb.bat cpu test [--quick]", file=sys.stderr)
        return 2
    quick = bool(argv)
    tests = ["bb_cpu_readiness_v1.py"] if quick else [
        "bb_cpu_readiness_v1.py", "bb_386_rm0_v1.py", "bb_386_rm1_v1.py",
        "bb_386_rm2_v1.py", "bb_386_rm3_v1.py", "bb_386_pm0_v1.py"
    ]
    print("CPU TOOL SELFTESTS: validating script parsers/installers using synthetic fixtures.")
    print("NOT a compiled CPU smoke suite and NOT a DOS/386 compatibility certification.")
    for filename in tests:
        rc = python_script(filename, ["selftest"], filename)
        if rc:
            print(f"CPU TEST FAIL: {filename} (exit {rc})", file=sys.stderr)
            return rc
    print(f"CPU TOOL SELFTEST PASS: {len(tests)} tools; no firmware or disk change")
    return 0


def cpu_audit(argv: list[str]) -> int:
    p=argparse.ArgumentParser(prog="bb.bat cpu audit", description="Read-only x86 source capability audit")
    p.add_argument("--blitz", default=r"C:\blitz86_v2")
    p.add_argument("--log")
    a=p.parse_args(argv)
    params=["audit", "--blitz", a.blitz, "--bus", str(ROOT)]
    if a.log:
        params += ["--log",a.log]
    return python_script("bb_cpu_readiness_v1.py",params,"CPU source readiness (indicators only)")


def tools(argv: list[str]) -> int:
    if not argv:
        print("Usage: bb.bat tools list | audit [--json] | run TOOL.py [args...]", file=sys.stderr)
        return 2
    verb,more=argv[0],argv[1:]
    if verb=="list":
        if more:
            print("Usage: bb.bat tools list", file=sys.stderr)
            return 2
        return python_script("scripts/bb_repo_tools.py",["list"],"Available Python tools")
    if verb=="audit":
        if more not in ([],["--json"]):
            print("Usage: bb.bat tools audit [--json]", file=sys.stderr)
            return 2
        return python_script("scripts/repo_audit.py",["--root",str(ROOT),*more],"Git repository audit (read-only)")
    if verb=="run":
        if not more or not more[0].endswith(".py"):
            print("Usage: bb.bat tools run FILE.py [args...]",file=sys.stderr)
            return 2
        return python_script("scripts/bb_repo_tools.py",["run",*more],"Run registered tool")
    print("Unknown tools subcommand: "+verb, file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args or args[0].lower() in ("help","-h","--help","/?"):
        print(HELP)
        return 0
    if len(args)<2:
        print(HELP)
        return 2
    group,verb = args[0].lower(),args[1].lower()
    rest=args[2:]
    if group=="dos":
        return {"boot":dos_boot, "verify":dos_verify,"diagnose":dos_diagnose}.get(verb,lambda _:(print(HELP),2)[1])(rest)
    if group=="cpu":
        return {"test":cpu_test,"audit":cpu_audit}.get(verb,lambda _:(print(HELP),2)[1])(rest)
    if group=="tools":
        return tools(args[1:])
    print(HELP)
    return 2


if __name__=="__main__":
    raise SystemExit(main())
