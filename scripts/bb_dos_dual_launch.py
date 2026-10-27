#!/usr/bin/env python3
"""Two terminal views of one DOS 6.22 session.

The original PowerShell DOS runner stays unchanged and remains the ONLY
COM5 owner. The second process follows the raw log and renders the already
existing CP437/VGA color terminal; it cannot send any guest input.
"""
from __future__ import annotations
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / 'scripts' / 'bb_live_run_dos622_irqtrial.ps1'
FOLLOWER = ROOT / 'scripts' / 'bb622_color_follow.ps1'
LOGS = ROOT / 'logs'


def run(argv: list[str]) -> int:
    suppress_tokens = {'--no-color-window', '-nocolorwindow'}
    no_color = any(x.lower() in suppress_tokens for x in argv)
    # The legacy PowerShell runner doesn't know our color-window flag.
    argv = [x for x in argv if x.lower() not in suppress_tokens]
    if not RUNNER.is_file():
        raise FileNotFoundError(f'DOS runner missing: {RUNNER}')
    if not no_color and not FOLLOWER.is_file():
        raise FileNotFoundError(f'Color follower missing: {FOLLOWER}')
    if not (ROOT / 'scripts' / 'bb622_descent_color_host.ps1').is_file():
        raise FileNotFoundError('Existing VGA/CP437 renderer missing')

    # The raw view floods the terminal with 80x25 VGA row hex. Default the
    # interactive CONTROL window to the existing filtered Events renderer.
    # Explicit -ConsoleView Raw/Screen/Events always wins.
    has_view = any(x.lower() == '-consoleview' for x in argv)
    if not has_view:
        argv.extend(['-ConsoleView', 'Events'])

    LOGS.mkdir(parents=True, exist_ok=True)
    before = {p.name for p in LOGS.glob('bb-live-*-console.txt') if p.is_file()}
    cmd = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(RUNNER), *argv]
    print('[bb-dual] DOS control terminal = THIS window (only COM5 owner + keyboard)', flush=True)
    if not no_color:
        print('[bb-dual] CP437/VGA color window will launch when the new raw log starts.', flush=True)
    else:
        print('[bb-dual] Color window disabled; control terminal only.', flush=True)
    print('[bb-dual] Main view: ' + ('explicit selection' if has_view else 'Events (default)'), flush=True)
    # Inherit stdin/stdout/stderr and console to preserve the exact DOS
    # interactive controls; no pipe that might swallow console keystrokes.
    runner = subprocess.Popen(cmd, cwd=str(ROOT))
    viewer: subprocess.Popen | None = None
    try:
        while runner.poll() is None:
            if viewer is None and not no_color:
                added = [p for p in LOGS.glob('bb-live-*-console.txt')
                         if p.is_file() and p.name not in before]
                if added:
                    # When one or more runs have started, use latest log.
                    p = max(added, key=lambda q: (q.stat().st_mtime_ns, q.name))
                    view_cmd = [
                        'powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                        '-File', str(FOLLOWER), '-Log', str(p),
                        '-ParentPid', str(runner.pid),
                    ]
                    try:
                        flags = subprocess.CREATE_NEW_CONSOLE if os.name == 'nt' else 0
                        viewer = subprocess.Popen(view_cmd, cwd=str(ROOT), creationflags=flags)
                        print(f'[bb-dual] VGA screen opened (PID {viewer.pid}) | source={p}', flush=True)
                        print('[bb-dual] Type DOS commands here; the color window is DISPLAY ONLY.', flush=True)
                    except OSError as exc:
                        print(f'[bb-dual] WARNING: color window could not start: {exc}', flush=True)
                        # Keep operating safely as a single-console session.
                        no_color = True
            time.sleep(0.15)
    except KeyboardInterrupt:
        print('[bb-dual] Ctrl+C received; use Ctrl+X in DOS console for graceful exit.', flush=True)
        try:
            runner.wait(timeout=3)
        except subprocess.TimeoutExpired:
            # Never terminate a still-running DOS session without consent.
            return 130
    # Viewer watches original runner PID and closes after it ends.
    # Never kill it on behalf of the user or attempt to reopen COM5.
    return runner.wait()


if __name__ == '__main__':
    try:
        sys.exit(subprocess.call([sys.executable, str(ROOT / 'scripts' / 'bb_dos_dual_launch_v2.py'), *sys.argv[1:]], cwd=str(ROOT)))  # BB_DUAL_INPUT_V2
    except (FileNotFoundError, OSError, ValueError) as e:
        print(f'[bb-dual] ERROR: {e}', file=sys.stderr, flush=True)
        sys.exit(2)
