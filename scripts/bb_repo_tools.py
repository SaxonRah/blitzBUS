#!/usr/bin/env python3
"""Discover and run historical blitzBUS Python tools from the project root."""
from pathlib import Path
import argparse
import subprocess
import sys

def main():
    root=Path(__file__).resolve().parents[1]
    ap=argparse.ArgumentParser(description=__doc__)
    sub=ap.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    p=sub.add_parser("run")
    p.add_argument("tool")
    p.add_argument("args", nargs=argparse.REMAINDER)
    a=ap.parse_args()
    found={p.name:p for base in (root,root/"tools"/"legacy"/"log-analysis") if base.is_dir() for p in base.glob("*.py")}
    # Print ambiguous/duplicated names as an error rather than silently picking one.
    duplicates={p.name for p in root.glob("*.py") if (root/"tools"/"legacy"/"log-analysis"/p.name).exists()}
    if a.command=="list":
        for name in sorted(found):
            print(f"{name:48} {found[name].relative_to(root)}")
        print(f"Total: {len(found)} Python tools")
        return 0
    if a.tool in duplicates:raise SystemExit("Ambiguous basename: "+a.tool)
    path=found.get(a.tool)
    if not path or path.name!=a.tool:raise SystemExit("Unknown tool; use list")
    return subprocess.call([sys.executable,str(path),*a.args],cwd=root)

if __name__=="__main__":sys.exit(main())
