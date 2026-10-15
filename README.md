# blitzBUS

**blitzBUS** is an RP2350/Pimoroni Pico Plus 2 DOS-machine project that combines the **microDOS** runtime, **blitz86** x86 translation/interpreter, PSRAM, SD-backed disks, and an SPI LCD. The project is under active development; some features and test programs are experimental.

## Current status (October 2026)

- Genuine **MS-DOS 6.22** boots from a writable FAT16 hard-disk image (`DOS622_HDD.IMG`) on the Pico Plus 2.
- The DOS console, color LCD text output, keyboard input, and read-only B: floppy image mounting are working for tested cases.
- The Descent installer reads its first floppy and writes files to C:, but **stalls before prompting for disk 2**.
- PIT channel 0 and the PIC are emulated, but DOS 6.22's regular guest IRQ0 delivery is still disabled. A *single* test IRQ0 reached its handler, after which guest execution entered invalid control flow. **Do not treat the IRQ0 one-shot as a fix or enable continuous IRQ0 delivery.**
- 286 real-mode execution and 386-related smoke tests exist; this is not a claim of complete 386/486 or protected-mode support.

Read [the IRQ0 one-shot experiment](docs/experiments/IRQ0_ONE_SHOT_TRIAL_V1.md) before repeating that diagnostic. A **reboot is required** after an IRQ-related guest-state failure.

## Repository layout

| Path | Role |
| --- | --- |
| `src/` | blitzBUS runtime, emulator integration, VGA/PIT/PIC and DOS BIOS adapters |
| `sd_boot/` | SD-card boot, FAT-backed media, virtual floppy and HDD access |
| `scripts/` | Build/install runners, firmware upload, local diagnostics and utilities |
| `tests/` | Source-level regression and smoke tests |
| `pico/` | RP2350-facing integration |
| `BB_*` tool folders | Historical FAT, disk-image and Descent maintenance utilities; review their README before running |
| `.bb_*_state/`, `.bb622_*_state/` | **Required installer backup/manifest history** for byte-exact verification and rollback; do not casually remove |
| `games/`, `media/`, `dos_bench/` | Historical test media and fixtures; some third-party assets may require separate rights |
| `milestones/` | Historical baselines, not the current build target |

[Repository hygiene and audit instructions](docs/REPOSITORY_CLEANUP.md) distinguish live files from local/generated data and historical backups.

## Building and running

The development environment uses **three separate working trees**:

```text
C:\blitzBUS
C:\microDOS
C:\blitz86_v2
```

`bb.bat` supplies the original project-level `install`, `build`, and `run` entry points. For the most recent DOS 6.22 experiment, inspect `scripts/bb_live_run_dos622_irqtrial.ps1` and its prerequisites first. A typical interactive runner invocation is:

```powershell
cd C:\blitzBUS
powershell -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\bb_live_run_dos622_irqtrial.ps1 `
  -MicroDOS C:\microDOS -Blitz86 C:\blitz86_v2 `
  -Port COM5 -Seconds 0 -ConsoleView Screen
```

The above runner is **experimental**, not a validated stable release. Make sure the Pico is actually flashed with the image you built; a successful compilation alone does not flash hardware. Only one application may own COM5 at a time. Run the sidecar log viewer in a separate window to preserve copyable diagnostics.

## Safety and verification

**Do not remove the installer state directories or rewrite them as part of a tidy-up.** Later installers verify not only the current source SHA, but also the exact prior states and backup bytes. Retain the original installer scripts while these checks are in use.

Disk images are separate from source files. Back up `DOS622_HDD.IMG` before any experiment that writes to C:. Never rewrite, shrink, clean, or reinitialize a working SD image merely to reduce Git size. This repository still contains tracked media and historical disk images; `.gitignore` does not stop Git from tracking changes to files that were already committed.

To audit tracked files and exact duplicate Git blobs locally without modifying anything:

```powershell
python .\scripts\repo_audit.py --root C:\blitzBUS
python .\scripts\repo_audit.py --root C:\blitzBUS --json
```

## Development references

- [Source repository](https://github.com/SaxonRah/blitzBUS)
- [microDOS](https://github.com/SaxonRah/microDOS)
- [Repository cleanup notes](docs/REPOSITORY_CLEANUP.md)

The experimental work is still in progress. Preserve diagnostic logs from a failed boot rather than assuming CPU progress means DOS or a game has made forward progress.
