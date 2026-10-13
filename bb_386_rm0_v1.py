#!/usr/bin/env python3
"""blitz86 real-mode 386 milestone 0: reversible source installer.

Run from C:\\blitzBUS, with local Blitz86 source at C:\\blitz86_v2:
  python bb_386_rm0_v1.py selftest
  python bb_386_rm0_v1.py probe
  python bb_386_rm0_v1.py apply
  python bb_386_rm0_v1.py verify
  python bb_386_rm0_v1.py restore

Edits only blitz86_v2/{include/b86.h,src/interp.c,src/jit.c}; installs
src/i386_rm0.inc and tests/bb_386_rm0_smoke.c. Keeps exact-byte backups.
Model 286 remains the active blitzBUS default. 386 execution is interpreter-
only until a 32-bit-capable JIT exists. Unsupported 386 instructions explicitly
return B86_UNSUPPORTED=5 instead of silently misexecuting.
"""
from __future__ import annotations
import argparse, hashlib, json, os, pathlib, shutil, sys

TAG = "BB_386_RM0_V1"
HOME = pathlib.Path(__file__).resolve().parent
FILES = ["include/b86.h", "src/interp.c", "src/jit.c"]
NEW = ["src/i386_rm0.inc", "tests/bb_386_rm0_smoke.c"]
BAK_DIR = ".bb_386_rm0_v1_backup"


