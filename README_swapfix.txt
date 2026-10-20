BB_SWAP_STACK_V2 + BB_DOS622_PERF_V1 (extract over C:\blitzBUS, rebuild):
* V1 (static swap buffers) took ~1.2 KiB of SRAM; RAM was already 99.5%
  used and the heap ran out at boot (crash right after LCD clear). Reverted.
* sd_boot/bb_sd_boot.c: the B: live swap checks the image with a 32-byte
  BPB read + 2-byte signature read instead of a 512-byte stack buffer
  (no extra SRAM, ~480 bytes less stack under FatFs on core 0).
* sd_boot/bb_dos622_hdd_sd_v1.inc, bb_dos622_sd.inc: fast seek, batched
  syncs, 12.5 MHz (unchanged from blitzBUS_sdperf).
