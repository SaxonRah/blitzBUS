#!/usr/bin/env python3
"""blitz86 80386 RM1: reversible 67h/SIB/66h+67h source-file installer.

This is a *layer* above bb_386_rm0_v1.py. Keep the RM0 backup intact.
Actions: selftest, probe, apply, verify, restore.

Run from C:\\blitzBUS:
  python .\\bb_386_rm1_v1.py selftest
  python .\\bb_386_rm1_v1.py probe
  python .\\bb_386_rm1_v1.py apply
  python .\\bb_386_rm1_v1.py verify

Edits C:\\blitz86_v2\\src\\interp.c, tests\\bb_386_rm0_smoke.c;
adds src\\i386_rm1.inc and tests\\bb_386_rm1_smoke.c.
The old 8086/186/286 JIT/Thumb-2 source is not changed.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import pathlib
import shutil
import sys
import tempfile

TAG = "BB_386_RM1_V1"
ROOT = pathlib.Path(__file__).resolve().parent
BACKUP = ROOT / ".bb_386_rm1_v1_backup"
EDITS = ["src/interp.c", "tests/bb_386_rm0_smoke.c"]
NEW = {"src/i386_rm1.inc": "i386_rm1.inc", "tests/bb_386_rm1_smoke.c": "bb_386_rm1_smoke.c"}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def newline(data: bytes) -> str:
    if b"\r\n" in data:
        if b"\n" in data.replace(b"\r\n", b""):
            raise ValueError("mixed line endings")
        return "\r\n"
    return "\n"


def once(src: str, orig: str, replacement: str, label: str) -> str:
    count = src.count(orig)
    if count != 1:
        raise ValueError(f"{label}: expected 1 matching anchor, found {count}")
    return src.replace(orig, replacement, 1)


def transform(rel: str, source: bytes) -> bytes:
    ending = newline(source)
    s = source.decode("utf-8").replace("\r\n", "\n")
    if TAG in s:
        raise ValueError(f"{rel}: RM1 already installed")
    if rel == "src/interp.c":
        if "BB_386_RM0_V1" not in s:
            raise ValueError("RM0 must be installed before RM1")
        s = once(s, '#include "i386_rm0.inc"\n',
            '#include "i386_rm0.inc"\n/* BB_386_RM1_V1: 67h address-size interpreter, flash only. */\n#include "i386_rm1.inc"\n',
            "RM0 include")
        s = once(s,
            "        if (address32 || op == 0x63 || op == 0x64 || op == 0x65 ||",
            "        if (address32) return b86_rm1_67(s, op, operand32); /* 67h with optional 66h */\n"
            "        if (op == 0x63 || op == 0x64 || op == 0x65 ||",
            "67h diversion")
    elif rel == "tests/bb_386_rm0_smoke.c":
        s = once(s,
            '    chk("67h explicit unsupported", b86_step(&cpu), B86_UNSUPPORTED);\n'
            '    chk("unsupported leaves IP", cpu.ip, 0u);',
            '    chk("67h 32-bit EA recognized", b86_step(&cpu), B86_OK);\n'
            '    chk("67h advances instruction", cpu.ip, 3u);\n'
            '    /* BB_386_RM1_V1: this was an unsupported case in RM0. */',
            "RM0 smoke updated assertion")
    else:
        raise ValueError(rel)
    return s.replace("\n", ending).encode("utf-8")


def guard(root: pathlib.Path) -> None:
    if not (root / "src/i386_rm0.inc").exists():
        raise RuntimeError("RM0 is not installed (missing src/i386_rm0.inc)")
    if not (root / "tests/bb_386_rm0_smoke.c").exists():
        raise RuntimeError("RM0 smoke test is missing")
    if not (root / "include/b86.h").exists():
        raise RuntimeError("not a blitz86 source checkout")
    if b"B86_CPU_386" not in (root / "include/b86.h").read_bytes():
        raise RuntimeError("B86_CPU_386 not declared: install RM0 first")


def probe(root: pathlib.Path) -> None:
    guard(root)
    print("Blitz86:", root)
    for rel in EDITS:
        data = (root / rel).read_bytes()
        if TAG.encode() in data:
            print(rel, "already has RM1; run verify")
        else:
            changed = transform(rel, data)
            print(rel, "anchors OK", len(data), "->", len(changed), "bytes", repr(newline(data)))
    for rel in NEW:
        if (root / rel).exists():
            print(rel, "already exists; apply will refuse")
        else:
            print(rel, "will be added")
    print("PROBE PASS: no changes made")


def save_manifest(root: pathlib.Path, originals, edited, created):
    BACKUP.mkdir()
    m = {"tag": TAG, "root": str(root.resolve()),
         "edited": {rel: {"before": sha(originals[rel]), "after": sha(edited[rel])} for rel in EDITS},
         "created": {rel: sha(data) for rel, data in created.items()}}
    for rel, data in originals.items():
        p = BACKUP / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    (BACKUP / "manifest.json").write_text(json.dumps(m, indent=2), encoding="utf-8")


def manifest(root: pathlib.Path):
    fn = BACKUP / "manifest.json"
    if not fn.exists():
        raise RuntimeError("no managed RM1 backup found")
    m = json.loads(fn.read_text(encoding="utf-8"))
    if m.get("tag") != TAG or m.get("root") != str(root.resolve()):
        raise RuntimeError("backup does not match current source root")
    return m


def verify(root: pathlib.Path) -> None:
    m = manifest(root)
    for rel, h in m["edited"].items():
        if not (root / rel).exists() or sha((root / rel).read_bytes()) != h["after"]:
            raise RuntimeError("source modified after RM1 install: " + rel)
        if sha((BACKUP / rel).read_bytes()) != h["before"]:
            raise RuntimeError("RM1 backup altered: " + rel)
    for rel, h in m["created"].items():
        if not (root / rel).exists() or sha((root / rel).read_bytes()) != h:
            raise RuntimeError("RM1 installed file altered: " + rel)
    print("VERIFIED RM1: checked sources and byte-exact rollback backups")


def apply(root: pathlib.Path) -> None:
    guard(root)
    if BACKUP.exists():
        raise RuntimeError("RM1 backup already exists; use verify/restore")
    for rel, name in NEW.items():
        if (root / rel).exists():
            raise RuntimeError("refusing to overwrite: " + rel)
        if not (ROOT / name).exists():
            raise RuntimeError("missing package file: " + name)
    before = {rel: (root / rel).read_bytes() for rel in EDITS}
    after = {rel: transform(rel, raw) for rel, raw in before.items()}
    created = {rel: (ROOT / filename).read_bytes() for rel, filename in NEW.items()}
    save_manifest(root, before, after, created)
    written = []
    try:
        for rel, data in {**after, **created}.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            written.append(rel)
        verify(root)
    except Exception:
        for rel in written:
            p = root / rel
            if rel in before:
                p.write_bytes(before[rel])
            else:
                p.unlink(missing_ok=True)
        shutil.rmtree(BACKUP)
        raise
    print("APPLIED RM1: 67h + 66h/67h 386 real-mode interpreter, no JIT/cache changes")


def restore(root: pathlib.Path) -> None:
    m = manifest(root)
    verify(root)  # refuse to discard edits made after installation
    for rel in EDITS:
        (root / rel).write_bytes((BACKUP / rel).read_bytes())
        if sha((root / rel).read_bytes()) != m["edited"][rel]["before"]:
            raise RuntimeError("unexpected restore mismatch for " + rel)
    for rel in NEW:
        (root / rel).unlink()
    shutil.rmtree(BACKUP)
    print("RESTORED RM1 exactly; RM0 and prior RCL/RCR + eager unchaining preserved")


def selftest() -> None:
    orig = {
        "src/interp.c": "/* BB_386_RM0_V1 */\n#include \"i386_rm0.inc\"\n"
                        "        if (address32 || op == 0x63 || op == 0x64 || op == 0x65 ||\n",
        "tests/bb_386_rm0_smoke.c":
            '    chk("67h explicit unsupported", b86_step(&cpu), B86_UNSUPPORTED);\n'
            '    chk("unsupported leaves IP", cpu.ip, 0u);\n'
    }
    for nl in ["\n", "\r\n"]:
        for rel, data in orig.items():
            before = data.replace("\n", nl).encode()
            out = transform(rel, before)
            assert TAG.encode() in out
            assert newline(out) == nl
            assert transform(rel, before) == out
            assert before != out
    # Mini-transaction in an isolated checkout also verifies backup/restore.
    global ROOT, BACKUP
    old_root, old_backup = ROOT, BACKUP
    with tempfile.TemporaryDirectory() as tmp:
        ROOT = pathlib.Path(tmp)
        BACKUP = ROOT / ".bb_386_rm1_v1_backup"
        source = ROOT / "checkout"
        (source / "src").mkdir(parents=True)
        (source / "tests").mkdir()
        (source / "include").mkdir()
        (source / "src/i386_rm0.inc").write_text("RM0")
        (source / "include/b86.h").write_text("B86_CPU_386")
        for rel, data in orig.items():
            (source / rel).write_text(data)
        (ROOT / "i386_rm1.inc").write_bytes((old_root / "i386_rm1.inc").read_bytes())
        (ROOT / "bb_386_rm1_smoke.c").write_bytes((old_root / "bb_386_rm1_smoke.c").read_bytes())
        apply(source)
        restore(source)
        for rel, data in orig.items():
            assert (source / rel).read_text() == data
        assert not (source / "src/i386_rm1.inc").exists()
    ROOT, BACKUP = old_root, old_backup
    print("SELFTEST PASS: exact anchors, LF/CRLF, install/verify/restore, model isolation")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=["selftest", "probe", "apply", "verify", "restore"])
    p.add_argument("--blitz86", type=pathlib.Path, default=(pathlib.Path(r"C:\blitz86_v2") if os.name == "nt" else ROOT / "blitz86_v2"))
    a = p.parse_args()
    if a.action == "selftest":
        selftest()
    else:
        root = a.blitz86.resolve()
        {"probe": probe, "apply": apply, "verify": verify, "restore": restore}[a.action](root)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, UnicodeError) as e:
        print("ERROR:", e, file=sys.stderr)
        sys.exit(1)
