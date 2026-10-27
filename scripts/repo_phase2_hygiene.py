#!/usr/bin/env python3
"""blitzBUS phase-2 repository hygiene: guarded archive and living indexes.

Never changes code, DOS media, or checksum states. Git operations are local and staged.
"""
import argparse
import collections
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ARCHIVE = 'archive/test-results'
CANDIDATES = (
    'SELFTEST_OUTPUT.txt', 'TEST_RESULTS.txt', 'V2_2_SELFTEST.txt',
    'test_installer.txt', 'test_c11.txt', 'test_lineage.txt',
    'log_audit_selftest.txt',
)
DOC_386 = (
    'BB_386_PM0_INCLUDE_FIX1_README.md',
    'BB_386_RM2_SRAM_FLASH_FIX_README.md',
    'BB_386_RM3_SELFTEST_FIX1_README.txt',
    'BIOS_386_ROADMAP.md',
    'BLITZ86_386_PM0_README.md',
    'BLITZ86_386_RM0_README.md',
    'BLITZ86_386_RM1_README.md',
    'BLITZ86_386_RM2_README.md',
    'BLITZ86_386_RM3_README.md',
    'BLITZ86_CPU_COMPATIBILITY_WORKPLAN.md',
)
DOC_DOS622 = (
    'BLITZBUS_DOS622_BOOT_DIAG_V1_README.md',
    'BLITZBUS_DOS622_IPL_V1_README.md',
    'BLITZBUS_DOS622_KEYBA2_V1_README.md',
    'BLITZBUS_DOS622_KEYBA2_V2_README.md',
    'BLITZBUS_DOS622_KEYBA2_V3_README.md',
    'BLITZBUS_DOS622_LCD_TEXT_V1_README.md',
    'BLITZBUS_DOS622_P61_REFRESH_V1_README.md',
    'BLITZBUS_DOS622_SD_CLOCKFIX_V1_README.md',
    'BLITZBUS_DOS622_THREE_DISK_STAGING.md',
    'BLITZBUS_DOS622_VGA12_30_V1_README.md',
    'BLITZBUS_DOS622_VGA12_34_V1_README.md',
)
INDEXES = (
    'docs/REPO_TOOL_INDEX.md',
    'docs/REPO_MEDIA_INVENTORY.md',
    'docs/REPO_HISTORY_INDEX.md',
    'docs/REPO_TEST_AUDIT.md',
    'docs/REPO_PHASE2_POLICY.md',
    'scripts/repo_phase2_hygiene.py',
)
STATE = 'backups/bb_repo_phase2_v1_state'
TEXT_EXT = {'.py', '.ps1', '.bat', '.cmd', '.c', '.h', '.inc', '.md', '.txt', '.json', '.yml', '.yaml', '.cmake', '.toml', '.ini', '.sh'}


def git(root, *args, check=True):
    p = subprocess.run(['git', '-C', str(root), *args], stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, check=False)
    if check and p.returncode:
        raise RuntimeError('git ' + ' '.join(args) + ': ' + p.stderr.decode('utf-8', 'replace').strip())
    return p


def names(root):
    return [x.decode('utf-8', 'surrogateescape') for x in git(root, 'ls-files', '-z').stdout.split(b'\x00') if x]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def txt(root, p):
    return (root / p).read_text(encoding='utf-8', errors='replace')


def clean_stage(root):
    if git(root, 'diff', '--quiet', check=False).returncode or git(root, 'diff', '--cached', '--quiet', check=False).returncode:
        raise RuntimeError('Tracked files or index already modified. Commit/restore them before phase 2.')


def refs(root, tracked, candidate):
    hits = []
    # Search the actual tracked worktree, not a GitHub code-search sample.
    # Filename guard errs conservatively: comments and historical citations block a move.
    pattern = Path(candidate).name.lower()
    for rel in tracked:
        if rel == candidate:
            continue
        p = root / rel
        if not p.is_file() or p.suffix.lower() not in TEXT_EXT or p.stat().st_size > 1200000:
            continue
        try:
            data = p.read_bytes()
        except OSError:
            continue
        if b'\x00' in data[:4096]:
            continue
        if pattern.encode('ascii') in data.lower():
            hits.append(rel)
    return hits


