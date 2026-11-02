# blitzBUS roadmap

## Future: a native Thumb-2 compiler for DOS

- **Compile in DOS, run natively.** A compiler running under blitzBUS that
  emits Thumb-2 code for the RP2350, plus a small loader and calling
  convention, so software built inside DOS runs as native code on the Pico at
  full speed instead of going through blitz86.
- **Later: compile DOS itself natively.** Build the DOS kernel and core
  components to Thumb-2, so the operating system layer runs natively and only
  legacy x86 programs are emulated.
- **Questions to settle first:**
  - the interface between native code and the emulated x86 state (registers,
    memory map, interrupts, DOS calls);
  - protecting the emulator from faulty native code;
  - where native code lives (SRAM vs PSRAM: the capacity and churn lessons from
    V105-V112 apply);
  - which compiler to adapt (for example, a small C compiler with an ARM
    back end).
