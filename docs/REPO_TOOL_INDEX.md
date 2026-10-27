# blitzBUS tool index (phase 2)

Generated from the local tracked checkout. This is a navigation catalog, not a declaration that every tool is currently maintained.

**IMPORTANT:** Root-level installer scripts and the `.bb_*_state` directories remain at their original paths. Changing their locations could invalidate checksum manifests, sibling imports and rollback scripts.

## Key known working entry points

- `bb.bat` — legacy build/install/run entry point.
- `scripts/install_live.py` — installs the live integration into the microDOS build.
- `scripts/bb_live_run_dos622_irqtrial.ps1` — experimental DOS 6.22 / IRQ0 runner; *not* a known-good IRQ0 release.
- `bb622_lineage_verify_v13.py verify` — installed SHA lineage.
- `bb622_irq0_trial_v1.py verify` — latest one-shot IRQ0 patch-source verification.
- `bb622_logview_pic.py` — passive, copyable live-log viewer.

## Root-level Python tools

111 root Python scripts detected in tracked checkout.

### CPU / JIT investigation (10)

- `bb_jit_tune.py`
- `bb_tier1h.py`
- `bb_tier1i.py`
- `bb_tier1j.py`
- `bb_tier1k.py`
- `bb_tier1l.py`
- `bb_tier2a_analyze.py`
- `bb_tier2b_analyze.py`
- `bb_tier2c_install.py`
- `bb_tier2c_repair.py`

### diagnostic / analysis (12)

- `bb622_console_report.py`
- `bb622_descent_diagnose.py`
- `bb622_dos_disk_audit_v3.py`
- `bb622_hdd_audit.py`
- `bb622_irq0_report.py`
- `bb622_logview.py`
- `bb622_logview_pic.py`
- `bb622_media_audit.py`
- `bb_dos622_hdd_image_audit.py`
- `bb_dos622_log_audit.py`
- `bb_jit_reuse_diag.py`
- `verify_c_probe.py`

### lineage verification (13)

- `bb622_lineage_verify_v11.py`
- `bb622_lineage_verify_v12.py`
- `bb622_lineage_verify_v13.py`
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

### media / disk utility (5)

- `bb622_descent_swap_c11.py`
- `bb622_descent_swap_c11_v2.py`
- `bb_dos622_image.py`
- `bb_fat12_import_v1.py`
- `bb_make_dos622_hdd_v1.py`

### other historical tool (10)

- `bb622_pic_session_trial_v1.py`
- `bb_cpu_readiness_v1.py`
- `bb_dos622_stage3_v1.py`
- `bb_eviction_tune.py`
- `bb_psram_layout_v1.py`
- `bb_retranslation_promotion.py`
- `build_rcxtest.py`
- `c11_swap_lcd_tests.py`
- `test_keyb92_c.py`
- `test_sram_floor.py`

### versioned installer / rollback (61)

- `bb622_boot_eject_v1.py`
- `bb622_descent_swap_v1.py`
- `bb622_irq0_trial_v1.py`
- `bb622_pic_host_control_v1.py`
- `bb622_pic_pending_v1.py`
- `bb622_swap_ack_v2.py`
- `bb622_swap_ack_v3.py`
- `bb622_swap_controls_fix_v1.py`
- `bb_386_pm0_include_fix1.py`
- `bb_386_pm0_v1.py`
- `bb_386_rm0_v1.py`
- `bb_386_rm1_v1.py`
- `bb_386_rm2_flash_sram_v1.py`
- `bb_386_rm2_v1.py`
- `bb_386_rm3_v1.py`
- `bb_audit_sram_flash_fix_v1.py`
- `bb_chain_audit.py`
- `bb_chain_exit_split_v1.py`
- `bb_chain_exit_split_v2.py`
- `bb_deadstub_unchain_ab.py`
- `bb_deadstub_unchain_ab_v2.py`
- `bb_dos622_atbios_v1.py`
- `bb_dos622_boot_diag_v1.py`
- `bb_dos622_color_cells_v1.py`
- `bb_dos622_ega_info_v1.py`
- `bb_dos622_floppy_b_v1.py`
- `bb_dos622_hdd_v1.py`
- `bb_dos622_hdd_v2.py`
- `bb_dos622_heap_rescue_v1.py`
- `bb_dos622_ipl_v1.py`
- `bb_dos622_irq0_isolation_v1.py`
- `bb_dos622_keyb92_v1.py`
- `bb_dos622_keyba2_v1.py`
- `bb_dos622_keyba2_v2.py`
- `bb_dos622_keyba2_v3.py`
- `bb_dos622_lcd_text_v1.py`
- `bb_dos622_lcd_text_v2.py`
- `bb_dos622_p61_refresh_v1.py`
- `bb_dos622_printer17_v1.py`
- `bb_dos622_rtc1a_v1.py`
- `bb_dos622_screen_clear_v1.py`
- `bb_dos622_sd_clockfix_v1.py`
- `bb_dos622_serial14_guard_v1.py`
- `bb_dos622_sram_floor_v1.py`
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
- `bb_exit_hotspot_v1.py`
- `bb_fallback_opcode_profile_v1.py`
- `bb_int_vector_profile_v1.py`
- `bb_make_dos622_clean_console.py`
- `bb_rcx_mem1_ab_v1.py`
- `bb_thumb2_form_and_lookup_audit_v1.py`

## Script directory entry points

- `scripts/bb622_descent_color_host.ps1`
- `scripts/bb622_irq0_trial.ps1`
- `scripts/bb622_pic_toggle.ps1`
- `scripts/bb622_request_disk.ps1`
- `scripts/bb622_request_disk_v3.ps1`
- `scripts/bb622_request_media.ps1`
- `scripts/bb_dos622_color_host.ps1`
- `scripts/bb_dos622_screen_host.ps1`
- `scripts/bb_dos622_swap_color_host.ps1`
- `scripts/bb_jit_probe.ps1`
- `scripts/bb_live_run.ps1`
- `scripts/bb_live_run_dos622.ps1`
- `scripts/bb_live_run_dos622_boot_eject.ps1`
- `scripts/bb_live_run_dos622_color.ps1`
- `scripts/bb_live_run_dos622_controls.ps1`
- `scripts/bb_live_run_dos622_controls_v3.ps1`
- `scripts/bb_live_run_dos622_descent.ps1`
- `scripts/bb_live_run_dos622_irqtrial.ps1`
- `scripts/bb_live_run_dos622_pic_control.ps1`
- `scripts/bb_live_run_dos622_swap.ps1`
- `scripts/bb_pc_report.ps1`
- `scripts/bb_run.ps1`
- `scripts/bb_vga_run.ps1`
- `scripts/bridge_probe.ps1`
- `scripts/install_jit_probe.py`
- `scripts/install_live.py`
- `scripts/install_overlay.py`
- `scripts/repo_audit.py`

## History and archive policy

- Installer versions are a **chronology**, not automatically duplicates.
- `milestones/` and every rollback state directory are preserved untouched.
- The test-output archive consists only of individually reference-checked files.
- Do not run `git add -A` with writable tracked DOS images.

