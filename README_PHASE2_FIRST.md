# blitzBUS repository cleanup — phase 2

**Baseline:** phase-1 cleanup branch `chore/blitzbus-repo-cleanup` committed locally (and optionally pushed). Phase 2 does **not** require phase 1 to be merged to `main`.

This is **structural/documentation maintenance**. It does not change or build firmware, microDOS/blitz86 source, the IRQ0 dispatcher, DOS disk data, installer scripts, or any `.bb*state` checksum directory. No automatic commit or push.

## What the package does

- Archives standalone tracked test-output transcripts under `archive/test-results/` **only if** no other tracked text file references the basename, their working-tree Git version is clean, and the destination does not exist.
- Moves reference-free historical 386/286 documentation to `docs/history/386/`, and DOS 6.22 stage documentation to `docs/history/dos622/`. **No active installers move.** A referenced/modified document is reported as `KEEP` and left unchanged.
- Generates `docs/REPO_TOOL_INDEX.md` with classified root-level Python tools and `scripts/` entry points.
- Generates `docs/REPO_MEDIA_INVENTORY.md` with tracked disk/media sizes; **does not delete unique images**.
- Generates `docs/REPO_HISTORY_INDEX.md` listing moved historical documentation and transcripts.
- Generates `docs/REPO_TEST_AUDIT.md` listing root-level C/ASM test sources and their literal references; lack of references is **not proof a test is unused**.
- Generates `docs/REPO_PHASE2_POLICY.md` and installs a checked copy of the maintenance program at `scripts/repo_phase2_hygiene.py`.
- Uses `git mv` and stages *only* the expected paths. Does not use `git add -A`.

The scanner is conservative but cannot prove the absence of *dynamically constructed* paths or personal scripts outside the repository. Review changes before committing.

## Installation

Extract the ZIP at `C:\blitzBUS`, so the new `bb_repo_phase2_v1.py` ends up at the root. Avoid placing the ZIP contents into an extra nested folder.

Close the DOS/COM5 runner. Before this cleanup, protect your DOS 6.22 image independently, and commit or restore any tracked edits. Check:

```powershell
cd C:\blitzBUS
git status --short
git branch --show-current
python .\bb622_lineage_verify_v13.py verify
python .\bb622_irq0_trial_v1.py verify
```

Your branch should normally be `chore/blitzbus-repo-cleanup` (or a **new branch based on it**). The installer *refuses* any unstaged or staged changes to tracked files. Untracked cleanup helper files from phase 1 may remain: this tool does not touch them.

## Validate, preview, apply

```powershell
cd C:\blitzBUS
python .\bb_repo_phase2_v1.py selftest
python .\bb_repo_phase2_v1.py probe
```

**Review the `MOVE` and `KEEP` lines**. Any reference or modified file is automatically kept. If `probe` fails, stop rather than forcing it. If acceptable:

```powershell
python .\bb_repo_phase2_v1.py apply
python .\bb_repo_phase2_v1.py verify

git diff --cached --check
git diff --cached --stat
git diff --cached --name-status

python .\bb622_lineage_verify_v13.py verify
python .\bb622_irq0_trial_v1.py verify
```

Review `docs/REPO_TOOL_INDEX.md`, `docs/REPO_MEDIA_INVENTORY.md`, `docs/REPO_HISTORY_INDEX.md`, and `docs/REPO_TEST_AUDIT.md`. Do not infer that a Python script is unused simply because a file has no obvious imports.

## Roll back *before committing*

```powershell
python .\bb_repo_phase2_v1.py verify
python .\bb_repo_phase2_v1.py restore
git status --short
```

The rollback restores exact original file bytes from backups under `backups/bb_repo_phase2_v1_state/`, unstages the archive moves and removes generated documentation. The path is under the existing Git-ignored `backups/` directory. It refuses rollback if a staged/generated file was edited after apply.

## Commit and push after review

```powershell
git commit -m "chore: archive historical docs and index blitzBUS tools"
git push
```

The `bb_repo_phase2_v1.py` that you extracted at the root stays **untracked**; a copy is committed as `scripts/repo_phase2_hygiene.py`. Do **not** run `git add -A` just to include the former.

**Note:** After committing, `verify` and `restore` intentionally refuse because HEAD changed. Undo a committed cleanup with Git's normal `git revert` workflow after reviewing its commit. Leave the local backups intact until you're satisfied.

## Validation scope

The tool's disposable-repo tests cover Git `core.autocrlf=true/false` combined with LF/CRLF source files, exact reference guards, modified tracked source guards, correct staging, checksum verification, and byte-exact rollback. It has **not** run against the user's Windows checkout or compiled Pico firmware in this environment.

## What remains for a future phase

Moving hundreds of versioned Python installers is deliberately postponed. Safe consolidation needs a version-aware installer loader, stable external entry-point shims, and an adapted checksum-chain verifier tested against *all* historic stages. Unique game/media assets and ROM/disk images require separate archival/licensing decisions and must not be deleted to simplify source navigation.
