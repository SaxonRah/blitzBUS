# blitzBUS v0.5.3 — bridge probe runner repair

Replaces `scripts/bridge_probe.ps1` only. No Pico changes.

Two fixes:
- The previous multi-source `cl.exe` command used `/Fo"C:\...\"` which could swallow the compiler source arguments. Compile each C file separately to its own explicit `.obj`, then link explicitly.
- Capture stdout and stderr using `Start-Process` so Windows PowerShell 5.1 does not stop on native stderr as a `NativeCommandError`.

Open ordinary PowerShell:

```powershell
cd C:\blitzBUS
Unblock-File .\scripts\bridge_probe.ps1
.\scripts\bridge_probe.ps1 -MicroDOS C:\microDOS -Blitz86 C:\blitz86_v2
```

Logs: `build-host\bridge-probe-msvc.log`. If this detects actual C errors, send the new output. This is a host-side CPU-state smoke probe, **not** a DOS JIT integration.
