#!/usr/bin/env python3
"""Guarded, reversible DOS 6.22 dual-console integration (no Git patches).

Edits only scripts/bb_cli.py. Keeps the SHA-protected DOS runner and original
color renderer byte-for-byte. Adds two complete new standalone source files:
  scripts/bb_dos_dual_launch.py
  scripts/bb622_color_follow.ps1

Commands: selftest | probe | apply | verify | restore
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

PACKAGE = Path(__file__).resolve().parent
CLI = Path('scripts/bb_cli.py')
LAUNCHER = Path('scripts/bb_dos_dual_launch.py')
FOLLOWER = Path('scripts/bb622_color_follow.ps1')
STATE = Path('backups/bb_dos_dual_console_v1_state')
TAG = 'BB_DOS_DUAL_CONSOLE_V1'


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def atomic_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.bbdual-', suffix='.tmp', delete=False) as fh:
        tmp = Path(fh.name)
        fh.write(raw)
    try:
        os.replace(tmp, path)
    finally:
        if tmp.exists(): tmp.unlink()


def modify_cli(raw: bytes) -> bytes:
    eol = b'\r\n' if b'\r\n' in raw else b'\n'
    s = raw.replace(b'\r\n', b'\n')
    if TAG.encode() in s:
        raise ValueError('Dual console already installed. Use verify, not apply.')
    changes = (
        (b'    return execute(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), *argv], label="DOS 6.22 BOOT")',
         b'    # BB_DOS_DUAL_CONSOLE_V1: protected runner stays byte-exact; two host windows share one log.\n'
         b'    return python_script("scripts/bb_dos_dual_launch.py", argv, "DOS 6.22 BOOT (dual console)")'),
        (b'bb.bat dos boot [-NoBuild] [-NoFlash] [-Port COM5] [-Seconds 0] [-ConsoleView Screen]',
         b'bb.bat dos boot [-NoBuild] [-NoFlash] [-Port COM5] [-Seconds 0] [-ConsoleView Events] [-NoColorWindow]'),
        (b'  - DOS boot uses scripts/bb_live_run_dos622_irqtrial.ps1, which is EXPERIMENTAL.',
         b'  - DOS boot uses the original EXPERIMENTAL runner, plus a log-only second VGA color window.'),
    )
    for old, new in changes:
        count = s.count(old)
        if count != 1:
            raise ValueError(f'Expected one CLI anchor, found {count}: {old[:100]!r}. No files changed.')
        s = s.replace(old, new, 1)
    return s.replace(b'\n', eol)


def manifest(root: Path) -> dict:
    p = root / STATE / 'manifest.json'
    if not p.is_file(): raise ValueError(f'Missing state manifest: {p}')
    obj = json.loads(p.read_text(encoding='utf-8'))
    if obj.get('tag') != TAG: raise ValueError('State tag mismatch')
    return obj


def verify(root: Path) -> None:
    obj = manifest(root)
    p = root / CLI
    installed = p.read_bytes()
    original = (root / STATE / 'cli.original').read_bytes()
    if sha(installed) != obj['cli_installed']:
        raise ValueError('CLI changed since installation; protecting local edits')
    if sha(original) != obj['cli_original']:
        raise ValueError('CLI rollback bytes corrupted')
    for relative, key in ((LAUNCHER,'launcher_sha'),(FOLLOWER,'follower_sha')):
        if sha((root / relative).read_bytes()) != obj[key]:
            raise ValueError(f'Installed file hash mismatch: {relative}')
    # Critically: verify the SHA-protected DOS runner is still exactly as when
    # the dual console was applied; never tamper with DOS IRQ0 lineage.
    runner = root / 'scripts/bb_live_run_dos622_irqtrial.ps1'
    if sha(runner.read_bytes()) != obj['protected_runner_sha']:
        raise ValueError('Protected DOS runner changed since installation')
    print('VERIFY PASS: two-window CLI and files; protected DOS runner SHA preserved')


def preflight(root: Path) -> tuple[bytes,bytes]:
    if not (root / CLI).is_file(): raise ValueError('Unified CLI missing: run unified bb.bat installer first')
    if not (root / 'scripts/bb_live_run_dos622_irqtrial.ps1').is_file():
        raise ValueError('Protected DOS runner missing')
    if not (root / 'scripts/bb622_descent_color_host.ps1').is_file():
        raise ValueError('Existing CP437 color renderer missing')
    original = (root / CLI).read_bytes()
    return original, modify_cli(original)


def probe(root: Path) -> None:
    if (root / STATE / 'manifest.json').is_file():
        verify(root)
        return
    if (root / STATE).exists():
        raise ValueError(f'Partial state exists, inspect without deleting: {root / STATE}')
    for p in (LAUNCHER,FOLLOWER):
        if (root / p).exists():
            raise ValueError(f'File already exists, refusing replacement: {root / p}')
    a,b = preflight(root)
    print('PROBE PASS: scripts/bb_cli.py exact edit available')
    print('Existing CLI SHA256:',sha(a))
    print('Proposed CLI SHA256:',sha(b))
    print('Protected DOS IRQ0 runner: unchanged')
    print('No COM5, firmware, disk, or repository file changed.')


def apply(root: Path) -> None:
    if (root / STATE / 'manifest.json').is_file():
        verify(root)
        print('ALREADY INSTALLED; no modifications')
        return
    probe(root)
    original, updated = preflight(root)
    files = {
        LAUNCHER:(PACKAGE/LAUNCHER).read_bytes(),
        FOLLOWER:(PACKAGE/FOLLOWER).read_bytes(),
    }
    protected = (root / 'scripts/bb_live_run_dos622_irqtrial.ps1').read_bytes()
    obj = dict(tag=TAG,cli_original=sha(original),cli_installed=sha(updated),
               protected_runner_sha=sha(protected),launcher_sha=sha(files[LAUNCHER]),
               follower_sha=sha(files[FOLLOWER]))
    state=root/STATE
    state.mkdir(parents=True)
    cli_changed=False
    created=[]
    try:
        atomic_write(state/'cli.original',original)
        for p,blob in files.items():
            if (root/p).exists(): raise ValueError(f'Unexpected file conflict: {p}')
            atomic_write(root/p,blob)
            created.append(p)
        if (root/CLI).read_bytes()!=original: raise ValueError('CLI edited concurrently, refusing overwrite')
        atomic_write(root/CLI,updated)
        cli_changed=True
        atomic_write(state/'manifest.json',(json.dumps(obj,indent=2)+'\n').encode('utf-8'))
        verify(root)
    except Exception:
        if cli_changed and sha((root/CLI).read_bytes())==sha(updated):
            atomic_write(root/CLI,original)
        for p in created:
            if (root/p).is_file() and sha((root/p).read_bytes())==sha(files[p]):
                (root/p).unlink()
        # Any partial state remains for safe inspection.
        raise
    print('APPLY PASS: bb.bat dos boot opens interactive controls here and a second VGA screen window')
    print('Main default: Events; -ConsoleView Raw remains available. -NoColorWindow disables second view.')


def restore(root: Path) -> None:
    verify(root)
    old=(root/STATE/'cli.original').read_bytes()
    atomic_write(root/CLI,old)
    for p in (LAUNCHER,FOLLOWER): (root/p).unlink()
    (root/STATE/'manifest.json').unlink()
    (root/STATE/'cli.original').unlink()
    (root/STATE).rmdir()
    print('RESTORE PASS: unified CLI restored byte-for-byte; protected DOS runner unchanged')


def selftest() -> None:
    template=(b'bb.bat dos boot [-NoBuild] [-NoFlash] [-Port COM5] [-Seconds 0] [-ConsoleView Screen]\n'
        b'  - DOS boot uses scripts/bb_live_run_dos622_irqtrial.ps1, which is EXPERIMENTAL.\n'
        b'    return execute(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), *argv], label="DOS 6.22 BOOT")\n')
    for eol in (b'\n',b'\r\n'):
        raw = b'\xef\xbb\xbf'+template.replace(b'\n',eol)
        result=modify_cli(raw)
        assert result.startswith(b'\xef\xbb\xbf')
        assert result.count(TAG.encode())==1
        assert result.count(b'bb_dos_dual_launch.py')==1
        assert b'-NoColorWindow' in result
        if eol==b'\r\n': assert result.count(b'\n')==result.count(b'\r\n')
        try:
            modify_cli(result)
            raise AssertionError('Duplicate install was accepted')
        except ValueError:
            pass
    ps=(PACKAGE/FOLLOWER).read_text(encoding='utf-8')
    py=(PACKAGE/LAUNCHER).read_text(encoding='utf-8')
    assert 'SerialPort' not in ps and 'FileShare' in ps
    assert 'Write-BbDos622ColorConsoleChunk' in ps
    assert 'CREATE_NEW_CONSOLE' in py and 'bb-live-*-console.txt' in py
    print('SELFTEST PASS: LF/CRLF/BOM, exact SHA guard, single COM owner, two display processes')


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['selftest','probe','apply','verify','restore'])
    parser.add_argument('--root',type=Path,default=PACKAGE.parent)
    args=parser.parse_args()
    try:
        {'selftest':lambda:selftest(),'probe':lambda:probe(args.root),
         'apply':lambda:apply(args.root),'verify':lambda:verify(args.root),
         'restore':lambda:restore(args.root)}[args.action]()
        return 0
    except (OSError,ValueError,AssertionError) as e:
        print('ERROR:',e,file=sys.stderr)
        return 1

if __name__=='__main__': raise SystemExit(main())
