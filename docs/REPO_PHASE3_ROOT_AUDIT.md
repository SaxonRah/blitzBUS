# Root tools and historical analysis — phase 3

Generated from the local Git checkout. The list is a navigation catalog, not evidence that an unreferenced script is obsolete.

## Critical paths not moved

- Root `bb622_*.py` and `bb_dos622_*.py` installers, state manifests, backup folders, .inc files and firmware sources retain their original names.
- `DOS622_HDD.IMG` and all other DOS/floppy images are never modified.
- `bb622_lineage_verify_v13.py verify` and `bb622_irq0_trial_v1.py verify` remain the required regression gates.

## Categorized remaining root Python / PowerShell tools

### DOS 6.22 versioned installers / utilities (keep fixed paths) (56)

- `bb622_boot_eject_v1.py`
- `bb622_console_report.py`
- `bb622_descent_diagnose.py`
- `bb622_descent_swap_c11.py`
- `bb622_descent_swap_c11_v2.py`
- `bb622_descent_swap_v1.py`
- `bb622_dos_disk_audit_v3.py`
- `bb622_hdd_audit.py`
- `bb622_log_window.ps1`
- `bb622_logview.py`
- `bb622_logview_pic.py`
- `bb622_media_audit.py`
- `bb622_request_disk_v2.ps1`
- `bb622_request_disk_v3.ps1`
- `bb622_swap_ack_v2.py`
- `bb622_swap_ack_v3.py`
- `bb622_swap_controls_fix_v1.py`
- `bb_dos622_atbios_v1.py`
- `bb_dos622_boot_diag_v1.py`
- `bb_dos622_color_cells_v1.py`
- `bb_dos622_color_host.ps1`
- `bb_dos622_ega_info_v1.py`
- `bb_dos622_floppy_b_v1.py`
- `bb_dos622_hdd_image_audit.py`
- `bb_dos622_hdd_v1.py`
- `bb_dos622_hdd_v2.py`
- `bb_dos622_heap_rescue_v1.py`
- `bb_dos622_image.py`
- `bb_dos622_ipl_v1.py`
- `bb_dos622_keyb92_v1.py`
- `bb_dos622_keyba2_v1.py`
- `bb_dos622_keyba2_v2.py`
- `bb_dos622_keyba2_v3.py`
- `bb_dos622_lcd_text_v1.py`
- `bb_dos622_lcd_text_v2.py`
- `bb_dos622_log_audit.py`
- `bb_dos622_p61_refresh_v1.py`
- `bb_dos622_printer17_v1.py`
- `bb_dos622_rtc1a_v1.py`
- `bb_dos622_screen_clear_v1.py`
- `bb_dos622_screen_host.ps1`
- `bb_dos622_sd_clockfix_v1.py`
- `bb_dos622_serial14_guard_v1.py`
- `bb_dos622_sram_floor_v1.py`
- `bb_dos622_stage3_v1.py`
- `bb_dos622_stall_watch_v1.py`
- `bb_dos622_swap_lcd_v1.py`
- `bb_dos622_swap_lcd_v2.py`
- `bb_dos622_swap_lcd_v2_1.py`
- `bb_dos622_swap_lcd_v2_2.py`
- `bb_dos622_textio_psram_v1.py`
- `bb_dos622_textio_v1.py`
- `bb_dos622_vga0b_keys_v1.py`
- `bb_dos622_vga0b_stdio_fix_v1.py`
- `bb_dos622_vga12_30_v1.py`
- `bb_dos622_vga12_34_v1.py`

### active DOS 6.22 verification / IRQ0 experiments (19)

- `bb622_irq0_report.py`
- `bb622_irq0_trial_v1.py`
- `bb622_lineage_verify_v11.py`
- `bb622_lineage_verify_v12.py`
- `bb622_lineage_verify_v13.py`
- `bb622_pic_host_control_v1.py`
- `bb622_pic_pending_v1.py`
- `bb622_pic_session_trial_v1.py`
- `bb_dos622_irq0_isolation_v1.py`
- `bb_dos622_lineage_verify_v1.py`
- `bb_dos622_lineage_verify_v10.py`
- `bb_dos622_lineage_verify_v2.py`
- `bb_dos622_lineage_verify_v3.py`
- `bb_dos622_lineage_verify_v4.py`
- `bb_dos622_lineage_verify_v5.py`
- `bb_dos622_lineage_verify_v6.py`
- `bb_dos622_lineage_verify_v7.py`
- `bb_dos622_lineage_verify_v8.py`
- `bb_dos622_lineage_verify_v9.py`

