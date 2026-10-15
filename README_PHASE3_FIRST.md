# blitzBUS — safe root-folder cleanup (Phase 3)

**Use only after phase 2 is committed.** This package does not itself apply phase 2. It does not flash the Pico, launch DOS or modify guest disk images. The goal is to reduce avoidable root clutter without invalidating the DOS 6.22 patch/rollback chain.

## 1. Complete phase 2 first (only if not already committed)

In PowerShell, from `C:\blitzBUS`:

```powershell
cd C:\blitzBUS
git status --short
python .\bb_repo_phase2_v1.py selftest
python .\bb_repo_phase2_v1.py probe
```

The phase-2 `probe` reports which historical documents/transcripts can be moved and which must stay because of references. If the probe passes and the list is acceptable:

```powershell
python .\bb_repo_phase2_v1.py apply
python .\bb_repo_phase2_v1.py verify
git diff --cached --check
git diff --cached --stat
python .\bb622_lineage_verify_v13.py verify
python .\bb622_irq0_trial_v1.py verify
```

**Review the staged changes** before:

```powershell
git commit -m "chore: organize historical docs and create tool indexes"
```

If phase 2 was already committed, **do not rerun phase 2**. Continue below. If the working tree has staged or unstaged tracked edits, commit/restore those intentionally before any new cleanup. `git status --short` may show untracked cleanup helpers; this is okay.

## 2. Install phase 3 and preview

Extract `BLITZBUS_REPO_PHASE3_SAFE_ROOT_V1.zip` into `C:\blitzBUS` (it contains only `bb_repo_phase3_v1.py` and this README).

```powershell
cd C:\blitzBUS
Expand-Archive `
  "$HOME\Downloads\BLITZBUS_REPO_PHASE3_SAFE_ROOT_V1.zip" `
  C:\blitzBUS -Force

python .\bb_repo_phase3_v1.py selftest
python .\bb_repo_phase3_v1.py probe
```

`probe` requires a clean tracked Git working tree and a clean Git index. It checks file bytes, folder references, the existing destination names and whether historical tools have obvious installer/relative-path dependencies. `KEEP` means *do not remove/move*.

The expected categories of possible changes depend on your current local source:

- **Delete a redundant tracked reference copy only** if it matches its root-level counterpart *byte-for-byte* and no other tracked text references the containing folder.
- **Keep `reference_do_not_overwrite/`** when `SHA256SUMS.txt` mentions its path, even if its files match a root copy.
- Archive **only unreferenced** report snapshots like `LAST_DOS_SCREEN_20261014.txt` and `LAST_LOG_AUDIT_20261014.json` under `archive/reports/`.
- Move only two **old log-analysis-only** scripts (`bb_tier2a_analyze.py`, `bb_tier2b_analyze.py`) under `tools/legacy/log-analysis/`, *if* the local reference and script guards approve them. The new tool locator will list and run them under their new paths.
- Generate `docs/REPO_PHASE3_ROOT_AUDIT.md`, `docs/REPO_PHASE3_POLICY.md`, `scripts/bb_repo_tools.py` and a maintained copy of the phase-3 installer at `scripts/repo_phase3_hygiene.py`.

No unique disk image, DOS install file, firmware source, `bb622_*`/`bb_dos622_*` installer, `.inc` file, `SHA256SUMS.txt`, or `.bb*_state` directory is deleted or moved.

## 3. Stage and verify phase 3

Only if `probe` gives the desired result:

```powershell
python .\bb_repo_phase3_v1.py apply
python .\bb_repo_phase3_v1.py verify

git diff --cached --check
git diff --cached --stat
git diff --cached --name-status

python .\bb622_lineage_verify_v13.py verify
python .\bb622_irq0_trial_v1.py verify

python .\scripts\bb_repo_tools.py list
```

Review the staged list. **No commit or push is automatic.** If you approve:

```powershell
git commit -m "chore: remove unused reference duplicates and catalog root tools"
git status --short
```

Optionally push the existing cleanup branch with `git push` after inspection. No Git history rewrite.

## 4. Undo phase 3 before committing

```powershell
python .\bb_repo_phase3_v1.py verify
python .\bb_repo_phase3_v1.py restore
```

The original bytes are saved under ignored `backups/bb_repo_phase3_v1_state/`. Once a new Git commit changes `HEAD`, automated restore refuses; use Git's normal `revert` workflow instead. A failed apply preserves backups for investigation; do not run destructive Git reset commands.

## 5. Untracked setup notes and old logs

These temporary root notes are **not** deleted automatically:

`README_FIRST.md`, `README_FIX1.md`, `README_PHASE2_FIRST.md`, `PHASE2_REMOTE_AUDIT.md`

After both cleanups are committed and you no longer need the original handouts, move any present notes out of the root without deleting them:

```powershell
cd C:\blitzBUS
New-Item -ItemType Directory -Path .\archive\local-cleanup-notes -Force | Out-Null
@('README_FIRST.md','README_FIX1.md','README_PHASE2_FIRST.md','PHASE2_REMOTE_AUDIT.md') |
  ForEach-Object {
    if (Test-Path -LiteralPath $_) {
      Move-Item -LiteralPath $_ -Destination .\archive\local-cleanup-notes\ -WhatIf
    }
  }
```

Remove `-WhatIf` **only after inspecting the preview**. Don't delete `repo_cleanup_payload/` or the extracted installer Python files while you still need their rollback utilities. `__pycache__/` can be removed any time the scripts are not running.

## Validation

Self-tests in a disposable Git repository passed four LF/CRLF + `core.autocrlf=true/false` combinations with stage → verify → restore, checksum reference protection and modified checkout refusal. Your actual Windows checkout and Pico device have **not** been modified or tested by this packaging process. The tool may find fewer eligible moves than the upstream audit; that is expected and safe.
