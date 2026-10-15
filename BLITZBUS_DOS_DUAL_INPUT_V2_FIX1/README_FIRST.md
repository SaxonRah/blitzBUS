# blitzBUS DOS Dual Color Keyboard V2 — COM5 forwarding fix 1

## Symptom

V2 displayed `Sent N characters + Enter` after writing the per-session `.evt` files, **not after COM5 acknowledged the input**. The V2 generated PowerShell runner attempted to reconstruct synthetic `ConsoleKey` objects for printable command-line input. If that handoff failed, V2 provided no reliable indication to the color window.

FIX1 routes ordinary printable LINE input, Enter, and Backspace directly through the **existing sole COM5 owner's** `SerialPort.Write` (one event per main-loop iteration, preserving the existing pacing), while preserving the existing original special-key and disk-swap handling. It also publishes per-event COM5-owner ACK data back to the color window.

**Three stages have different meanings:**

- `QUEUED`: the color window wrote the keyboard event files.
- `FORWARDED to COM5`: the owner called the serial write successfully through the final queued event. This **does not guarantee** the guest accepted or displayed all characters.
- DOS screen `C:\>DIR`, or `[bb-v23] KEY` / `[bb622-key-ab]` in the RAW log: guest-level evidence that the character was consumed.

If the queue stalls, the input strip warns after 5 seconds. If an event is rejected, the owner preserves the failed `.bad` input event and writes `owner_error.txt` in the session folder for diagnosis. No event is silently discarded on a parse or COM5 failure.

## Apply (close active DOS session first)

Extract `BLITZBUS_DOS_DUAL_INPUT_V2_FIX1.zip` to `C:\blitzBUS`.

```powershell
cd C:\blitzBUS
python .\BLITZBUS_DOS_DUAL_INPUT_V2_FIX1\install_dual_input_fix1.py selftest
python .\BLITZBUS_DOS_DUAL_INPUT_V2_FIX1\install_dual_input_fix1.py probe
python .\BLITZBUS_DOS_DUAL_INPUT_V2_FIX1\install_dual_input_fix1.py apply
python .\BLITZBUS_DOS_DUAL_INPUT_V2_FIX1\install_dual_input_fix1.py verify
python .\BLITZBUS_DOS_DUAL_INPUT_V2\install_dual_input.py verify
.\bb.bat dos verify
```

`probe` checks the SHA hashes recorded when V2 was installed and refuses to overwrite locally changed files. Apply saves exact originals in `backups/bb_dos_dual_input_v2_fix1_state`, updates V2's SHA manifest, and changes only the V2 launcher and color keyboard scripts. It does **not** change `bb_live_run_dos622_irqtrial.ps1`, `bb622_descent_color_host.ps1`, the V1 launcher or V1 manifest, DOS or firmware, or any disk image. All V1/V2 verification should remain valid.

Start the console:

```powershell
.\bb.bat dos boot -NoBuild -NoFlash -Seconds 0
```

Click the **color terminal**, type `DIR`, and press Enter. Check that the input strip advances from `QUEUED` to `FORWARDED`. Wait for DOS to echo and show the directory listing. The RAW PowerShell window should show a new `[bb-dual-v2-fix1] FORWARDED to COM5 ... key=13 code=13` line at Enter.

## If input still does not reach DOS

Do **not** reflash and do **not** press Ctrl+U. While the console is running, in a separate PowerShell session or after ending it:

```powershell
cd C:\blitzBUS
Get-ChildItem .\logs -Directory -Filter 'bb-dual-input-v2-*' |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 3 FullName,LastWriteTime
```

Inspect the **most recent** folder (paste the real full name; never delete it):

```powershell
$folder = 'PASTE_LATEST_SESSION_FOLDER'
Get-ChildItem -LiteralPath $folder -Force | Select-Object Name,Length,LastWriteTime
Get-Content -LiteralPath (Join-Path $folder 'owner_ack.txt') -ErrorAction SilentlyContinue
Get-Content -LiteralPath (Join-Path $folder 'owner_error.txt') -ErrorAction SilentlyContinue
```

Look for `[bb-dual-v2-fix1]` and `[bb-v23] KEY` in the most recent `logs\bb-live-*-console.txt` raw log. Failed events are left as `.bad` for diagnosis. There is no need to send fresh IRQ0 trials.

## Roll back FIX1 only

Close the DOS session first, then:

```powershell
python .\BLITZBUS_DOS_DUAL_INPUT_V2_FIX1\install_dual_input_fix1.py restore
python .\BLITZBUS_DOS_DUAL_INPUT_V2\install_dual_input.py verify
```

This restores the original V2 launcher, color keyboard viewer, and V2 manifest byte-for-byte. The earlier V1 and V2 state/rollback files remain preserved.

## Validation scope

The package was tested using a synthetic install/apply/verify/restore fixture, generated runner marker verification, two newline formats, and Python compilation. **Live Windows PowerShell and COM5 transmission have not yet been tested here.**
