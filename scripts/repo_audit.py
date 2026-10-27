#!/usr/bin/env python3
"""Read-only blitzBUS Git worktree audit; never opens or writes disk images.

Reports tracked bytes, hash-identical Git index blobs, patch-state bytes,
large tracked assets and working-tree status. Exact duplicates use the index's
Git object IDs; this is not a comparison of unsaved working-tree modifications.
"""
import argparse
import collections
import json
import os
from pathlib import Path
import subprocess
import sys


def git_bytes(root, *args):
    process = subprocess.run(["git", "-C", str(root), *args],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             check=False)
    if process.returncode:
        raise RuntimeError(process.stderr.decode("utf-8", "replace").strip())
    return process.stdout


def audit(root):
    root = Path(root).resolve()
    rows = []
    for token in git_bytes(root, "ls-files", "--stage", "-z").split(b"\0"):
        if not token:
            continue
        head, name = token.split(b"\t", 1)
        mode, sha, stage = head.decode("ascii").split()
        if stage != "0":
            # Unmerged/conflicted entries are not meaningful duplicates.
            continue
        rel = os.fsdecode(name)
        path = root / rel
        stat_size = path.stat().st_size if path.is_file() else None
        rows.append({"path": rel.replace("\\", "/"), "sha": sha,
                     "size": stat_size, "mode": mode})
    by_sha = collections.defaultdict(list)
    for row in rows:
        by_sha[row["sha"]].append(row)
    duplicates = []
    for files in by_sha.values():
        if len(files) > 1:
            duplicates.append({"sha": files[0]["sha"],
                               "paths": sorted(row["path"] for row in files),
                               "size": files[0]["size"],
                               "repeated_checkout_bytes": (
                                   (len(files)-1) * files[0]["size"]
                                   if files[0]["size"] is not None else None)})
    duplicates.sort(key=lambda x: x["repeated_checkout_bytes"] or 0,
                    reverse=True)
    tracked = sum(row["size"] or 0 for row in rows)
    states = [row for row in rows if row["path"].split("/")[0].startswith((
        ".bb_dos622_", ".bb622_")) and "_state/" in row["path"]]
    disks = [row for row in rows if row["path"].lower().endswith((
        ".img", ".arj", ".hog", ".pig"))]
    changes = git_bytes(root, "status", "--porcelain=v1", "-z").split(b"\0")
    return {"root": str(root), "tracked_files": len(rows),
            "tracked_checkout_bytes": tracked,
            "missing_tracked_files": [r["path"] for r in rows if r["size"] is None],
            "state_files": len(states),
            "state_checkout_bytes": sum(r["size"] or 0 for r in states),
            "large_disk_archive_paths": len(disks),
            "large_disk_archive_bytes": sum(r["size"] or 0 for r in disks),
            "working_tree_has_changes": any(changes),
            "duplicates": duplicates,
            "duplicate_checkout_bytes": sum(
                d["repeated_checkout_bytes"] or 0 for d in duplicates),
            "largest_files": sorted(rows, key=lambda r: r["size"] or 0,
                                    reverse=True)[:15]}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", default=".", help="Git checkout (default: current directory)")
    p.add_argument("--json", action="store_true", help="Output JSON for saving/processing")
    args = p.parse_args()
    try:
        report = audit(args.root)
    except (RuntimeError, OSError) as e:
        print("AUDIT ERROR:", e, file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    print(f"TRACKED: {report['tracked_files']:,} files, "
          f"{report['tracked_checkout_bytes']:,} checkout bytes")
    print(f"ROLLBACK STATES: {report['state_files']:,} files, "
          f"{report['state_checkout_bytes']:,} bytes — KEEP")
    print(f"LARGE DISK/ARCHIVE PATHS: {report['large_disk_archive_paths']:,} "
          f"paths, {report['large_disk_archive_bytes']:,} bytes")
    print(f"EXACT INDEX DUPLICATES: {len(report['duplicates']):,} groups; "
          f"{report['duplicate_checkout_bytes']:,} repeated checkout bytes")
    print("WORKTREE CHANGES:", "YES — inspect git status before cleanup"
          if report["working_tree_has_changes"] else "none")
    if report["missing_tracked_files"]:
        print(f"MISSING TRACKED FILES: {len(report['missing_tracked_files'])} "
              "(sizes/duplicates may be incomplete)")
    print("LARGEST EXACT DUPLICATES:")
    for d in report["duplicates"][:12]:
        print(f"  {d['repeated_checkout_bytes'] or 0:>11,} B: " + " = ".join(d["paths"]))
    print("No files changed. Git duplicate groups reflect INDEX blobs, "
          "not necessarily unsaved worktree contents.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