def classify_py(name, text):
    low = name.lower()
    if (('selftest' in text and (' restore' in text or 'restore(' in text))
            or ('apply' in text and 'restore' in text and ('manifest' in text or 'sha256' in text))):
        return 'versioned installer / rollback'  # never move
    if 'lineage' in low:
        return 'lineage verification'
    if any(k in low for k in ('audit', 'report', 'diag', 'probe', 'logview', 'inventory', 'profile')):
        return 'diagnostic / analysis'
    if any(k in low for k in ('fat', 'disk', 'hdd', 'image', 'descent')):
        return 'media / disk utility'
    if 'tier' in low or 'jit' in low or 'thumb' in low or 'bench' in low:
        return 'CPU / JIT investigation'
    return 'other historical tool'


def size_fmt(n):
    return f'{n/1048576:.2f} MiB' if n >= 1048576 else f'{n:,} B'


def generate(root, tracked, moves):
    rootpy = sorted(p for p in tracked if '/' not in p and p.endswith('.py'))
    groups = collections.defaultdict(list)
    for p in rootpy:
        groups[classify_py(p, txt(root, p))].append(p)
    current = sorted((p for p in tracked if p.startswith('scripts/') and p.endswith(('.py', '.ps1'))))
    catalog = [
        '# blitzBUS tool index (phase 2)', '',
        'Generated from the local tracked checkout. This is a navigation catalog, not a declaration that every tool is currently maintained.', '',
        '**IMPORTANT:** Root-level installer scripts and the `.bb_*_state` directories remain at their original paths. '
        'Changing their locations could invalidate checksum manifests, sibling imports and rollback scripts.', '',
        '## Key known working entry points', '',
        '- `bb.bat` — legacy build/install/run entry point.',
        '- `scripts/install_live.py` — installs the live integration into the microDOS build.',
        '- `scripts/bb_live_run_dos622_irqtrial.ps1` — experimental DOS 6.22 / IRQ0 runner; *not* a known-good IRQ0 release.',
        '- `bb622_lineage_verify_v13.py verify` — installed SHA lineage.',
        '- `bb622_irq0_trial_v1.py verify` — latest one-shot IRQ0 patch-source verification.',
        '- `bb622_logview_pic.py` — passive, copyable live-log viewer.',
        '', '## Root-level Python tools', '',
        f'{len(rootpy)} root Python scripts detected in tracked checkout.', ''
    ]
    for group, paths in sorted(groups.items()):
        catalog.extend([f'### {group} ({len(paths)})', ''])
        catalog.extend(f'- `{p}`' for p in paths)
        catalog.append('')
    catalog.extend(['## Script directory entry points', ''])
    catalog.extend(f'- `{p}`' for p in current)
    catalog.extend(['', '## History and archive policy', '',
                    '- Installer versions are a **chronology**, not automatically duplicates.',
                    '- `milestones/` and every rollback state directory are preserved untouched.',
                    '- The test-output archive consists only of individually reference-checked files.',
                    '- Do not run `git add -A` with writable tracked DOS images.', ''])

    image_paths = [p for p in tracked if p.lower().endswith(('.img', '.arj', '.zip', '.wad', '.hog', '.pig'))]
    image_paths.sort(key=lambda p: (p.split('/')[0], p))
    medias = ['# blitzBUS media inventory (phase 2)', '',
              'Generated from the tracked checkout. **Sizes are not proof of duplicate content**. No unique media is deleted or modified by phase 2.', '',
              'The active DOS 6.22 HDD `DOS622_HDD.IMG` is protected. Multiple C: image versions may represent different states even when similarly sized.', '',
              '| File | Checkout bytes |', '| --- | ---: |']
    total = 0
    for p in image_paths:
        full = root / p
        if not full.exists():
            continue
        n = full.stat().st_size
        total += n
        medias.append(f'| `{p}` | {n:,} |')
    medias.extend(['', f'**Tracked media files listed:** {len(image_paths)}; **sum of working-tree bytes:** {size_fmt(total)}.', '',
                  'Git history retains media even after tracked-file deletion unless explicitly rewritten; history rewriting is out of scope. Review third-party asset redistribution rights separately.', ''])
    history = ['# Historical documentation index', '',
               'The listed documentation is historical. Its source-code installer paths remain unchanged. Moves were permitted only after scanning tracked text files for references and verifying a clean Git index.', '',
               '## 386 / 286 bring-up', '']
    history.extend(f'- `{b}` (from `{a}`)' for a,b in moves if a in DOC_386)
    history.extend(['', '## DOS 6.22 incremental bring-up', ''])
    history.extend(f'- `{b}` (from `{a}`)' for a,b in moves if a in DOC_DOS622)
    history.extend(['', '## Standalone test output', ''])
    history.extend(f'- `{b}` (from `{a}`)' for a,b in moves if a in CANDIDATES)
    history.extend(['', 'If a document was not eligible for relocation because another file referenced it, it remains at the old path and is reported by `probe`.', ''])
    testroots = sorted(p for p in tracked if '/' not in p and p.lower().endswith(('.c', '.asm')) and (p.lower().startswith('test') or p.lower().endswith('_smoke.c') or 'test' in p.lower()))
    tests = ['# Host test and smoke-file reference audit', '',
             'A **literal-reference scan** of tracked text files. A file with zero found references is NOT proven unused; CMake, wildcards, command-line arguments or manual build scripts may load it indirectly.', '',
             '| Test source | Files referring to its exact filename |', '| --- | --- |']
    for p in testroots:
        users = refs(root, tracked, p)
        tests.append('| `' + p + '` | ' + (', '.join('`'+n+'`' for n in users[:6]) if users else 'No literal references found (not proof of disuse)') + ' |')
    tests.extend(['', 'Do not delete these tests without compiling their hosts and checking the build/test commands. All test source files remain in place in phase 2.', ''])
    moved = [f'- `{a}` → `{b}`' for a, b in moves]
    policy = ['# Phase-2 repository hygiene', '',
              'This phase archives reference-free historical documents and standalone test output, and adds tool/media/history/test catalogs and a reusable maintenance script plus this policy. No emulator source, installer, BIOS, PSRAM, IRQ0, HDD/floppy or patch-state file is moved.', '',
              '## Planned/staged archive moves', ''] + (moved or ['No files eligible in the local checkout.']) + [
                  '', 'Each file was checked against other tracked text files for references by basename and required to match the unmodified Git index. References and local changes cause the move to be blocked.', '',
                  '## Protected boundaries', '',
                  '- Never move `.bb_dos622_*_state`, `.bb622_*_state`, or their backups/manifests.',
                  '- Never rename root-level `bb_dos622_*.py`, `bb622_*.py`, firmware `.inc` files, `src/`, `sd_boot/`, or active runner scripts without a separately verified migration of all references.',
                  '- Never prune unique `.IMG` images during a code cleanup.',
                  '- Previous V1 duplicate asset cleanup is independent of these changes.', '',
                  '## Restore', '',
                  'Before committing, run `python .\\bb_repo_phase2_v1.py verify` followed by `python .\\bb_repo_phase2_v1.py restore`. No automatic commit/push is performed.', '',
                  'If an archive move is blocked, inspect `probe` output before considering an explicit compatibility adapter.', ''
              ]
    contents = ('\n'.join(catalog) + '\n', '\n'.join(medias) + '\n', '\n'.join(history) + '\n', '\n'.join(tests) + '\n', '\n'.join(policy) + '\n', Path(__file__).read_text(encoding='utf-8'))
    return dict(zip(INDEXES, contents))


