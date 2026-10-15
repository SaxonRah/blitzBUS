# Phase 3 conservative root cleanup

This pass removes *byte-identical* snapshots only where no tracked text references their folder name; archives reference-free standalone reports; and may relocate two early read-only log-analysis scripts if their dependency guard passes.

All .bb*_state directories, original images, source folders and versioned patch installers stay fixed. `reference_do_not_overwrite/` is intentionally kept if `SHA256SUMS.txt` still references its paths.

## Staged operations

- MOVE `TEST_REPAIRED.TXT` → `archive/reports/TEST_REPAIRED.TXT`
- MOVE `CHECK_NEWTEST.TXT` → `archive/reports/CHECK_NEWTEST.TXT`
- MOVE `bb_tier2a_analyze.py` → `tools/legacy/log-analysis/bb_tier2a_analyze.py`
- MOVE `bb_tier2b_analyze.py` → `tools/legacy/log-analysis/bb_tier2b_analyze.py`

No Git history rewrite. No automatic commit or push. A clean tracked working tree is required for the initial apply.

The snapshot under backups/bb_repo_phase3_v1_state keeps original file bytes until commit. `restore` works only before HEAD changes.

Git ignore rules do not remove already-tracked images. Never run `git add -A` during DOS image development.

The phase-2 REPO_TOOL_INDEX.md is a baseline catalog that may retain historical root locations. REPO_PHASE3_ROOT_AUDIT.md is the latest location map.

Untracked README_FIRST.md / README_FIX1.md / README_PHASE2_FIRST.md / PHASE2_REMOTE_AUDIT.md are not deleted automatically. Review and archive locally after the relevant cleanup commits.

