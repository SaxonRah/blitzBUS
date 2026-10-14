#!/usr/bin/env python3
"""blitzBUS DOS 6.22 KEYB 122-key probe (INT 16h/AH=A2h) repair.

Reversible byte-exact local installer. This script does NOT apply Git patches,
modify boot media, or touch the DOS2 fallback. Usage in C:\\blitzBUS:
    python bb_dos622_keyba2_v1.py selftest
    python bb_dos622_keyba2_v1.py probe
    python bb_dos622_keyba2_v1.py apply
    python bb_dos622_keyba2_v1.py verify
    python bb_dos622_keyba2_v1.py restore

Precondition: the exact 2026-10-14 local source SHA256 prefix from the handoff.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
SOURCE = "src/bb_live.c"
TAG = "BB_DOS622_KEYBA2_V1"
STATE_NAME = ".bb_dos622_keyba2_v1_state"
EXPECTED_SIZE = 90997
EXPECTED_SHA_PREFIX = "99c40b35f00e"  # confirmed in user-provided 2026-10-14 handoff
KEYB92_STATE = ".bb_dos622_keyb92_v1_state"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_bytes(path: Path, data: bytes):
    """Atomic replace in same directory; preserve content exactly."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, fn = tempfile.mkstemp(prefix=".bbkeyba2-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(fn, path)
    finally:
        try:
            os.unlink(fn)
        except FileNotFoundError:
            pass


def transform(raw: bytes) -> bytes:
    if TAG.encode() in raw:
        raise ValueError("KEYBA2 marker already installed; use verify")
    if b"bb622-keyb92" not in raw:
        raise ValueError("Missing verified KEYB AH=92h handler marker; refusing wrong source")
    signatures = list(re.finditer(rb"(?m)^static\s+int\s+bb_v22_keyboard\s*\(", raw))
    if len(signatures) != 1:
        raise ValueError(f"Expected one shared bb_v22_keyboard(), found {len(signatures)}")
    start = signatures[0].start()
    brace = raw.find(b"{", signatures[0].end(), signatures[0].end() + 300)
    if brace < 0:
        raise ValueError("Cannot locate shared keyboard handler opening brace")
    # Keep the existing keyb92 case, queue semantics, and all other code intact.
    # The AH declaration is currently at the very start of the shared handler.
    region = raw[brace + 1:brace + 850]
    decls = list(re.finditer(
        rb"(?m)^[ \t]*uint8_t[ \t]+ah[ \t]*=[ \t]*\(uint8_t\)\(\*ax>>8\);[ \t]*(\r\n|\n)",
        region))
    if len(decls) != 1:
        raise ValueError(f"Expected one AH declaration near shared handler entry, found {len(decls)}")
    decl = decls[0]
    pos = brace + 1 + decl.end()
    eol = decl.group(1)
    # Precede any unknown-function rejection. In an IBM-enhanced (not 122-key)
    # BIOS, A2h should remain above 80h on return. AX=A200 -> AX=A200.
    # FLAGS, all registers, IP, and rewind are untouched. The DOS2 path does
    # not enter this block. Both interpreter/native callers use this handler.
    block = [
        f"    /* {TAG}: DOS 5+/6.x KEYB's undocumented 122-key capability probe.",
        "       Ordinary enhanced keyboard: do not advertise AH=20h..22h services.",
        "       Preserve AX, FLAGS, other registers, IP, and rewind. */",
        "    if (ah == 0xA2u) {",
        "        extern bool bb_sd_dos622_active(void);",
        "        if (bb_sd_dos622_active()) {",
        "            static unsigned bb622_keyba2_seen;",
        "            if (bb622_keyba2_seen++ == 0u) {",
        '                printf("[bb622-keyba2] KEYB INT16/AH=A2 unsupported 122-key; AX=%04X preserved\\n",',
        "                       (unsigned)*ax);",
        "                fflush(stdout);",
        "            }",
        "            return 1;",
        "        }",
        "    }",
    ]
    injected = eol.join(s.encode("ascii") for s in block) + eol
    out = raw[:pos] + injected + raw[pos:]
    if out.count(TAG.encode()) != 1 or out.count(b"bb622-keyba2") != 1:
        raise ValueError("Generated code did not satisfy single-insertion checks")
    # Ensure the inserted case is located before the rejection of unknown INT16
    # services and nowhere else in the source.
    reject = out.find(b"if (ah!=0x00u", start + 1, start + 1300)
    if reject < 0 or out.find(TAG.encode(), start, start + 1300) > reject:
        raise ValueError("Cannot prove A2h handler precedes unknown-service rejection")
    return out