def scan(root):
    tracked = names(root)
    moves, blocked = [], {}
    for candidate in CANDIDATES + DOC_386 + DOC_DOS622:
        if candidate not in tracked:
            blocked[candidate] = ['not tracked in this checkout']
            continue
        # Compare HEAD/index normalized blobs, then require unmodified checkout via git diff --quiet.
        if git(root, 'diff', '--quiet', '--', candidate, check=False).returncode or git(root, 'diff', '--cached', '--quiet', '--', candidate, check=False).returncode:
            blocked[candidate] = ['modified relative to index or HEAD']
            continue
        hits = refs(root, tracked, candidate)
        if hits:
            blocked[candidate] = hits
            continue
        destdir = ARCHIVE if candidate in CANDIDATES else 'docs/history/386' if candidate in DOC_386 else 'docs/history/dos622'
        dst = destdir + '/' + candidate
        if (root / dst).exists() or dst in tracked:
            blocked[candidate] = ['destination already exists']
            continue
        moves.append((candidate, dst))
    return tracked, moves, blocked


def ensure_repo(root):
    git_top = git(root, 'rev-parse', '--show-toplevel').stdout.decode('utf8', 'replace').strip()
    if os.path.normcase(str(Path(git_top).resolve())) != os.path.normcase(str(root.resolve())):
        raise RuntimeError('Invoke from the root of the Git repository')
    if not (root / 'sd_boot').is_dir() or not (root / 'src').is_dir():
        raise RuntimeError('Not a blitzBUS source checkout (src/ and sd_boot/ missing)')


