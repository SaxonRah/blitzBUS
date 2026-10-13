blitz86 RP2350 — memory RCL/RCR by one A/B experiment
====================================================

Artifacts:
  bb_rcx_mem1_ab_v1.py      Full reversible source-file installer/controller
  RCXTEST.COM               64-case 8086-compatible DOS test executable
  RCXTEST.asm               Complete generated source for RCXTEST.COM
  build_rcxtest.py          Rebuild RCXTEST.COM with GNU assembler on host

Install script into C:\blitzBUS. Before installing, restore former audit
layers IN THIS ORDER if currently installed:

  python .\bb_audit_sram_flash_fix_v1.py restore
  python .\bb_thumb2_form_and_lookup_audit_v1.py restore

(Only run those restores when their respective layers are actually present.)
Leave eager dead-stub unchaining ON. Confirm:

  python .\bb_deadstub_unchain_ab_v2.py verify

Run:

  python .\bb_rcx_mem1_ab_v1.py selftest
  python .\bb_rcx_mem1_ab_v1.py probe
  python .\bb_rcx_mem1_ab_v1.py apply
  python .\bb_rcx_mem1_ab_v1.py set on
  python .\bb_rcx_mem1_ab_v1.py verify

The installer changes only C:\blitz86_v2\src\jit.c, and keeps the exact
original as jit.c.bb-rcx-mem1-ab-original.bak. It deliberately refuses to
install if prior profiler source markers are present. No git patches.

Build/flash with BB_CODE_KB=232 and the existing proven environment:

  $env:BB_HOT_THRESHOLD="32"
  $env:BB_EVICT_CHUNK="4096"
  $env:BB_EVICT_ROOM="2048"
  $env:BB_NO_CHAIN="0"
  $env:BB_BBUF="1"
  $env:BB_CODE_KB="232"
  $env:BB_CPU="286"
  $env:BB_SD_BOOT="1"
  $env:BB_LCD_PERI_HZ="150000000"
  $env:BB_LCD_SPI_HZ="75000000"
  $env:BB_LCD_LACE="1"

  powershell -NoProfile -ExecutionPolicy Bypass -File `
    .\scripts\bb_live_run.ps1 `
    -MicroDOS C:\microDOS `
    -Blitz86 C:\blitz86_v2 `
    -Port COM5 `
    -Seconds 180

Copy RCXTEST.COM to the DOS C: drive (e.g. C:\BENCH) using your normal
SD image management method. In the Pico DOS console:

  C:
  CD \BENCH
  RCXTEST
  T2ECPU
  3DBENCH

RCXTEST will print 'RCXTEST PASS 64 / 64' and return exit code 0 on pass,
or 'RCXTEST FAIL case NN' on a case mismatch, returning exit code 1.
All 64 cases check the destination memory value and CF/OF preservation.

For a valid A/B, compile and flash BOTH on and off builds and run the same
test and benchmark. Memory RCL/RCR ON could be slower from code size.

To return to OFF (only change compile-time flag; rebuild required):
  python .\bb_rcx_mem1_ab_v1.py set off
To restore the original source byte-for-byte:
  python .\bb_rcx_mem1_ab_v1.py restore

Important: Software arithmetic and install/restore tests passed. Neither
RP2350 linking nor guest correctness is yet proven by these files.
