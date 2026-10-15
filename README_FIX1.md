# blitzBUS repository cleanup — Windows Git line-ending FIX1

This is a drop-in replacement for `bb_repo_cleanup_v1.py` from `BLITZBUS_REPO_CLEANUP_V1.zip`.

## Symptom and root cause

The original `selftest` printed `RESTORE PASS` followed by `ERROR:` with no text. On Windows or when Git uses `core.autocrlf=true`, restoring a test README with LF-only line endings could change its worktree byte representation or leave a noisy Git index-stat state. The test raised a bare `AssertionError` and had no diagnostic message.

The file candidates in your real `probe` are not implicated. The real repository was NOT modified by running `selftest` or `probe`.

## Fixes

- Restores `.gitignore` and `README.md` from their SHA-checked original **byte backups** after restoring staged Git paths, instead of trusting Git's line-ending checkout conversion.
- Refreshes only these two index entries and verifies that their Git blobs still equal `HEAD`, so restoration does not silently stage different content.
- Checks that `HEAD` has not changed since `apply` before automatic restore (new FIX1 states record the starting HEAD; old manifests remain compatible).
- Replaces silent assertions with descriptive `CleanupError` messages.
- Tests 4 LF/CRLF x `core.autocrlf=true/false` cases, including modified duplicate rejection and staged apply/verify/restore.

## Installation

Extract this ZIP to `C:\blitzBUS` **with overwrite enabled**, replacing only the top-level `bb_repo_cleanup_v1.py`. Other original cleanup payload files can remain as-is.

```powershell
cd C:\blitzBUS
Expand-Archive "$HOME\Downloads\BLITZBUS_REPO_CLEANUP_V1_FIX1.zip" C:\blitzBUS -Force
python .\bb_repo_cleanup_v1.py selftest
python .\bb_repo_cleanup_v1.py probe
```

Do not run `apply` unless **both** commands pass. After verifying the working tree and backing up the real DOS HDD:

```powershell
git status --short
git switch -c chore/blitzbus-repo-cleanup
python .\bb_repo_cleanup_v1.py apply
python .\bb_repo_cleanup_v1.py verify
git diff --cached --stat
python .\bb622_lineage_verify_v13.py verify
python .\bb622_irq0_trial_v1.py verify
```

To undo before committing:

```powershell
python .\bb_repo_cleanup_v1.py restore
```

**No changes to any `DOS622_HDD.IMG`, game floppy image, firmware `.c`/`.inc` files, installer rollback states, or Git history are performed by the cleanup tool.** All deletions are SHA-checked duplicate copies. Do not commit or reset unrelated modifications by accident; inspect Git's staged diff.

## Validation

Original script reproduced `ERROR:` under Linux with Git configured `core.autocrlf=true`; this replacement passes all four variants under both normal Git settings and an injected global `core.autocrlf=true`. Tests run in temporary Git fixtures; the user's Windows machine has not been directly tested here.