def parent_manifests(root: Path, pre_sha: str, post_sha: str):
    """Return old/new manifest bytes for ALL checksum-tracking parent installers."""
    parents = {}
    for mf in sorted(root.glob(".bb_dos622_*_state/manifest.json")):
        if mf.parent.name == STATE_NAME:
            continue
        original = mf.read_bytes()
        try:
            info = json.loads(original)
        except Exception as exc:
            raise ValueError(f"Malformed parent manifest: {mf}: {exc}") from exc
        item = info.get("files", {}).get(SOURCE)
        if item is None:
            continue
        if not isinstance(item, dict) or not isinstance(item.get("installed"), str):
            raise ValueError(f"Unexpected parent manifest shape: {mf}")
        if item["installed"].lower() != pre_sha:
            raise ValueError(f"Parent manifest {mf} expects {item['installed']}, but source SHA is {pre_sha}; run parent verify first")
        item["installed"] = post_sha
        was_newline = original.endswith(b"\n")
        new = json.dumps(info, indent=2, ensure_ascii=False).encode("utf-8")
        if was_newline:
            new += b"\n"
        parents[mf.relative_to(root).as_posix()] = (original, new)
    required = f"{KEYB92_STATE}/manifest.json"
    if required not in parents:
        raise ValueError(f"Missing expected verified KEYB92 parent manifest: {required}")
    return parents


def prepare(root: Path, strict: bool = True, report: bool = True):
    if (root / STATE_NAME).exists():
        raise ValueError(f"{STATE_NAME} exists: use verify or restore; no changes made")
    target = root / SOURCE
    if not target.is_file():
        raise ValueError(f"Missing {target}")
    original = target.read_bytes()
    pre_sha = sha(original)
    if strict and (len(original) != EXPECTED_SIZE or not pre_sha.startswith(EXPECTED_SHA_PREFIX)):
        raise ValueError(
            f"Local {SOURCE} differs from captured KEYB92 source; "
            f"got bytes={len(original)} SHA256={pre_sha}; expected "
            f"bytes={EXPECTED_SIZE}, SHA256 prefix={EXPECTED_SHA_PREFIX}. "
            "Do not force installation: supply the updated local source and manifests for review.")
    changed = transform(original)
    post_sha = sha(changed)
    parents = parent_manifests(root, pre_sha, post_sha)
    changes = {SOURCE: (original, changed), **parents}
    if report:
        print(f"{SOURCE}: anchor PASS {len(original)} -> {len(changed)} bytes")
        print(f"source old={pre_sha} new={post_sha}")
        print(f"parent manifest SHA checks PASS: {len(parents)} updated atomically on apply")
        print("PROBE PASS: no repository files modified")
    return changes


def probe(root: Path = ROOT, strict: bool = True):
    prepare(root, strict)


def _load_state(root: Path):
    path = root / STATE_NAME / "manifest.json"
    if not path.is_file():
        raise ValueError(f"Missing installer state: {path}")
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("tag") != TAG or state.get("source") != SOURCE:
        raise ValueError("Installer state tag/path mismatch")
    if not isinstance(state.get("files"), list) or not state["files"]:
        raise ValueError("Installer state has no files")
    return state


