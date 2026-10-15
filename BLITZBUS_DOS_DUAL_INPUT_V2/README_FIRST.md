# blitzBUS DOS 6.22 — dual-console keyboard V2

This upgrades the working **Dual Console V1** setup. The original interactive
PowerShell window becomes a raw diagnostic log, and the automatically opened
VGA/CP437 DOS window becomes the **only interactive keyboard window**.

## How it works

```text
                    [ COLOR VGA WINDOW ]
                     80 x 25 DOS screen
                     row 26: INPUT [LINE]>...
                        |       ^
                   keypress events / editor
                        |
          local, atomic, ordered .evt files
                        |
                        v
 [ ORIGINAL POWERSHELL / RAW LOG ]
     protected DOS runner copied (transient) with key-queue reader
     only owner of COM5 -> Pico -> MS-DOS 6.22
     writes exact [bb622-cells] raw capture -> VGA window follows
```

- DOS screen rows 0–24 are drawn with **the original color renderer**.
- The input field stays on row 26, **outside** the renderer's screen area.
  Row 25 is a divider, row 27 is a status/help line.
- **LINE mode (default):** edit the text locally, then Enter sends the whole
  command plus DOS Enter. Backspace, Delete, Left, Right, Home, End, Escape
  are local editing keys; characters are **not** sent before Enter.
- **F2:** toggle **LIVE mode**. Each press goes directly to the guest via the
  event queue; use for interactive installers, confirmation keys, games,
  and arrow/navigation keys. F2 is reserved by the host as the toggle.
- **F9**, **Alt+G** / **Ctrl+G**: pass through to the original protected
  DOS floppy picker; A/B/disk digit flow remains immediate.
- **Ctrl+X:** stop original runner and close the color window after it exits.
- **Ctrl+]** statistics, **Ctrl+Y** pending-only PIC probe, and **Ctrl+U**
  one-shot IRQ0 trial remain available **as intentional, immediate controls**;
  *do not press Ctrl+U during normal use*, since the IRQ0 failure remains
  unresolved. Normal guest IRQ0 delivery is still suppressed by firmware.
- No second serial client. The new color input window never opens COM5.
- This **does not** alter the Pico firmware, disk images, guest memory,
  protected DOS runner source or original color renderer.

### One-time upgrade

Extract `BLITZBUS_DOS_DUAL_INPUT_V2.zip` into `C:\blitzBUS`, retaining the
`BLITZBUS_DOS_DUAL_INPUT_V2` directory. From PowerShell:

```powershell
cd C:\blitzBUS
python .\BLITZBUS_DOS_DUAL_INPUT_V2\install_dual_input.py selftest
python .\BLITZBUS_DOS_DUAL_INPUT_V2\install_dual_input.py probe
python .\BLITZBUS_DOS_DUAL_INPUT_V2\install_dual_input.py apply
python .\BLITZBUS_DOS_DUAL_CONSOLE_V1\install_dual_console.py verify
.\bb.bat dos verify
```

The upgrade changes only:

- `scripts/bb_dos_dual_launch.py` (V1 entrypoint delegates to V2)
- `backups/bb_dos_dual_console_v1_state/manifest.json` (records the new
  SHA-256 of the V1 launcher, so the original V1 `verify` still passes)
- Adds `scripts/bb_dos_dual_launch_v2.py`
- Adds `scripts/bb622_color_keyboard_v2.ps1`
- Adds `backups/bb_dos_dual_input_v2_state/` (byte-exact V1 backups)

This **does not edit** `scripts/bb_cli.py`, protected IRQ0 state manifests,
DOS images, or original `scripts/bb_live_run_dos622_irqtrial.ps1`.

### Start both windows, without rebuilding or reflashing

```powershell
.\bb.bat dos boot -NoBuild -NoFlash -Seconds 0
```

For a 180-second diagnostic session:

```powershell
.\bb.bat dos boot -NoBuild -NoFlash -Seconds 180
```

The main PowerShell defaults to `-ConsoleView Raw` so all diagnostics and
hex cell events are logged verbatim; focus the **new VGA window** to type.
No preexisting firmware or DOS image is changed by this launcher, although
DOS's normally mounted C: drive can perform guest-initiated writes.

If Windows Terminal cannot give the color window 29 visible rows, manually
make it at least 80 columns wide and 29 lines high to expose the separate
`INPUT>` field. The application requests this window height automatically.

Use `-NoColorWindow` to return to single-window legacy keyboard semantics.
Do **not** combine `-NoInput` with dual keyboard mode; the launcher refuses it.

### Restore V1 exactly

Close all running sessions first:

```powershell
python .\BLITZBUS_DOS_DUAL_INPUT_V2\install_dual_input.py verify
python .\BLITZBUS_DOS_DUAL_INPUT_V2\install_dual_input.py restore
python .\BLITZBUS_DOS_DUAL_CONSOLE_V1\install_dual_console.py verify
.\bb.bat dos verify
```

The V1 launcher and its V1 manifest are restored byte for byte.

### Limitations

- The guest still owns normal DOS line echo, which appears *after* a line is
  submitted. The editable `INPUT>` line is a separate host-side composition
  buffer; it does **not** alter DOS keyboard-driver semantics.
- One key event is sent by the original runner each polling iteration; long
  submitted lines may take a short moment to finish sending to DOS.
- This package has installer and source-guard self-tests, but **no Windows
  PowerShell/COM5 runtime validation in this environment**. Test first with
  `DIR`, then `CLS`, then normal DOS commands. If the input window is not
  responsive, stop and use `-NoColorWindow` or `restore`.
