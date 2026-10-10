# v49e – validated exception-frame PC capture

This restores the exact v49c naked-entry calling convention, passing
`EXC_RETURN`, the selected SP, and both raw SPs into a regular C helper.
The helper decodes the **basic** frame for EXC_RETURN bit 4 set and extended
frame for bit 4 clear, then validates xPSR.T and restricts the captured PC
to ARM executable XIP or SRAM regions. It reports rejection totals. It does
not modify JIT-generated code or the DOS PIT/PIC.

Use `python .\v49e-frame-safe\install_v49e.py --blitzbus C:\blitzBUS --check`
then `--apply`. Use `--restore` to roll back to the exact original header.

Note: capturing per-sample PCs in interrupts may still affect benchmark
speed. Non-JIT region percentages are only meaningful for **valid samples**.
The JIT lookup after a flush can miss PCs from overwritten JIT code; do not
assume unmapped means outside JIT execution.

## Repeated benchmark comparison

Without changing or reflashing the firmware, run 3DBENCH at least three times
from DOS and record each program-reported FPS, along with clock/display and
profiling settings. Ideally compare against three runs on a separately
flashed unchanged v48 baseline under identical conditions. Report median and
range; do not treat a single peak as a code-generation speed improvement.