def apply(root: Path = ROOT, strict: bool = True):
    changes = prepare(root, strict)
    state_path = root / STATE_NAME
    state_path.mkdir()  # refuse existing state
    state = {"tag": TAG, "source": SOURCE, "files": []}
    try:
        # Make verified byte-for-byte backups and commit the recovery manifest
        # BEFORE changing any parent/source, so interrupted writes are recoverable.
        for index, (rel, (old, new)) in enumerate(changes.items()):
            backup = f"backup_{index:03d}.bin"
            atomic_bytes(state_path / backup, old)
            state["files"].append({"path": rel, "backup": backup,
                                   "original": sha(old), "installed": sha(new)})
        atomic_bytes(state_path / "manifest.json", (json.dumps(state, indent=2) + "\n").encode("utf-8"))
        # Source + all parents have been validated; replace each atomically.
        for rel, (_, new) in changes.items():
            atomic_bytes(root / rel, new)
        verify(root)
    except Exception:
        # Automatic rollback of any changes that may already have completed.
        # State remains if recovery itself encounters a failure.
        try:
            for rel, (old, _) in changes.items():
                atomic_bytes(root / rel, old)
            shutil.rmtree(state_path)
        except Exception:
            print("Recovery state retained; use 'recover' after investigating errors", file=sys.stderr)
        raise
    print("APPLIED: A2h compatibility only, DOS6 opt-in, DOS2 unchanged")


def verify(root: Path = ROOT):
    state = _load_state(root)
    for item in state["files"]:
        path = root / item["path"]
        backup = root / STATE_NAME / item["backup"]
        if not backup.is_file() or sha(backup.read_bytes()) != item["original"]:
            raise ValueError(f"Missing/corrupt byte-exact backup for {item['path']}")
        if not path.is_file() or sha(path.read_bytes()) != item["installed"]:
            raise ValueError(f"Installed file SHA mismatch for {item['path']}")
    source = (root / SOURCE).read_bytes()
    if source.count(TAG.encode()) != 1:
        raise ValueError("Source marker missing/duplicated")
    print(f"VERIFY PASS: exact source and {len(state['files'])-1} parent manifests match; all backups valid")


def restore(root: Path = ROOT, recover: bool = False):
    state = _load_state(root)
    if not recover:
        verify(root)  # strict restore; never erase unrelated user edits
    for item in state["files"]:
        dest = root / item["path"]
        backup = root / STATE_NAME / item["backup"]
        old = backup.read_bytes()
        if sha(old) != item["original"]:
            raise ValueError(f"Backup SHA mismatch: {dest}")
        if recover and dest.exists():
            current = sha(dest.read_bytes())
            if current not in (item["installed"], item["original"]):
                raise ValueError(f"Recover REFUSED: unrelated change to {dest}")
    for item in state["files"]:
        old = (root / STATE_NAME / item["backup"]).read_bytes()
        atomic_bytes(root / item["path"], old)
    shutil.rmtree(root / STATE_NAME)
    print(f"RESTORE PASS: {len(state['files'])} files exactly returned to pre-A2h bytes")