### disk/media analysis (2)

- `bb_fat12_import_v1.py`
- `bb_make_dos622_hdd_v1.py`

### other tools / historical experiments (24)

- `bb_archive_62_5.ps1`
- `bb_audit_sram_flash_fix_v1.py`
- `bb_chain_audit.py`
- `bb_chain_exit_split_v1.py`
- `bb_chain_exit_split_v2.py`
- `bb_cpu_readiness_v1.py`
- `bb_deadstub_unchain_ab.py`
- `bb_deadstub_unchain_ab_v2.py`
- `bb_eviction_tune.py`
- `bb_exit_hotspot_v1.py`
- `bb_fallback_opcode_profile_v1.py`
- `bb_int_vector_profile_v1.py`
- `bb_make_dos622_clean_console.py`
- `bb_meta_telemetry.ps1`
- `bb_psram_layout_v1.py`
- `bb_psram_meta_experiment.ps1`
- `bb_rcx_mem1_ab_v1.py`
- `bb_repo_phase2_v1.py`
- `bb_retranslation_promotion.py`
- `build_rcxtest.py`
- `c11_swap_lcd_tests.py`
- `test_keyb92_c.py`
- `test_sram_floor.py`
- `verify_c_probe.py`

### x86/386/JIT development (23)

- `bb_386_pm0_include_fix1.py`
- `bb_386_pm0_v1.py`
- `bb_386_rm0_v1.py`
- `bb_386_rm1_v1.py`
- `bb_386_rm2_flash_sram_v1.py`
- `bb_386_rm2_v1.py`
- `bb_386_rm3_v1.py`
- `bb_jit_reuse_diag.py`
- `bb_jit_tune.py`
- `bb_thumb2_form_and_lookup_audit_v1.py`
- `bb_tier0.ps1`
- `bb_tier1.ps1`
- `bb_tier1_followup.ps1`
- `bb_tier1f.ps1`
- `bb_tier1g.ps1`
- `bb_tier1h.py`
- `bb_tier1i.py`
- `bb_tier1j.py`
- `bb_tier1k.py`
- `bb_tier1l.py`
- `bb_tier2c_install.py`
- `bb_tier2c_repair.py`
- `bb_tier2f_aba.ps1`

## Relocated historical log readers (if any)

- `CHECK_NEWTEST.TXT` → `archive/reports/CHECK_NEWTEST.TXT`
- `TEST_REPAIRED.TXT` → `archive/reports/TEST_REPAIRED.TXT`
- `bb_tier2a_analyze.py` → `tools/legacy/log-analysis/bb_tier2a_analyze.py`
- `bb_tier2b_analyze.py` → `tools/legacy/log-analysis/bb_tier2b_analyze.py`

Use `python .\scripts\bb_repo_tools.py list` to enumerate tools or `run TOOL.py ...` from the repository root.
The dispatcher does not bypass Python scripts with their own prerequisites or manifest state checks.

## Retained / blocked candidates

- `reference_dependencies_DO_NOT_OVERWRITE/`: referenced from docs/REPOSITORY_CLEANUP.md
- `reference_do_not_overwrite/`: referenced from SHA256SUMS.txt, docs/REPOSITORY_CLEANUP.md
- `LAST_DOS_SCREEN_20261014.txt`: referenced from archive/test-results/log_audit_selftest.txt
- `LAST_LOG_AUDIT_20261014.json`: referenced from archive/test-results/log_audit_selftest.txt
- `FAT_CHAIN_REPORT.json`: referenced from BB_FAT16_CHAIN_CHECK/README.md
- `SELFTEST.txt`: referenced from bb_repo_phase2_v1.py, docs/REPO_HISTORY_INDEX.md, docs/REPO_PHASE2_POLICY.md, scripts/repo_phase2_hygiene.py

