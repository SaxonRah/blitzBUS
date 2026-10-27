# Phase-2 repository hygiene

This phase archives reference-free historical documents and standalone test output, and adds tool/media/history/test catalogs and a reusable maintenance script plus this policy. No emulator source, installer, BIOS, PSRAM, IRQ0, HDD/floppy or patch-state file is moved.

## Planned/staged archive moves

- `SELFTEST_OUTPUT.txt` → `archive/test-results/SELFTEST_OUTPUT.txt`
- `TEST_RESULTS.txt` → `archive/test-results/TEST_RESULTS.txt`
- `V2_2_SELFTEST.txt` → `archive/test-results/V2_2_SELFTEST.txt`
- `test_installer.txt` → `archive/test-results/test_installer.txt`
- `test_c11.txt` → `archive/test-results/test_c11.txt`
- `test_lineage.txt` → `archive/test-results/test_lineage.txt`
- `log_audit_selftest.txt` → `archive/test-results/log_audit_selftest.txt`
- `BB_386_PM0_INCLUDE_FIX1_README.md` → `docs/history/386/BB_386_PM0_INCLUDE_FIX1_README.md`
- `BB_386_RM2_SRAM_FLASH_FIX_README.md` → `docs/history/386/BB_386_RM2_SRAM_FLASH_FIX_README.md`
- `BB_386_RM3_SELFTEST_FIX1_README.txt` → `docs/history/386/BB_386_RM3_SELFTEST_FIX1_README.txt`
- `BIOS_386_ROADMAP.md` → `docs/history/386/BIOS_386_ROADMAP.md`
- `BLITZ86_386_PM0_README.md` → `docs/history/386/BLITZ86_386_PM0_README.md`
- `BLITZ86_386_RM0_README.md` → `docs/history/386/BLITZ86_386_RM0_README.md`
- `BLITZ86_386_RM1_README.md` → `docs/history/386/BLITZ86_386_RM1_README.md`
- `BLITZ86_386_RM2_README.md` → `docs/history/386/BLITZ86_386_RM2_README.md`
- `BLITZ86_386_RM3_README.md` → `docs/history/386/BLITZ86_386_RM3_README.md`
- `BLITZ86_CPU_COMPATIBILITY_WORKPLAN.md` → `docs/history/386/BLITZ86_CPU_COMPATIBILITY_WORKPLAN.md`
- `BLITZBUS_DOS622_BOOT_DIAG_V1_README.md` → `docs/history/dos622/BLITZBUS_DOS622_BOOT_DIAG_V1_README.md`
- `BLITZBUS_DOS622_IPL_V1_README.md` → `docs/history/dos622/BLITZBUS_DOS622_IPL_V1_README.md`
- `BLITZBUS_DOS622_KEYBA2_V1_README.md` → `docs/history/dos622/BLITZBUS_DOS622_KEYBA2_V1_README.md`
- `BLITZBUS_DOS622_KEYBA2_V2_README.md` → `docs/history/dos622/BLITZBUS_DOS622_KEYBA2_V2_README.md`
- `BLITZBUS_DOS622_KEYBA2_V3_README.md` → `docs/history/dos622/BLITZBUS_DOS622_KEYBA2_V3_README.md`
- `BLITZBUS_DOS622_LCD_TEXT_V1_README.md` → `docs/history/dos622/BLITZBUS_DOS622_LCD_TEXT_V1_README.md`
- `BLITZBUS_DOS622_P61_REFRESH_V1_README.md` → `docs/history/dos622/BLITZBUS_DOS622_P61_REFRESH_V1_README.md`
- `BLITZBUS_DOS622_SD_CLOCKFIX_V1_README.md` → `docs/history/dos622/BLITZBUS_DOS622_SD_CLOCKFIX_V1_README.md`
- `BLITZBUS_DOS622_THREE_DISK_STAGING.md` → `docs/history/dos622/BLITZBUS_DOS622_THREE_DISK_STAGING.md`
- `BLITZBUS_DOS622_VGA12_30_V1_README.md` → `docs/history/dos622/BLITZBUS_DOS622_VGA12_30_V1_README.md`
- `BLITZBUS_DOS622_VGA12_34_V1_README.md` → `docs/history/dos622/BLITZBUS_DOS622_VGA12_34_V1_README.md`

Each file was checked against other tracked text files for references by basename and required to match the unmodified Git index. References and local changes cause the move to be blocked.

## Protected boundaries

- Never move `.bb_dos622_*_state`, `.bb622_*_state`, or their backups/manifests.
- Never rename root-level `bb_dos622_*.py`, `bb622_*.py`, firmware `.inc` files, `src/`, `sd_boot/`, or active runner scripts without a separately verified migration of all references.
- Never prune unique `.IMG` images during a code cleanup.
- Previous V1 duplicate asset cleanup is independent of these changes.

## Restore

Before committing, run `python .\bb_repo_phase2_v1.py verify` followed by `python .\bb_repo_phase2_v1.py restore`. No automatic commit/push is performed.

If an archive move is blocked, inspect `probe` output before considering an explicit compatibility adapter.

