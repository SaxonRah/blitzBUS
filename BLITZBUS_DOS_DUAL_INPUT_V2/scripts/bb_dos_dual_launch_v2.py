#!/usr/bin/env python3
"""DOS 6.22 dual input V2: raw owner + editable VGA keyboard terminal.

Creates a guarded, per-run COPY of the protected DOS runner in its own
scripts directory so $PSScriptRoot keeps working. Original runner stays byte
exact. The only serial-port owner is the copied DOS runner.
"""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
PROTECTED = ROOT / 'scripts' / 'bb_live_run_dos622_irqtrial.ps1'
VIEWER = ROOT / 'scripts' / 'bb622_color_keyboard_v2.ps1'
COLOR = ROOT / 'scripts' / 'bb622_descent_color_host.ps1'
LOGS = ROOT / 'logs'
TAG = 'BB_DUAL_INPUT_V2'

# Exact body of the existing PS runner's keyboard branch: only the two lines
# below are replaced in a transient per-run copy, not inside the repo source.
ANCHOR = '                if([Console]::KeyAvailable){\n                    $k=[Console]::ReadKey($true)'
REPLACE = r'''                # BB_DUAL_INPUT_V2: only color terminal produces keyboard events.
                $bbV2HaveKey=$false
                if($env:BB_DUAL_V2_INPUT_DIR){
                    $bbV2Next=Get-ChildItem -LiteralPath $env:BB_DUAL_V2_INPUT_DIR -Filter 'k_*.evt' -File -ErrorAction SilentlyContinue |
                        Sort-Object Name | Select-Object -First 1
                    if($null -ne $bbV2Next){
                        try {
                            $bbV2Text=[System.IO.File]::ReadAllText($bbV2Next.FullName,[System.Text.Encoding]::ASCII).Trim()
                            if($bbV2Text -notmatch '^(\d{1,4}),(\d{1,3}),(\d{1,4})$') { throw 'Invalid key event syntax' }
                            $bbV2Num=[int]$Matches[1]
                            $bbV2Modifiers=[int]$Matches[2]
                            $bbV2Char=[int]$Matches[3]
                            if($bbV2Num -gt 255 -or $bbV2Modifiers -gt 7 -or $bbV2Char -gt 255){ throw 'Invalid key range' }
                            $k=[pscustomobject]@{
                                Key=[System.ConsoleKey]$bbV2Num
                                KeyChar=[char]$bbV2Char
                                Modifiers=[System.ConsoleModifiers]$bbV2Modifiers
                            }
                            $bbV2HaveKey=$true
                        } catch {
                            [System.IO.File]::AppendAllText($log,"[bb-dual-v2] REJECT keyboard event: $($_.Exception.Message)`n")
                        } finally {
                            [System.IO.File]::Delete($bbV2Next.FullName)
                        }
                    }
                } elseif([Console]::KeyAvailable) {
                    $k=[Console]::ReadKey($true)
                    $bbV2HaveKey=$true
                }
                if($bbV2HaveKey){'''


def sha(x: bytes) -> str:
    return hashlib.sha256(x).hexdigest()


def patched_runner(source: bytes) -> bytes:
    bom = b'\xef\xbb\xbf' if source.startswith(b'\xef\xbb\xbf') else b''
    normalized = source[len(bom):].replace(b'\r\n', b'\n')
    marker = ANCHOR.encode('ascii')
    if normalized.count(marker) != 1:
        raise RuntimeError(f'Protected runner has {normalized.count(marker)} expected keyboard anchors; REFUSING to generate modified runner')
    if TAG.encode('ascii') in normalized:
        raise RuntimeError('Protected runner already contains the V2 marker; refusing double patch')
    out = normalized.replace(marker, REPLACE.encode('utf-8'), 1)
    if b'\r\n' in source:
        out = out.replace(b'\n', b'\r\n')
    return bom + out


