# blitzBUS phase-2 audit notes

Reviewed the public `SaxonRah/blitzBUS` branch `chore/blitzbus-repo-cleanup` at commit `5f08f285df887f39357556e95c2e558cec15ff73`.

At the reviewed commit, 1,023 files were tracked, with 235 root-level files. Among those root-level files were 111 `.py` scripts, 14 `.ps1` scripts, 26 `.md` documents, and 18 `.c` sources. `main` had not yet incorporated phase 1 when checked.

**Risk categories**

- **Highest risk / frozen paths:** `src/`, `sd_boot/`, all `.bb*state` directories, phase-specific `bb622_*.py` and `bb_dos622_*.py` installers, active runners and `DOS622_HDD.IMG`.
- **Reorganization candidates:** old `BLITZ86_386_*_README.md`, old `BLITZBUS_DOS622_*_README.md`, and standalone test-output `.txt` files when no literal references exist.
- **Review only:** unique disk images and snapshots, game-data archives, old C tests, and benchmark binaries.

**Limitations**

GitHub code search did not find obvious references to the selected historic document and test-result basenames, but local source scanning is authoritative for the checkout actually being changed. A zero-reference result is not proof of no dynamic dependency. The phase-2 tool therefore checks the local tracked checkout and skips any detected references or local modifications.

No API write to GitHub was performed by this phase. User can review/stage locally and then commit/push normally.