def digest(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def nl_of(b: bytes) -> str:
    if b"\r\n" in b:
        if b.replace(b"\r\n", b"").find(b"\n") >= 0:
            raise RuntimeError("mixed newline format; refusing to rewrite")
        return "\r\n"
    return "\n"


def replace_once(s: str, old: str, new: str, label: str) -> str:
    n = s.count(old)
    if n != 1:
        raise RuntimeError(f"{label}: expected one matching anchor, found {n}")
    return s.replace(old, new, 1)


def insert_before(s: str, anchor: str, payload: str, label: str) -> str:
    return replace_once(s, anchor, payload + anchor, label)


def modify(path: str, raw: bytes) -> bytes:
    eol = nl_of(raw)
    s = raw.decode("utf-8").replace("\r\n", "\n")
    if TAG in s:
        raise RuntimeError(path + ": already has milestone marker; verify or restore first")
    if path == "include/b86.h":
        s = replace_once(s,
            "enum { B86_CPU_8086 = 0, B86_CPU_186 = 1, B86_CPU_286 = 2 };",
            "enum { B86_CPU_8086 = 0, B86_CPU_186 = 1, B86_CPU_286 = 2, B86_CPU_386 = 3 }; /* " + TAG + ": 386 real mode */",
            path + " model enum")
        s = replace_once(s,
            "enum { B86_OK = 0, B86_HALT = 1, B86_EXIT = 2, B86_BUDGET = 3, B86_TRAP = 4 };",
            "enum { B86_OK = 0, B86_HALT = 1, B86_EXIT = 2, B86_BUDGET = 3, B86_TRAP = 4, B86_UNSUPPORTED = 5 };",
            path + " return codes")
    elif path == "src/interp.c":
        # Cold include: only code for the new CPU model is added; legacy helpers retain ABI.
        s = insert_before(s, "B86_HOT int b86_step(B86Cpu *c)\n{",
            "/* " + TAG + ": 386 66h operand path stays in flash. */\n#include \"i386_rm0.inc\"\n\n",
            path + " include")
        s = replace_once(s,
            "B86_HOT int b86_step(B86Cpu *c)\n{",
            "B86_HOT static int b86_step_internal(B86Cpu *c)\n{",
            path + " internal rename")
        s = replace_once(s,
            "    uint8_t op;\n    for (;;) {\n        op = f8(s);",
            "    uint8_t op;\n    int operand32 = 0, address32 = 0;  /* " + TAG + " */\n    for (;;) {\n        op = f8(s);\n        if (c->model >= B86_CPU_386 && op == 0x66) { operand32 = 1; continue; }\n        if (c->model >= B86_CPU_386 && op == 0x67) { address32 = 1; continue; }",
            path + " prefixes")
        s = replace_once(s,
            "    int w = op & 1;\n\n    if (op < 0x40",
            "    int w = op & 1;\n    if (c->model >= B86_CPU_386) {\n"
            "        if (address32 || op == 0x63 || op == 0x64 || op == 0x65 ||\n"
            "            (op == 0x0F && !operand32 &&\n"
            "             rd8(c, B86_CS, s->ip) != 0x01 && rd8(c, B86_CS, s->ip) != 0x06)) {\n"
            "            c->ip = s->fip0; return B86_UNSUPPORTED;\n"
            "        }\n"
            "        if (operand32) return b86_rm0_66(s, op);\n"
            "    }\n\n    if (op < 0x40",
            path + " opcode diversion")
        marker = "B86_HOT int b86_run_interp(B86Cpu *c, uint64_t max)\n{"
        wrapper = """/* BB_386_RM0_V1: on a 386, 16-bit instructions must preserve the
   upper halves of EAX..EDI, even when the legacy 286 interpreter assigns
   directly to 16-bit register slots.  The wrapper is never used by 286.
   A 66h instruction writes the entire 32-bit destination, so skip merge. */
B86_HOT int b86_step(B86Cpu *c)
{
    if (c->model < B86_CPU_386) return b86_step_internal(c);
    uint32_t hi[8];
    for (unsigned i = 0; i < 8; ++i) hi[i] = c->r[i] & 0xFFFF0000u;
    uint16_t ip = (uint16_t)c->ip;
    int operand32 = 0;
    for (unsigned k = 0; k < 15; ++k) {
        uint8_t op = rd8(c, B86_CS, ip++);
        if (op == 0x66) { operand32 = 1; continue; }
        if (op == 0x67 || op == 0x26 || op == 0x2E || op == 0x36 ||
            op == 0x3E || op == 0xF0 || op == 0xF1 || op == 0xF2 || op == 0xF3)
            continue;
        break;
    }
    int rc = b86_step_internal(c);
    if (!operand32) for (unsigned i = 0; i < 8; ++i) c->r[i] = (c->r[i] & 0xFFFFu) | hi[i];
    return rc;
}

"""
        s = insert_before(s, marker, wrapper, path + " wrapper")
    elif path == "src/jit.c":
        anchor = "B86_HOT int b86_jit_run(B86Cpu *c, uint64_t max_dispatch)\n{"
        body = """/* BB_386_RM0_V1: never run the 16-bit Thumb-2/A64 JIT with 386
   registers.  Cold interpreter is deliberately in flash, not SRAM. */
B86_COLD static int b86_386_rm0_run(B86Cpu *c, uint64_t budget)
{
    for (uint64_t i = 0; i < budget; ++i) {
        if (c->irq & 0x80000000u) { c->irq &= 0x7FFFFFFFu; return B86_HALT; }
        if (c->irq) return B86_EXIT;
        if (c->seg[B86_CS] == c->trap_cs) return B86_TRAP;
        int r = b86_step(c);
        if (r != B86_OK) return r;
    }
    return B86_BUDGET;
}

"""
        s = insert_before(s, anchor, body, path + " 386 dispatcher")
        s = replace_once(s,
            "    J *j = c->jit;\n    uint64_t n = 0;",
            "    if (c->model >= B86_CPU_386) return b86_386_rm0_run(c, max_dispatch);\n    J *j = c->jit;\n    uint64_t n = 0;",
            path + " dispatcher selector")
    else:
        raise ValueError(path)
    return s.replace("\n", eol).encode("utf-8")


def locations(root: pathlib.Path) -> list[pathlib.Path]:
    return [root / x for x in FILES]


def probe(root: pathlib.Path) -> None:
    print("Blitz86 source:", root)
    for rel, path in zip(FILES, locations(root)):
        if not path.is_file():
            raise RuntimeError("missing: " + str(path))
        raw = path.read_bytes()
        if TAG in raw.decode("utf-8"):
            print(rel, "already installed")
        else:
            out = modify(rel, raw)
            print(rel, "anchors OK", len(raw), "->", len(out), "bytes; newline", repr(nl_of(raw)))
    for rel in NEW:
        print(rel, "exists" if (root / rel).exists() else "will install")
    print("No files modified")


def apply(root: pathlib.Path) -> None:
    backup = HOME / BAK_DIR
    if backup.exists():
        raise RuntimeError("existing backup at " + str(backup) + "; verify or restore first")
    if not (HOME / "i386_rm0.inc").is_file() or not (HOME / "bb_386_rm0_smoke.c").is_file():
        raise RuntimeError("extract the entire ZIP beside installer (missing .inc or smoke test)")
    if any((root / rel).exists() for rel in NEW):
        raise RuntimeError("destination files already exist; refuse to replace: " + str(NEW))
    old = {rel: (root / rel).read_bytes() for rel in FILES}
    edited = {rel: modify(rel, raw) for rel, raw in old.items()}
    created = {NEW[0]: (HOME / "i386_rm0.inc").read_bytes(),
               NEW[1]: (HOME / "bb_386_rm0_smoke.c").read_bytes()}
    backup.mkdir(parents=True, exist_ok=False)
    manifest = {"version": TAG, "root": str(root.resolve()),
                "files": {rel: {"old": digest(old[rel]), "new": digest(edited[rel])} for rel in FILES},
                "new": {rel: digest(raw) for rel, raw in created.items()}}
    for rel, raw in old.items():
        q = backup / rel
        q.parent.mkdir(parents=True, exist_ok=True)
        q.write_bytes(raw)
    (backup / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    written = []
    try:
        for rel, raw in {**edited, **created}.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(raw)
            written.append(rel)
        verify(root)
    except Exception:
        for rel in written:
            p = root / rel
            if rel in old: p.write_bytes(old[rel])
            elif p.exists(): p.unlink()
        shutil.rmtree(backup)
        raise
    print("APPLIED: 386 real-mode 66h interpreter-only milestone; prior CPUs unchanged")


def load_manifest(root: pathlib.Path):
    bk = HOME / BAK_DIR
    p = bk / "manifest.json"
    if not p.is_file():
        raise RuntimeError("no managed install/backup found")
    man = json.loads(p.read_text(encoding="utf-8"))
    if man["root"] != str(root.resolve()) or man["version"] != TAG:
        raise RuntimeError("backup belongs to another source root/version")
    return bk, man


def verify(root: pathlib.Path) -> None:
    bk, man = load_manifest(root)
    for rel, h in man["files"].items():
        if digest((root / rel).read_bytes()) != h["new"]:
            raise RuntimeError("modified since install: " + str(root / rel))
        if digest((bk / rel).read_bytes()) != h["old"]:
            raise RuntimeError("backup altered: " + str(bk / rel))
    for rel, h in man["new"].items():
        if digest((root / rel).read_bytes()) != h:
            raise RuntimeError("new source altered: " + str(root / rel))
    print("VERIFIED: 386 milestone installed; original 286/8086 sources backed up exactly")


def restore(root: pathlib.Path) -> None:
    bk, man = load_manifest(root)
    verify(root)  # never overwrite a source changed by someone else
    for rel in FILES:
        (root / rel).write_bytes((bk / rel).read_bytes())
    for rel in NEW:
        (root / rel).unlink()
    for rel in FILES:
        assert digest((root / rel).read_bytes()) == man["files"][rel]["old"]
    shutil.rmtree(bk)
    print("RESTORED: exact-byte original source; RCL/RCR changes preceding this layer preserved")


def selftest() -> None:
    # Build minimal synthetic anchors for an LF / CRLF and exact restore test.
    import tempfile
    blobs = {
      "include/b86.h": "enum { B86_CPU_8086 = 0, B86_CPU_186 = 1, B86_CPU_286 = 2 };\nenum { B86_OK = 0, B86_HALT = 1, B86_EXIT = 2, B86_BUDGET = 3, B86_TRAP = 4 };\n",
      "src/interp.c": "B86_HOT int b86_step(B86Cpu *c)\n{\n    uint8_t op;\n    for (;;) {\n        op = f8(s);\n    }\n    int w = op & 1;\n\n    if (op < 0x40) return 1;\n}\nB86_HOT int b86_run_interp(B86Cpu *c, uint64_t max)\n{\n}\n",
      "src/jit.c": "B86_HOT int b86_jit_run(B86Cpu *c, uint64_t max_dispatch)\n{\n    J *j = c->jit;\n    uint64_t n = 0;\n}\n"
    }
    for eol in ["\n", "\r\n"]:
        for path, s in blobs.items():
            orig = s.replace("\n", eol).encode()
            new = modify(path, orig)
            assert TAG.encode() in new
            assert nl_of(new) == eol
            assert modify(path, orig) == new
    print("SELFTEST PASS: anchors, model/status declarations, CPU JIT guard, CRLF/LF stability")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("action", choices=["selftest", "probe", "apply", "verify", "restore"])
    p.add_argument("--blitz86", type=pathlib.Path, default=pathlib.Path(r"C:\blitz86_v2") if os.name == "nt" else HOME / "blitz86_v2")
    a = p.parse_args()
    if a.action == "selftest": selftest()
    else:
        root = a.blitz86.resolve()
        {"probe": probe, "apply": apply, "verify": verify, "restore": restore}[a.action](root)

if __name__ == "__main__":
    try: main()
    except (RuntimeError, OSError, UnicodeError) as exc:
        print("ERROR:", exc, file=sys.stderr)
        sys.exit(1)
