# blitzBUS repository hygiene — conservative cleanup

Audit based on the tracked `main` tree inspected **2026-10-14**, before this cleanup branch:

- **1,046 tracked files** across 99 Git trees.
- About **290.8 MB of `.IMG` files** in the checkout (14 tracked uppercase `.IMG` paths).
- **420 `.bin` blobs**, predominantly historical installer rollback state (~3 MB total). These are **not** ordinary disposable build products.
- **76 groups** of exact matching Git object SHA-1 IDs. Duplicates represent about **52.8 MB** of repeated checkout copies; Git's packfiles already deduplicate identical object IDs, so removing duplicate paths primarily reduces the checked-out worktree, *not existing Git history*.

## Scope of the proposed cleanup

Only redundant files whose Git blob IDs match retained files are removed. The chosen canonical locations and their duplicates were validated against the branch base tree:

| Remove from current tree | Retained byte-identical copy | Repeated checkout bytes |
| --- | --- | ---: |
| `descent_extracted/` (25 files) | `descent_complete/` (same 25 relative paths) | 19,739,348 |
| `DRIVE_C_PRE_FAT_REPAIR.IMG` | `DRIVE_C_BEFORE_CLEAN.IMG` | 31,457,280 |
| `BOOT_MINIMAL_TEST_old2.IMG` | `BOOT_MINIMAL_TEST.IMG` | 368,640 |

**Total redundant checkout copies removed: 51,565,268 bytes (~49.2 MiB).** All three retained locations contain byte-identical content in this revision. These removals do not erase Git history; individual files can be restored from the base commit.

`BB_DESCENT_OFFLINE_INSTALL/install_descent.py` defaults to `descent_extracted/` as a **fresh staging/output folder**. That folder being absent in a clean clone is intentional. Run `--extract-only` to populate it before `--install-only`; existing files in the stage cause extraction to refuse overwriting them. If you need a pre-extracted data tree for manual use, point `--stage` to `descent_complete/` when using **install-only**, without re-extracting into that tree. The offline installer does not depend on the removed folder's content existing in Git at startup.

## Kept deliberately

- `DOS622_HDD.IMG` and all **unique** `DRIVE_C*.IMG` versions: the writable DOS state and historical recovery checkpoints. No repartition, FAT operation, or byte edit is part of cleanup.
- `games/`, `descent_volumes/`, `descent_complete/`, and `descent_extracted_incomplete/`: retained while their historical/diagnostic uses are assessed; may contain third-party game data.
- All `.bb_dos622_*_state/` and `.bb622_*_state/` manifests and backups. **Never delete them without first proving the lineage verifier and restore tools do not reference them.**
- All `src/`, `sd_boot/`, `pico/`, `scripts/`, `tests/`, 386 probes, and `BB_*` tool folders; no executable source or active runner is deleted.
- Exact-looking copies under `reference_dependencies_DO_NOT_OVERWRITE/` and `reference_do_not_overwrite/`: these are packaging references. Validate which installed package expects them before removal.

## Local audit, verification, and safe Git workflow

```powershell
cd C:\blitzBUS
# Inspect uncommitted changes BEFORE pulling this cleanup PR.
git status --short
python .\scripts\repo_audit.py --root C:\blitzBUS

# Existing DOS 6.22 checksum-layer regression checks.
python .\bb622_lineage_verify_v13.py verify
python .\bb622_irq0_trial_v1.py verify
```

Before merging or checking out the cleanup branch, **copy irreplaceable modified images outside the repository**, including the active SD-backed `DOS622_HDD.IMG` and any handwritten extraction results. Be aware that tracked image changes are not protected by `.gitignore`; use `git status` before `git add -A` and never commit local DOS images accidentally.

After review, a local checkout can compare the candidate branch without merging:

```powershell
git fetch origin
# This only lists changes. It does NOT check out or overwrite your files.
git diff --stat origin/main..origin/chore/blitzbus-repo-hygiene-20261014
```

The top-level README was previously the IRQ0 one-shot package README. Its full original content is preserved in `docs/experiments/IRQ0_ONE_SHOT_TRIAL_V1.md`.

## Further cleanup requires explicit decisions

There are more large, unique older FAT16 disk checkpoints (e.g. `DRIVE_C_BEFORE_INSTALL.IMG`, `DRIVE_C_30M_NEW.IMG`, `DRIVE_C_CLEAN.IMG`) and historical benchmarks. Some may be obsolete; others are recovery assets. **No unique disk image is deleted in this cleanup.** If more size reduction is desired, verify which images can be archived offline or moved to an external data store *before* removing tracked paths. Git history retains old large blobs unless history is rewritten, which is **not appropriate** during the current checksum-sensitive DOS 6.22 investigation.

The public repository may also contain game assets whose redistribution rights should be reviewed independently. Cleanup does not establish rights or permission to redistribute those assets.