def probe(root):
    ensure_repo(root)
    clean_stage(root)
    tracked, moves, blocked = scan(root)
    for p in INDEXES:
        if (root / p).exists():
            raise RuntimeError(f'Will not overwrite existing file: {p}')
    if (root / STATE).exists():
        raise RuntimeError(f'Previous phase-2 state exists: {STATE}; verify/restore it first')
    print(f'PROBE PASS: {len(tracked)} tracked files; {len(moves)} independently safe archive candidates')
    for src, dst in moves:
        print('  MOVE ' + src + ' -> ' + dst)
    for src, hits in blocked.items():
        if hits == ['not tracked in this checkout']:
            continue
        print('  KEEP ' + src + ': ' + ', '.join(hits[:4]))
    print('Protected: patch states, installer paths, source, disk images. No changes.')
    return tracked, moves, blocked


def apply(root):
    tracked, moves, blocked = probe(root)
    if not moves:
        raise RuntimeError('No safe archive candidates. Catalog-only apply intentionally requires an explicit new version.')
    source_bytes = {a: (root / a).read_bytes() for a, b in moves}
    docs = generate(root, tracked, moves)
    base = git(root, 'rev-parse', 'HEAD').stdout.decode().strip()
    meta = {'version': 1, 'base': base, 'moves': [{'src': a, 'dest': b, 'sha256': sha(source_bytes[a])} for a, b in moves],
            'documents': {p: sha(content.encode('utf-8')) for p, content in docs.items()}, 'blocked': blocked}
    store = root / STATE
    store.mkdir(parents=True, exist_ok=False)
    try:
        for i, (p, data) in enumerate(source_bytes.items()):
            (store / f'file_{i:03d}.bin').write_bytes(data)
        (store / 'manifest.json').write_text(json.dumps(meta, indent=2) + '\n', encoding='utf-8')
        for a, b in moves:
            (root / b).parent.mkdir(parents=True, exist_ok=True)
            git(root, 'mv', '--', a, b)
        for p, content in docs.items():
            (root / p).parent.mkdir(parents=True, exist_ok=True)
            (root / p).write_bytes(content.encode('utf-8'))
            git(root, 'add', '--', p)
        verify(root)
    except Exception:
        # Preserve state + staged files for manual investigation rather than destroying evidence.
        print('APPLY INCOMPLETE: state preserved; inspect Git diff and backups before restore.', file=sys.stderr)
        raise
    print(f'APPLIED: {len(moves)} guarded archival moves + {len(docs)} index/policy files STAGED. No commit, push, or media changes.')


def load_state(root):
    p = root / STATE / 'manifest.json'
    if not p.is_file():
        raise RuntimeError('Phase-2 state missing. Nothing to verify/restore.')
    data = json.loads(p.read_text(encoding='utf-8'))
    if data.get('version') != 1:
        raise RuntimeError('Unsupported state version')
    return data


def verify(root):
    ensure_repo(root)
    meta = load_state(root)
    if git(root, 'rev-parse', 'HEAD').stdout.decode().strip() != meta['base']:
        raise RuntimeError('HEAD changed since apply. Refuse automatic restore or verification.')
    for i, move in enumerate(meta['moves']):
        src, dst = move['src'], move['dest']
        if (root / src).exists():
            raise RuntimeError('Old path recreated unexpectedly: ' + src)
        backup = root / STATE / f'file_{i:03d}.bin'
        if sha(backup.read_bytes()) != move['sha256'] or sha((root / dst).read_bytes()) != move['sha256']:
            raise RuntimeError('Archive or restore backup modified: ' + dst)
    for p, h in meta['documents'].items():
        if sha((root / p).read_bytes()) != h:
            raise RuntimeError('Generated documentation modified: ' + p)
    staged = set(git(root, 'diff', '--cached', '--no-renames', '--name-only', '-z').stdout.decode('utf-8', 'surrogateescape').strip('\x00').split('\x00'))
    expected = set(meta['documents']) | {x['src'] for x in meta['moves']} | {x['dest'] for x in meta['moves']}
    if staged != expected:
        raise RuntimeError('Staged paths differ from phase-2 expected set: extra=' + repr(sorted(staged-expected)) + ', missing=' + repr(sorted(expected-staged)))
    if git(root, 'diff', '--quiet', check=False).returncode:
        raise RuntimeError('Unstaged changes present; cannot guarantee state')
    print(f'VERIFY PASS: {len(meta["moves"])} archived files byte-exact; {len(meta["documents"])} staged documents; original backups valid')