def selftest():
    keyboard = ("static int bb_v22_keyboard(uint8_t *m, uint16_t *ax, uint16_t *flags,\n"
                "                            uint16_t *ip, uint8_t *rewind)\n"
                "{\n"
                "    uint8_t ah=(uint8_t)(*ax>>8);\n"
                '    /* previous fix bb622-keyb92 remains */\n'
                "    uint16_t head,tail;\n"
                "    if (ah == 0x92u) { *ax = 0x8000u; return 1; }\n"
                "    if (ah!=0x00u && ah!=0x01u && ah!=0x02u && ah!=0x10u && ah!=0x11u && ah!=0x12u) return 0;\n"
                "    return 1;\n"
                "}\n")
    for kind in ("LF", "CRLF", "MIXED", "CRLF_LF"):
        with tempfile.TemporaryDirectory(prefix=f"bb622_a2_{kind}_") as tmp:
            root = Path(tmp)
            source = root / SOURCE
            source.parent.mkdir(parents=True)
            if kind == "LF":
                original = keyboard.encode()
            elif kind == "CRLF":
                original = keyboard.replace("\n", "\r\n").encode()
            elif kind == "MIXED":
                original = ("// previous unrelated block\r\n" + keyboard).encode()
            else:
                original = (keyboard + "// additional file text\r\n").encode()
            source.write_bytes(original)
            parent = root / KEYB92_STATE / "manifest.json"
            parent.parent.mkdir(parents=True)
            before_manifest = (json.dumps({"tag": "BB_DOS622_KEYB92_V1",
                "files": {SOURCE: {"original": "a" * 64, "installed": sha(original)}}}, indent=2) + "\n").encode()
            parent.write_bytes(before_manifest)
            new = transform(original)
            assert new.count(TAG.encode()) == 1
            assert new.count(b"bb622-keyb92") == 1
            assert b"return 1;" in new
            prepare(root, strict=False, report=False)
            apply(root, strict=False)
            verify(root)
            updated = json.loads(parent.read_text())
            assert updated["files"][SOURCE]["installed"] == sha(new)
            restore(root)
            assert source.read_bytes() == original
            assert parent.read_bytes() == before_manifest
            assert not (root / STATE_NAME).exists()
            # Ensure duplicate source insertions fail safely.
            try:
                transform(new)
            except ValueError:
                pass
            else:
                raise AssertionError("Idempotence guard failed")
        print(f"SELFTEST {kind}: PASS")
    # Optional C execution of the exact emitted A2 handler, rather than only
    # checking that the text is present. This is a standalone host contract test
    # (not a Pico firmware build, and not proof of native interpreter integration).
    cc = shutil.which("cc") or shutil.which("clang") or shutil.which("gcc")
    if cc:
        with tempfile.TemporaryDirectory(prefix="bb622_keyba2_c_") as td:
            fn = Path(td) / "a2_contract.c"
            exe = Path(td) / ("a2_contract.exe" if os.name == "nt" else "a2_contract")
            csrc = ("#include <stdint.h>\n#include <stdbool.h>\n#include <stdio.h>\n#include <assert.h>\n"
                    "static bool dos6_enabled = true;\n"
                    "bool bb_sd_dos622_active(void) { return dos6_enabled; }\n"
                    + transform(keyboard.encode()).decode("ascii")
                    + "int main(void) {\n"
                    "  uint8_t m[1] = {0}, rewind = 0;\n"
                    "  uint16_t ax = 0xA200u, flags = 0x02C7u, ip = 0x1262u;\n"
                    "  assert(bb_v22_keyboard(m, &ax, &flags, &ip, &rewind) == 1);\n"
                    "  assert(ax == 0xA200u && flags == 0x02C7u && ip == 0x1262u && rewind == 0);\n"
                    "  ax=0xA25Au; flags=0x0002u; rewind=0;\n"
                    "  assert(bb_v22_keyboard(m, &ax, &flags, &ip, &rewind) == 1);\n"
                    "  assert(ax==0xA25Au && flags==0x0002u && rewind==0);\n"
                    "  ax=0x9200u; assert(bb_v22_keyboard(m, &ax, &flags, &ip, &rewind)==1);\n"
                    "  assert(ax==0x8000u);\n"
                    "  dos6_enabled=false; ax=0xA200u;\n"
                    "  assert(bb_v22_keyboard(m, &ax, &flags, &ip, &rewind)==0);\n"
                    "  assert(ax==0xA200u);\n"
                    "  return 0; }\n")
            fn.write_text(csrc, encoding="ascii")
            compiled = subprocess.run([cc, "-std=c11", "-o", str(exe), str(fn)],
                                      capture_output=True, text=True)
            if compiled.returncode != 0:
                raise AssertionError(f"C contract compilation failed: {compiled.stderr}")
            ran = subprocess.run([str(exe)], capture_output=True, text=True)
            if ran.returncode != 0:
                raise AssertionError(f"C contract run failed: {ran.stdout} {ran.stderr}")
        print("SELFTEST C11 contract: PASS (AX/FLAGS/IP/rewind, AH=92, DOS2 gate)")
    else:
        print("SELFTEST C11 contract: SKIP (no host C compiler found)")
    print("SELFTEST PASS: anchors, SHA manifests, atomic install/rollback, C contract when available")
    print("Note: Pico build and real DOS6 boot behavior still require hardware validation.")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("selftest", "probe", "apply", "verify", "restore", "recover"))
    args = p.parse_args()
    try:
        {"selftest": selftest,
         "probe": probe,
         "apply": apply,
         "verify": verify,
         "restore": restore,
         "recover": lambda: restore(recover=True)}[args.action]()
    except (OSError, ValueError, AssertionError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
