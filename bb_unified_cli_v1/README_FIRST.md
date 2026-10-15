# blitzBUS — Unified command interface V1

This package **implements**, rather than merely documents, the commands shown in the earlier cleanup conversation:

```powershell
.\bb.bat dos boot
.\bb.bat dos verify
.\bb.bat dos diagnose
.\bb.bat cpu test
.\bb.bat tools list
.\bb.bat tools audit
```

## Scope

- Updates exactly two paths: `bb.bat` and new `scripts/bb_cli.py`.
- Preserves the existing five `bb.bat` routes (`install`, `upgrade`, `restore`, `build`, `run`) without changing their code.
- Does **not** edit, build or flash firmware during installation; does not access COM5 or touch SD/disk images.
- Installs via `BB_UNIFIED_CLI_V1/install.py`, which verifies the current legacy `bb.bat` (LF and CRLF accepted), saves its **exact original bytes** to `backups/bb_unified_cli_v1_state/`, and supports rollback. The backup stays in the Git-ignored `backups/` folder.
- The command itself `dos boot` **will build/flash unless** you pass `-NoBuild -NoFlash` or test with `--dry-run`. It invokes the existing EXPERIMENTAL `scripts/bb_live_run_dos622_irqtrial.ps1` runner. Guest IRQ0 one-shot is OFF by default and still requires separate arming. Avoid two processes owning COM5.
- `cpu test` runs script/parser/installer **synthetic self-tests**. It does **not** compile or run the x86 CPU smoke tests and does not certify 386/486 correctness.
- `cpu audit` reads source and writes derived `logs/cpu-readiness.md` and `.json` as the existing analyzer already does.

## Install on your current cleanup branch

Download `BLITZBUS_UNIFIED_BB_COMMANDS_V1.zip` to Downloads. Extract the ZIP into the repository so it creates a **new folder** `C:\blitzBUS\BB_UNIFIED_CLI_V1\` (no existing repo file overwritten by extraction):

```powershell
cd C:\blitzBUS
Expand-Archive "$HOME\Downloads\BLITZBUS_UNIFIED_BB_COMMANDS_V1.zip" C:\blitzBUS -Force

python .\BB_UNIFIED_CLI_V1\install.py selftest
python .\BB_UNIFIED_CLI_V1\install.py probe
python .\BB_UNIFIED_CLI_V1\install.py apply
python .\BB_UNIFIED_CLI_V1\install.py verify
```

If probe reports that `bb.bat` differs from the baseline, **do not overwrite** it; share the error and the current `bb.bat` file. An unrelated change may need merging first.

## Verify the new commands without changing the Pico

```powershell
.\bb.bat help
.\bb.bat dos boot --dry-run
.\bb.bat dos verify
.\bb.bat dos diagnose
.\bb.bat cpu test
.\bb.bat tools list
.\bb.bat tools audit
```

`dos diagnose` reads the **newest** raw log under `logs/`; specify an individual log with `--log C:\blitzBUS\logs\bb-live-...-console.txt` if needed.

`cpu test` runs `bb_cpu_readiness_v1.py selftest` plus RM0/RM1/RM2/RM3/PM0 installer self-tests. If you need the quick parser-only test, use `bb.bat cpu test --quick`.

`tools run` passes arguments to an installed named tool via the existing `scripts/bb_repo_tools.py` helper; it does not silently choose between ambiguous basenames.

## Actual hardware boot (only when ready)

```powershell
.\bb.bat dos boot -MicroDOS C:\microDOS -Blitz86 C:\blitz86_v2 -Port COM5 -Seconds 0 -ConsoleView Screen
```

If firmware is already built and flashed, use `-NoBuild -NoFlash`. Back up `DOS622_HDD.IMG` before starting any installer inside DOS.

## Commit only the intended two files

After `apply` and `verify` pass:

```powershell
git diff -- bb.bat
git status --short
git add -- bb.bat scripts/bb_cli.py
git diff --cached --check
git diff --cached --name-status
git commit -m "feat: add unified DOS CPU and tools command interface"
git push
```

Do **not** run `git add -A`, which could stage unrelated disk image changes or the extracted installation package. Leave `BB_UNIFIED_CLI_V1/` untracked or delete that package folder only **after** the CLI is committed and working, if you no longer need its installer/restore method.

## Restore original `bb.bat` before committing

```powershell
python .\BB_UNIFIED_CLI_V1\install.py verify
python .\BB_UNIFIED_CLI_V1\install.py restore
```

Then inspect `git status --short`. The restore refuses to operate if either installed file has been edited since `apply`, preventing silent loss of user changes.

## Validation performed

Python 3.13 syntax check; synthetic LF and CRLF apply/verify/restore; tamper detection; exact original byte restore; help and DOS log diagnosis using fake logs. **Windows `cmd.exe`, Pico flashing, and real MS-DOS command execution are not available in the test environment**; these must be confirmed on the user's Windows computer.