def restore(root):
    verify(root)
    meta = load_state(root)
    for p in meta['documents']:
        git(root, 'rm', '--cached', '-q', '--', p)
        (root / p).unlink()
    for i, move in enumerate(meta['moves']):
        a, b = move['src'], move['dest']
        git(root, 'rm', '--cached', '-q', '--', b)
        (root / b).unlink()
        git(root, 'restore', '--source=HEAD', '--staged', '--', a)
        (root / a).write_bytes((root / STATE / f'file_{i:03d}.bin').read_bytes())
    if git(root, 'diff', '--quiet', check=False).returncode or git(root, 'diff', '--cached', '--quiet', check=False).returncode:
        raise RuntimeError('Restore needs inspection: Git changes remain. State retained.')
    shutil.rmtree(root / STATE)
    print('RESTORE PASS: archive and docs reversed; exact original file bytes; clean tracked Git index; no commit changed')


def selftest():
    count=0
    for autocrlf in ('true', 'false'):
        for ending in (b'\n', b'\r\n'):
            with tempfile.TemporaryDirectory(prefix='bb-phase2-') as td:
                root=Path(td).resolve()
                git(root, 'init', '-q'); git(root, 'config', 'user.email', 'test@example.invalid');git(root, 'config', 'user.name', 'test')
                git(root, 'config', 'core.autocrlf', autocrlf)
                (root / 'src').mkdir(); (root / 'sd_boot').mkdir();(root / 'scripts').mkdir()
                (root / 'src' / 'bb_live.c').write_text('/* stable source */\n')
                (root / 'sd_boot' / 'bb_sd_boot.c').write_text('/* stable media */\n')
                (root / 'scripts' / 'install_live.py').write_text('# stable runner\n')
                (root / 'bb622_lineage_verify_v13.py').write_text('# stable SHA verification\n')
                (root / DOC_386[0]).write_text('historical documentation\n')
                (root / DOC_DOS622[0]).write_text('DOS documentation\n')
                # One filename is deliberately referenced and must not move.
                (root / 'REFERENCES.md').write_text('Old regression: test_lineage.txt\n')
                for name in CANDIDATES:
                    (root / name).write_bytes(b'archive test output' + ending)
                git(root, 'add', '--all');git(root, 'commit', '-qm', 'baseline')
                before={p: (root/p).read_bytes() for p in CANDIDATES + (DOC_386[0], DOC_DOS622[0])}
                _, moves, blocked = scan(root)
                assert len(moves)==len(CANDIDATES)+1 and 'test_lineage.txt' in blocked
                apply(root);verify(root)
                assert not (root / 'archive/test-results/test_lineage.txt').exists()
                restore(root)
                assert {p:(root/p).read_bytes() for p in before}==before
                assert not git(root, 'status', '--porcelain').stdout.strip()
                count+=1
    # Check no silent acceptance of a modified tracked candidate.
    with tempfile.TemporaryDirectory(prefix='bb-phase2-guard-') as td:
        r=Path(td).resolve();git(r,'init','-q');git(r,'config','user.email','test@example.invalid');git(r,'config','user.name','test')
        (r/'src').mkdir();(r/'sd_boot').mkdir();(r/'src'/'x.c').write_text('x')
        (r/'sd_boot'/'x.c').write_text('x');(r/CANDIDATES[0]).write_text('baseline')
        git(r,'add','--all');git(r,'commit','-qm','baseline')
        (r/CANDIDATES[0]).write_text('edited')
        _,moves,blocked=scan(r)
        assert not moves and 'modified' in blocked[CANDIDATES[0]][0]
    print(f'SELFTEST PASS: {count} Git autocrlf/LF+CRLF variants, reference guard, modification guard, staged verify, byte-exact restore')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('command', choices=['selftest','probe','apply','verify','restore'])
    ap.add_argument('--root', default='.')
    args=ap.parse_args()
    if args.command=='selftest':selftest();return
    root=Path(args.root).resolve()
    {'probe':probe, 'apply':apply, 'verify':verify, 'restore':restore}[args.command](root)


if __name__=='__main__':
    try:main()
    except (OSError, subprocess.SubprocessError, ValueError, RuntimeError, AssertionError, KeyError) as e:
        print(f'ERROR [{type(e).__name__}]: {e!s}',file=sys.stderr)
        sys.exit(1)
