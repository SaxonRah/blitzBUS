#!/usr/bin/env python3
"""blitzBUS DOS 6.22 KEYB 122-key probe (INT 16h/AH=A2h) repair.

Reversible byte-exact local installer. This script does NOT apply Git patches,
modify boot media, or touch the DOS2 fallback. Usage in C:\\blitzBUS:
    python bb_dos622_keyba2_v3.py selftest
    python bb_dos622_keyba2_v3.py probe
    python bb_dos622_keyba2_v3.py apply
    python bb_dos622_keyba2_v3.py verify
    python bb_dos622_keyba2_v3.py restore

Precondition: the exact 2026-10-14 local source SHA256 prefix from the handoff.

V3 understands installed/new/after/parent_after checksum fields in existing
parent metadata. It also cascades checksums of changed parent JSON files
without rewriting immutable before/original data or formatting.
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
TAG = "BB_DOS622_KEYBA2_V3"
STATE_NAME = ".bb_dos622_keyba2_v3_state"
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
    if TAG.encode() in raw or b"BB_DOS622_KEYBA2_V1" in raw or b"BB_DOS622_KEYBA2_V2" in raw:
        raise ValueError("KEYBA2 V1/V2/V3 marker already installed; verify/restore existing installer first")
    if b"bb622-keyb92" not in raw:
        raise ValueError("Missing verified KEYB AH=92h handler marker; refusing wrong source")
    signatures = list(re.finditer(rb"(?m)^static\s+int\s+bb_v22_keyboard\s*\(", raw))
    if len(signatures) != 1:
        raise ValueError(f"Expected one shared bb_v22_keyboard(), found {len(signatures)}")
    start = signatures[0].start()
    brace = raw.find(b"{", signatures[0].end(), signatures[0].end() + 300)
    if brace < 0:
        raise ValueError("Cannot locate shared keyboard handler opening brace")
    # Keep KEYB92, queue semantics, and all other code byte-identical.
    # Safety proof: AH is the FIRST statement of this shared function. By
    # injecting immediately after it, A2 dispatch is reached before ANY
    # pre-existing service dispatch or unknown-service rejection, regardless
    # of function size, comments, whitespace, or the shape/location of that
    # rejection. V1 had an erroneous 1300-byte search window that failed on
    # the user's 90997-byte post-KEYB92 source.
    region = raw[brace + 1:brace + 850]
    decls = list(re.finditer(
        rb"(?m)^[ \t]*uint8_t[ \t]+ah[ \t]*=[ \t]*\(uint8_t\)\(\*ax>>8\);[ \t]*(\r\n|\n)",
        region))
    if len(decls) != 1:
        raise ValueError(f"Expected one AH declaration near shared handler entry, found {len(decls)}")
    decl = decls[0]
    # The declaration must be the first code in the function: no preceding
    # statement can reject A2 or change host/guest state before our handler.
    before_ah = region[:decl.start()]
    if before_ah.strip():
        raise ValueError("AH declaration is not the first statement in bb_v22_keyboard(); refusing insertion")
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
    # Structural proof of ordering, independent of original handler length:
    # there was only whitespace before the AH declaration, and our entire
    # branch now immediately follows that declaration. The first possible
    # early return after AH is the new A2 handler. The old legacy fallback is
    # not modified (its spelling/layout can legitimately vary across fixes).
    if out[pos:pos + len(injected)] != injected or b"    if (ah == 0xA2u) {" not in injected:
        raise ValueError("A2h block did not land immediately after the first AH declaration")
    return out


# Only active installer metadata is rewritten. Immutable historical snapshots,
# such as parent_before.json and *.bak, are NEVER scanned or modified.
META_BASENAMES = {"manifest.json", "repair.json"}
# These values represent the currently installed file (or currently installed
# parent metadata); older/source/backup hashes have different field names.
ACTIVE_SHA_KEYS = frozenset({
    "installed", "new", "after", "current", "post", "parent_after",
    "installed_sha", "installed_hash", "installed_sha256",
    "new_sha", "new_hash", "new_sha256",
    "after_sha", "after_hash", "after_sha256",
    "current_sha", "current_hash", "current_sha256",
    "post_sha", "post_hash", "post_sha256",
    "sha_after", "sha_new", "sha_installed", "sha_current",
    "parent_after_sha", "parent_after_hash", "parent_after_sha256",
    "src_new", "src_after", "src_installed", "src_current",
    "source_new", "source_after", "source_installed", "source_current",
    "file_new", "file_after", "file_installed", "file_current",
    "src_new_sha", "src_after_sha", "src_installed_sha", "src_current_sha",
    "source_new_sha", "source_after_sha", "source_installed_sha", "source_current_sha",
})
HISTORICAL_SHA_KEYS = frozenset({
    "original", "old", "before", "previous", "parent_before",
    "original_sha", "original_hash", "original_sha256",
    "old_sha", "old_hash", "old_sha256",
    "before_sha", "before_hash", "before_sha256",
    "backup", "backup_sha", "backup_hash", "backup_sha256",
    "parent_before_sha", "parent_before_hash", "parent_before_sha256",
})
# Byte preserving: only the 64 hexadecimal characters of a JSON key/value
# string are replaced. Original spacing, line endings, ordering and indentation
# are never reserialized. This supports 'installed', 'new', 'after', and
# 'parent_after' without presuming a particular parent manifest schema.
KV_SHA = re.compile(rb'"(?P<key>[^"\\]+)"\s*:\s*"(?P<digest>[A-Fa-f0-9]{64})"')


def active_metadata(root: Path):
    found = {}
    for folder in sorted(root.glob(".bb_dos622_*_state")):
        if not folder.is_dir() or folder.name == STATE_NAME:
            continue
        for path in sorted(folder.glob("*.json")):
            if path.name not in META_BASENAMES:
                continue
            rel = path.relative_to(root).as_posix()
            raw = path.read_bytes()
            try:
                parsed = json.loads(raw)
            except Exception as exc:
                raise ValueError(f"Malformed active parent metadata {rel}: {exc}") from exc
            if not isinstance(parsed, dict):
                raise ValueError(f"Unexpected active metadata type in {rel}; expected JSON object")
            found[rel] = raw
    expected = [
        ".bb_dos622_ipl_v1_state/manifest.json",
        ".bb_dos622_boot_diag_v1_state/repair.json",
        ".bb_dos622_heap_rescue_v1_state/manifest.json",
    ]
    for path in expected:
        if path not in found:
            raise ValueError(f"Missing expected installed parent metadata: {path}")
    if not any(rel.startswith(KEYB92_STATE + "/") for rel in found):
        raise ValueError(f"Missing active metadata under {KEYB92_STATE}; do not patch unverified state")
    return found


def _key_is_active(key: str):
    key = key.lower()
    if key in ACTIVE_SHA_KEYS:
        return True
    # Recognize a constrained naming convention but not ambiguous keys like
    # 'sha', 'checksum', 'digest', or metadata 'original'.
    parts = re.split(r"[_-]", key)
    return (len(parts) >= 2 and (
                (parts[0] in {"after", "installed", "current", "new", "post"}
                 and all(x in {"sha", "sha256", "hash", "digest", "checksum", "parent", "file", "source"}
                         for x in parts[1:]))
                or (parts[0] in {"src", "source", "file", "parent"}
                    and parts[1] in {"after", "installed", "current", "new", "post"}
                    and all(x in {"sha", "sha256", "hash", "digest", "checksum"}
                            for x in parts[2:]))))


def _key_is_historical(key: str):
    key = key.lower()
    if key in HISTORICAL_SHA_KEYS:
        return True
    if key.startswith(("original_", "old_", "before_", "backup_", "previous_", "parent_before_")):
        return True
    parts = re.split(r"[_-]", key)
    return len(parts) >= 2 and parts[0] in {"src", "source", "file", "parent"} and parts[1] in {"original", "old", "before", "backup", "previous"}


def _update_metadata(raw: bytes, changes: dict[str, str], rel: str):
    """Only replace SHA values in explicit active/current fields."""
    replacements = []
    blocked = []
    for m in KV_SHA.finditer(raw):
        key = m.group("key").decode("ascii", "replace")
        old = m.group("digest").decode("ascii")
        target = changes.get(old.lower())
        if target is None or target == old.lower():
            continue
        if _key_is_active(key):
            replacement = target.upper() if old.isupper() else target
            replacements.append((m.start("digest"), m.end("digest"), replacement.encode("ascii")))
        elif not _key_is_historical(key):
            blocked.append(key)
    if blocked:
        raise ValueError(f"Unknown current-SHA key(s) {sorted(set(blocked))} in {rel}; "
                         "refusing to guess metadata semantics. Supply the JSON for review.")
    if not replacements:
        return raw, 0
    out = bytearray(raw)
    for start, end, value in replacements:
        assert len(value) == end - start == 64
        out[start:end] = value
    data = bytes(out)
    if len(data) != len(raw):
        raise AssertionError(f"Metadata length changed unexpectedly: {rel}")
    # Validate schema neutral: the resulting JSON is still parseable.
    json.loads(data)
    return data, len(replacements)


def parent_manifests(root: Path, pre_sha: str, post_sha: str):
    """Update active checksums across nested formats and cascading parents.

    A higher-stage manifest may record the SHA of a lower-stage manifest.
    Thus changing the source -> IPL metadata -> boot_diag repair -> KEYB92
    manifest is a dependency graph. Iterate to a fixed point without touching
    historical backups and without reformatting any JSON.
    """
    original = active_metadata(root)
    after = dict(original)
    # Map old file checksum to newest file checksum (source initially).
    digest_changes = {pre_sha: post_sha}
    counts = {}
    for iteration in range(len(original) * 8 + 8):
        changed = False
        for rel, before in original.items():
            updated, hits = _update_metadata(before, digest_changes, rel)
            if hits:
                # Historical SHA always refers to the original bytes on disk.
                # Replacements can be recomputed as dependency hashes evolve.
                old_digest = sha(before)
                new_digest = sha(updated)
                if digest_changes.get(old_digest) != new_digest:
                    digest_changes[old_digest] = new_digest
                    changed = True
                if after[rel] != updated:
                    after[rel] = updated
                    counts[rel] = hits
                    changed = True
        if not changed:
            break
    else:
        raise ValueError("Metadata SHA dependency graph did not converge; refusing modification")

    # No silent misses for parent manifests claiming to hold the pre-patch
    # source checksum: it must be an active/current value, or the manifest
    # is either unrelated or incompatible. Historical-only references remain.
    required = f"{KEYB92_STATE}/manifest.json"
    if required not in after:
        raise ValueError(f"Missing expected KEYB92 manifest: {required}")
    keyb92_raw = original[required]
    if pre_sha.encode("ascii") not in keyb92_raw.lower() or required not in counts:
        raise ValueError("KEYB92 manifest does not actively track the verified source SHA; "
                         "refusing modification (inspect actual KEYB92 manifest)")
    for rel, before in original.items():
        if (pre_sha.encode("ascii") in before.lower() and SOURCE.encode("ascii") in before
                and rel not in counts):
            raise ValueError(f"Metadata references source SHA but has no supported active field: {rel}")
    result = {rel: (original[rel], after[rel]) for rel in original if after[rel] != original[rel]}
    for rel, (old, new) in result.items():
        if sha(old) == sha(new):
            raise AssertionError(f"Unexpected unchanged state: {rel}")
    return result, counts


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
    parents, counts = parent_manifests(root, pre_sha, post_sha)
    changes = {SOURCE: (original, changed), **parents}
    if report:
        print(f"{SOURCE}: anchor PASS {len(original)} -> {len(changed)} bytes")
        print(f"source old={pre_sha} new={post_sha}")
        for rel, (old_meta, new_meta) in parents.items():
            print(f"  {rel}: {len(old_meta)} -> {len(new_meta)} bytes, "
                  f"SHA {sha(old_meta)[:12]} -> {sha(new_meta)[:12]}, "
                  f"{counts[rel]} tracked SHA value(s)")
        print(f"parent metadata SHA cascade PASS: {len(parents)} updated atomically on apply")
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
    print("APPLIED: A2h compatibility only, full parent SHA cascade, DOS6 opt-in, DOS2 unchanged")


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
    print(f"VERIFY PASS: exact source and {len(state['files'])-1} parent metadata files match; all backups valid")


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


def _test_tree(root: Path, keyboard: bytes, variant: str):
    source = root / SOURCE
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(keyboard)
    pre = sha(keyboard)
    # IPL tracks the source with installed; old-style stage uses new; a
    # newer stage uses after; repair.json references both the source and a
    # changed parent manifest SHA (the actual boot_diag convention).
    ipl = root / ".bb_dos622_ipl_v1_state/manifest.json"
    diag = root / ".bb_dos622_boot_diag_v1_state/repair.json"
    heap = root / ".bb_dos622_heap_rescue_v1_state/manifest.json"
    keyb92 = root / KEYB92_STATE / "manifest.json"
    for path in (ipl, diag, heap, keyb92):
        path.parent.mkdir(parents=True)
    if variant == "LF": eol = "\n"
    elif variant == "CRLF": eol = "\r\n"
    else: eol = "\r\n"
    def put(path: Path, value):
        path.write_bytes((json.dumps(value, indent=2) + eol).replace("\n", eol).encode("ascii"))
    put(ipl, {"tag": "IPL", "files": {SOURCE: {"original": "0"*64, "installed": pre}}})
    put(diag, {"tag": "DIAG", "files": {SOURCE: {"old": "1"*64, "new": pre}},
               "parent_before": "2"*64, "parent_after": sha(ipl.read_bytes())})
    # Regression: heap rescue installed hash under 'new', not 'installed'.
    # Include a different new/after container convention for diversity.
    put(heap, {"tag": "HEAP", "source": SOURCE, "files": {SOURCE: {"old": "3"*64, "new": pre}},
               "ipldata": {"parent_after": sha(ipl.read_bytes())}})
    put(keyb92, {"tag": "KEYB92", "files": {SOURCE: {"before": "4"*64, "after": pre},
                                             ipl.relative_to(root).as_posix(): {"old": "5"*64, "new": sha(ipl.read_bytes())},
                                             diag.relative_to(root).as_posix(): {"original": "6"*64, "installed": sha(diag.read_bytes())},
                                             heap.relative_to(root).as_posix(): {"old": "7"*64, "new": sha(heap.read_bytes())}}})
    snap = root / KEYB92_STATE / "parent_before.json"
    snap.write_bytes(b'{"original": "not an active state"}\n')
    originals = {p: p.read_bytes() for p in (source, ipl, diag, heap, keyb92, snap)}
    return originals


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
        with tempfile.TemporaryDirectory(prefix=f"bb622_a2v3_{kind}_") as tmp:
            root = Path(tmp)
            if kind == "LF": original = keyboard.encode()
            elif kind == "CRLF": original = keyboard.replace("\n", "\r\n").encode()
            elif kind == "MIXED": original = ("// unrelated block\r\n" + keyboard).encode()
            else: original = (keyboard + "// additional text\r\n").encode()
            originals = _test_tree(root, original, kind)
            new = transform(original)
            assert new.count(TAG.encode()) == 1
            assert new.count(b"bb622-keyb92") == 1
            prepare(root, strict=False, report=False)
            apply(root, strict=False)
            verify(root)
            assert (root / KEYB92_STATE / "parent_before.json").read_bytes() == originals[root / KEYB92_STATE / "parent_before.json"]
            assert (root / ".bb_dos622_boot_diag_v1_state/repair.json").stat().st_size == len(originals[root / ".bb_dos622_boot_diag_v1_state/repair.json"])
            diag = json.loads((root / ".bb_dos622_boot_diag_v1_state/repair.json").read_bytes())
            ipl = root / ".bb_dos622_ipl_v1_state/manifest.json"
            assert diag["parent_after"] == sha(ipl.read_bytes()), "dependency checksum not propagated"
            keyb = json.loads((root / KEYB92_STATE / "manifest.json").read_bytes())
            assert keyb["files"][SOURCE]["after"] == sha(new)
            assert keyb["files"][ipl.relative_to(root).as_posix()]["new"] == sha(ipl.read_bytes())
            assert keyb["files"][".bb_dos622_boot_diag_v1_state/repair.json"]["installed"] == sha((root / ".bb_dos622_boot_diag_v1_state/repair.json").read_bytes())
            restore(root)
            for path, data in originals.items():
                assert path.read_bytes() == data, f"restore was not byte exact: {path}"
            assert not (root / STATE_NAME).exists()
            try: transform(new)
            except ValueError: pass
            else: raise AssertionError("Duplicate insertion allowed")
        print(f"SELFTEST {kind}: PASS, nested parent dependency cascade + restore")

    marker = "    uint16_t head,tail;\n"
    padded = keyboard.replace(marker, marker + "    /* " + ("KEYB92 expanded dispatch " * 105) + " */\n")
    patched = transform(padded.encode("ascii"))
    assert padded.index("if (ah!=0x00u") > padded.index("static int bb_v22_keyboard") + 1300
    assert patched.index(b"if (ah == 0xA2u)") < patched.index(b"if (ah!=0x00u")
    print("SELFTEST expanded handler guard: PASS")
    malformed = keyboard.replace("{\n    uint8_t ah=", "{\n    return 0;\n    uint8_t ah=")
    try: transform(malformed.encode("ascii"))
    except ValueError as exc: assert "AH declaration is not the first statement" in str(exc)
    else: raise AssertionError("Unsafe insertion was allowed")
    print("SELFTEST early-executable-code guard: PASS")

    # Malformed/unrecognized CURRENT digest key is a hard refusal;
    # historical old/original/parent_before digest remains untouched.
    digest = "a" * 64
    body = json.dumps({"odd_checksum": digest, "old": digest}).encode()
    try: _update_metadata(body, {digest: "b" * 64}, "unrecognized.json")
    except ValueError as exc: assert "Unknown current-SHA" in str(exc)
    else: raise AssertionError("Unknown metadata key was silently modified/ignored")
    protected = json.dumps({"old": digest, "new": digest, "parent_before": digest, "parent_after": digest}).encode()
    out, hits = _update_metadata(protected, {digest: "b" * 64}, "semantic.json")
    obj = json.loads(out)
    assert hits == 2 and obj["old"] == digest and obj["parent_before"] == digest
    assert obj["new"] == "b" * 64 and obj["parent_after"] == "b" * 64
    assert len(out) == len(protected)
    print("SELFTEST unknown checksum refusal/historical snapshot protection: PASS")

    cc = shutil.which("cc") or shutil.which("clang") or shutil.which("gcc")
    if cc:
        with tempfile.TemporaryDirectory(prefix="bb622_keyba2v3_c_") as td:
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
            compiled = subprocess.run([cc, "-std=c11", "-o", str(exe), str(fn)], capture_output=True, text=True)
            if compiled.returncode != 0:
                raise AssertionError(f"C contract compilation failed: {compiled.stderr}")
            ran = subprocess.run([str(exe)], capture_output=True, text=True)
            if ran.returncode != 0:
                raise AssertionError(f"C contract run failed: {ran.stdout} {ran.stderr}")
        print("SELFTEST C11 contract: PASS (AX/FLAGS/IP/rewind, AH=92, DOS2 gate)")
    else:
        print("SELFTEST C11 contract: SKIP (no host C compiler found)")
    print("SELFTEST PASS: source anchors, mixed JSON shapes, SHA cascade, byte-exact rollback")
    print("Note: Pico firmware/hardware still requires your local build and run.")


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