def run(argv: list[str]) -> int:
    suppress = {'--no-color-window', '-nocolorwindow'}
    no_color = any(x.lower() in suppress for x in argv)
    argv = [x for x in argv if x.lower() not in suppress]
    if not PROTECTED.is_file() or not COLOR.is_file():
        raise FileNotFoundError('Protected DOS runner or original color renderer missing')
    if not VIEWER.is_file():
        raise FileNotFoundError(f'V2 input display missing: {VIEWER}')
    if any(a.lower() == '-noinput' for a in argv) and not no_color:
        raise RuntimeError('-NoInput conflicts with the V2 color keyboard; remove it or use -NoColorWindow')
    if no_color:
        print('[bb-dual-v2] -NoColorWindow: using unmodified single-console runner', flush=True)
        return subprocess.call(['powershell.exe', '-NoProfile','-ExecutionPolicy','Bypass',
            '-File',str(PROTECTED),*argv],cwd=str(ROOT))

    # Full raw diagnostic log remains in original shell. This is the
    # default, rather than Events or Screen which could hide evidence.
    if not any(a.lower() == '-consoleview' for a in argv):
        argv.extend(['-ConsoleView','Raw'])
    LOGS.mkdir(parents=True, exist_ok=True)
    before = {p.name for p in LOGS.glob('bb-live-*-console.txt') if p.is_file()}
    token = uuid.uuid4().hex[:12]
    queue = LOGS / f'bb-dual-input-v2-{token}'
    queue.mkdir()
    # Put transient script next to protected script, not into a temporary
    # folder: the original uses $PSScriptRoot for installers and includes.
    script = ROOT / 'scripts' / f'.bb_dual_v2_runner_{token}.ps1'
    original = PROTECTED.read_bytes()
    patched = patched_runner(original)
    if script.exists():
        raise FileExistsError(f'Unexpected temporary runner collision: {script}')
    script.write_bytes(patched)
    patched_digest = sha(patched)
    childenv = dict(os.environ, BB_DUAL_V2_INPUT_DIR=str(queue))
    cmd = ['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script),*argv]
    runner: subprocess.Popen | None = None
    viewer: subprocess.Popen | None = None
    requested_exit = False

    def ask_runner_to_exit() -> None:
        # The original runner recognizes KeyChar 0x18 as Ctrl+X. This does
        # not open COM5. Use a priority event to avoid executing stale lines.
        event = queue / 'k_000000000000.evt'
        tmp = queue / 'k_000000000000.tmp'
        tmp.write_text('88,4,24', encoding='ascii')
        os.replace(tmp, event)

    try:
        print('[bb-dual-v2] RAW LOG WINDOW: this PowerShell (sole COM5 owner)',flush=True)
        print('[bb-dual-v2] VGA KEYBOARD WINDOW: launches automatically when capture starts',flush=True)
        print('[bb-dual-v2] Keyboard focus belongs in color window, NOT the logger',flush=True)
        print(f'[bb-dual-v2] Protected runner sha256={sha(original)} (source unmodified)',flush=True)
        runner = subprocess.Popen(cmd,cwd=str(ROOT),env=childenv)
        while runner.poll() is None:
            if viewer is None and not requested_exit:
                added=[p for p in LOGS.glob('bb-live-*-console.txt') if p.is_file() and p.name not in before]
                if added:
                    p=max(added,key=lambda q:(q.stat().st_mtime_ns,q.name))
                    vcmd=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',
                        str(VIEWER),'-Log',str(p),'-InputDir',str(queue),'-ParentPid',str(runner.pid)]
                    try:
                        flags = subprocess.CREATE_NEW_CONSOLE if os.name == 'nt' else 0
                        viewer=subprocess.Popen(vcmd,cwd=str(ROOT),creationflags=flags)
                        print(f'[bb-dual-v2] DOS color/input window PID={viewer.pid}; RAW LOG={p}',flush=True)
                    except OSError as exc:
                        print(f'[bb-dual-v2] ERROR: color keyboard window failed to start: {exc}',flush=True)
                        print('[bb-dual-v2] Keyboard unavailable: requesting safe exit; relaunch with -NoColorWindow.',flush=True)
                        ask_runner_to_exit()
                        requested_exit=True
            if viewer is not None and viewer.poll() is not None and not requested_exit:
                print('[bb-dual-v2] VGA keyboard window closed: requesting graceful Ctrl+X exit.',flush=True)
                ask_runner_to_exit()
                requested_exit=True
            time.sleep(.10)
        return runner.wait()
    except KeyboardInterrupt:
        print('[bb-dual-v2] Ctrl+C: please use Ctrl+X in color window for graceful shutdown.',flush=True)
        return 130
    finally:
        # Do not force-terminate either the serial owner or viewer.
        # Only remove the generated script when child has actually exited.
        if runner is None or runner.poll() is not None:
            if script.exists() and sha(script.read_bytes())==patched_digest:
                script.unlink()
        if sha(PROTECTED.read_bytes()) != sha(original):
            print('[bb-dual-v2] WARNING: protected original DOS runner changed unexpectedly',flush=True)
        # Remove only a completely empty per-run queue. Unsent events are
        # preserved for inspection, and unknown/user files are never removed.
        try:
            queue.rmdir()
            print('[bb-dual-v2] Empty input queue cleaned up',flush=True)
        except OSError:
            print(f'[bb-dual-v2] Non-empty input queue preserved: {queue}',flush=True)


if __name__ == '__main__':
    try:
        raise SystemExit(run(sys.argv[1:]))
    except (OSError,RuntimeError,ValueError) as exc:
        print(f'[bb-dual-v2] ERROR: {exc}',file=sys.stderr)
        raise SystemExit(2)
