# blitzBUS compatibility pass

A structured run of `dos_bench` (PhilsComputerLab DOS Benchmark Pack 1.6,
menu `DOSBENCH.BAT`) on the Pico Plus 2. The pack covers every DOS extender
family that matters, so one pass gives a map of what works, what fails, and
why.

## How to run

One boot per test, so each log covers exactly one program:

```powershell
cd C:\blitzBUS
Get-ChildItem Env:BB_* | Remove-Item
$env:BB_DPMI = '1'; $env:BB_DPMI_DIRECT = '2'
.\bb.bat boot -AllowOverride
```

In DOS: `cd \DOS_BENCH` (wherever the pack is on the image), `DOSBENCH`, pick
the menu key. Let the program run to its result screen or for about 3 minutes,
then end the session. Keep the console log and the ELF of the run.

**What to record per test:** the menu key, whether it starts, whether it
finishes, the result it shows (fps, score, or a photo of the LCD), and how the
log ends (normal, `guest stopped`, crash record after reboot).

**Second pass, only for tests that fail with the host:** the same test with
`$env:BB_DPMI = '0'`. Then DOS/4GW and CWSDPMI use their own mode switching
instead of the blitzBUS DPMI host. That separates host problems from CPU
problems.

## Test matrix

Status: **ok** = runs and finishes, **partial** = starts but fails later,
**fail** = doesn't start, **n/a** = needs something blitzBUS doesn't have.
"Expected" is the prediction from the binaries and the current feature set.

| Key | Program | Family | Video | Exercises | Expected | Result |
|---|---|---|---|---|---|---|
| 1 | 3DBench 1.0 | real mode | 13h | 16-bit JIT, VGA | ok | |
| 2 | 3DBench 1.0c | real mode | 13h | same, faster variant | ok | |
| 3 | Chris's 3D Benchmark | DJGPP / CWSDPMI | 13h | **DPMI host with a second extender** | partial | |
| 4 | Chris's 3D 640x480 | DJGPP / CWSDPMI | VESA | VBE | n/a (no VBE) | |
| 5 | PC Player Benchmark | DOS/4GW | 13h | DOS/4GW, already verified | ok | |
| 6 | PC Player 640x480 | DOS/4GW | VESA | VBE | n/a (no VBE) | |
| a | Doom, min. details | DOS/4GW | 13h | DOS/4GW, sound, timer | ok? | |
| b | Doom, max. details | DOS/4GW | 13h | same | ok? | |
| c | Quake timedemo | DJGPP / CWSDPMI | 13h | DJGPP + **x87** | fail (x87) | |
| d | Quake 360x480 | DJGPP / CWSDPMI | Mode X | unchained VGA | fail | |
| e | Quake 640x480 | DJGPP / CWSDPMI | VESA | VBE | n/a (no VBE) | |
| k | System Information 8.0 | real mode | text | CPU/BIOS probes | ok? | |
| l | Landmark 6.00 | real mode | text | timing loops | ok | |
| m | TOPBENCH 3.8 | real mode | text | timing loops, PIT | ok | |
| n | Speedsys 4.78 | real mode | text/VGA | CPU, cache, memory probes | partial? | |
| s | CHKCPU | real mode | text | CPUID / 386 detection | ok? | |
| t | CACHECHK | real mode | text | cache timing | ok? | |
| u | MTRRLFBE | DJGPP / CWSDPMI | VESA LFB | MTRR, VBE LFB | n/a | |
| v | FASTVID | DOS/4GW | VESA LFB | VBE LFB, MTRR | n/a | |

## Harness pre-screen (2026-11-04)

The PC harness runs the same blitz86 core, JIT (V120 + V122 v4) and DPMI host
as the firmware, with its own DOS and BIOS emulation. Each program ran 15–25
million instructions with `--dpmi --irq --pj`. This finds CPU, JIT and host
problems; DOS, BIOS and timing details still need the Pico.

| Key | Program | Harness result |
|---|---|---|
| 1 | 3DBench 1.0 | **"Packed file is corrupt"**: EXEPACK bug, program loaded below 64 KB. On the Pico: try `LOADFIX 3DBENCH` if it appears there too. |
| 2 | 3DBench 1.0c | runs (no errors to the limit) |
| 3 | Chris's 3D (DJGPP) | **runs on the blitzBUS DPMI host**; 0507h unsupported, tolerated |
| 5 | PC Player (DOS/4GW) | runs |
| a | Doom min. (DOS/4GW) | **runs: timedemo renders** (status bar and palette visible); 0A00h unsupported, tolerated |
| c | Quake (DJGPP) | runs, but looks for `emu387.dxe`: **detects no FPU** |
| k | SysInfo 8 | runs |
| l | Landmark 6 | runs |
| m | TOPBENCH | runs |
| n | Speedsys | runs; "Cannot allocate 4 MB of XMS memory" (needs HIMEM.SYS), warning only |
| s | CHKCPU | **stops: `66 9C`/`66 9D` (PUSHFD/POPFD) unsupported in real mode** |
| t | CACHECHK | "Timer messed up!", then **divide error**; may be the harness's instruction-clocked PIT |

**Findings to fix, by reach:**
1. **Real-mode PUSHFD/POPFD** (`66 9C`, `66 9D`). The standard 486/CPUID
   detection toggles AC or ID in EFLAGS this way; many programs and extenders
   do it at start-up. A blitz86 gap, the same on the Pico.
2. **FPU detection for DJGPP:** Quake decides there's no coprocessor. Check
   what blitz86 answers to FNINIT/FNSTSW and CR0.ET, and which x87 path is
   active on the firmware (see ROADMAP).
3. **Timer-based measurements** (CACHECHK): verify on the Pico before
   changing anything.
4. **XMS:** whether the Pico's DOS 6.22 loads HIMEM.SYS (Speedsys, and
   extenders that prefer XMS).
5. **DPMI 0507h** (page attributes, DJGPP null-page protection): answering
   success as a no-op would be harmless; low priority, it's tolerated.

## What each family tests

- **Real mode** (1, 2, k–n, s, t): the 16-bit JIT, BIOS services, PIT and
  timing. CPU detection tools (k, n, s) report what blitz86 claims to be;
  wrong answers there are worth fixing because games use the same probes.
- **DOS/4GW** (5, a, b): the path Descent uses. PC Player is known good.
  **Doom is the main new test**: a second large DOS/4GW game with sound.
- **DJGPP / CWSDPMI** (3, c): CWSDPMI is only loaded when no DPMI host is
  present, so with `BB_DPMI=1` DJGPP programs use **the blitzBUS host
  directly**. That's the untested "phase D" of the DPMI work: different
  function mix (for example 0506h, 0A00h are unsupported today), different
  memory layout, possibly page locking and exception handling.
- **VESA** (4, 6, e, u, v): blitzBUS's video BIOS handles mode 3 and 13h only.
  These should fail cleanly ("no VESA"), not hang. A hang is a bug.

## Known gaps going in

- **No VBE**, so no 640x480 or linear framebuffer modes.
- **Unchained VGA (Mode X)** is unverified.
- **x87:** blitz86 executes x87 instructions in C (`[bb386-x87] c-executed=`
  in the logs). Quake needs more than Descent did (FSQRT, transcendentals,
  m32/m64 stores, see ROADMAP); expect it to stop at the first missing one.
- **DPMI host:** functions 0506h and 0A00h answer "unsupported" (DOS/4GW
  copes; DJGPP may not).

## After the pass

Each failure gets one line in the matrix with its cause from the log: the
missing BIOS function, DPMI function or instruction. The fixes are ranked by
how many programs they unblock, not by test order.
