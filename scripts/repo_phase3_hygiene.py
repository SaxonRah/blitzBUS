#!/usr/bin/env python3
"""blitzBUS phase 3: guarded removal of redundant reference copies, safe archival of unreferenced reports.

This script never moves patch installers, executable firmware sources, image data or checksum-state directories.
Usage: python bb_repo_phase3_v1.py selftest|probe|apply|verify|restore [--root PATH]
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

STATE = 'backups/bb_repo_phase3_v1_state'
DUP_DIRS = ('reference_dependencies_DO_NOT_OVERWRITE', 'reference_do_not_overwrite')
REPORTS = (
    'LAST_DOS_SCREEN_20261014.txt',
    'LAST_LOG_AUDIT_20261014.json',
    'FAT_CHAIN_REPORT.json',
    'TEST_REPAIRED.TXT',
    'CHECK_NEWTEST.TXT',
    'SELFTEST.txt',
)
# Only pure, historical log readers; NOT source patchers or active DOS diagnosis.
LEGACY_READERS = ('bb_tier2a_analyze.py', 'bb_tier2b_analyze.py')
DOCS = ('docs/REPO_PHASE3_ROOT_AUDIT.md', 'docs/REPO_PHASE3_POLICY.md',
        'scripts/repo_phase3_hygiene.py', 'scripts/bb_repo_tools.py')
TEXT = ('.py', '.ps1', '.bat', '.cmd', '.c', '.h', '.inc', '.md', '.txt', '.json', '.toml', '.yml', '.yaml', '.cmake', '.sh', '.ini', '.asm')
# Machine-produced phase-2 listing names *every* root tool without depending on
# their location. The phase-3 index supersedes it and documents both old/new paths.
ADVISORY_INDEX = {'docs/REPO_TOOL_INDEX.md'}


def git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    p = subprocess.run(['git', '-C', str(root), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if check and p.returncode:
        raise RuntimeError('git ' + ' '.join(args) + ': ' + p.stderr.decode('utf-8', 'replace').strip())
    return p


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def tracked(root: Path) -> list[str]:
    return [p.decode('utf-8', 'surrogateescape') for p in git(root, 'ls-files', '-z').stdout.split(b'\x00') if p]


def ensure(root: Path):
    top = git(root, 'rev-parse', '--show-toplevel').stdout.decode('utf-8', 'replace').strip()
    if os.path.normcase(str(Path(top).resolve())) != os.path.normcase(str(root.resolve())):
        raise RuntimeError('Invoke at Git repository root')
    if not (root/'src').is_dir() or not (root/'sd_boot').is_dir():
        raise RuntimeError('Expected blitzBUS src/ and sd_boot/ directories')
    for p in ('DOS622_HDD.IMG', 'bb622_lineage_verify_v13.py'):
        if not (root/p).is_file():
            raise RuntimeError('Missing protected working file: ' + p)


def require_clean(root: Path):
    if git(root, 'diff', '--quiet', check=False).returncode or git(root, 'diff', '--cached', '--quiet', check=False).returncode:
        raise RuntimeError('Tracked working tree or Git index has changes. Finish/commit prior phase and retry.')


def references(root: Path, paths: list[str], query: str, exclude=()) -> list[str]:
    # Scan whole tracked text tree, including docs and checksum files. Reject references
    # in any non-candidate file even when a user might consider them comments.
    out = []
    key = query.lower().encode('utf-8')
    avoid = set(exclude)
    for rel in paths:
        if rel in avoid or rel in ADVISORY_INDEX:
            continue
        p = root/rel
        if not p.is_file() or p.suffix.lower() not in TEXT or p.stat().st_size > 2_000_000:
            continue
        data = p.read_bytes()
        if b'\0' in data[:4096]:
            continue
        if key in data.lower():
            out.append(rel)
    return out


def scan(root: Path):
    paths = tracked(root)
    pset = set(paths)
    operations = []
    blocked = []
    # Deduplicate snapshots only if every file still matches root original and
    # there are no references to the *folder name* outside that folder.
    for dirname in DUP_DIRS:
        under = sorted(x for x in paths if x.startswith(dirname+'/'))
        if not under:
            blocked.append((dirname+'/', 'not tracked / absent'))
            continue
        hits = references(root, paths, dirname, under)
        if hits:
            blocked.append((dirname+'/', 'referenced from '+', '.join(hits[:6])))
            continue
        for p in under:
            rootcopy = Path(p).name
            if rootcopy not in pset or not (root/rootcopy).is_file():
                blocked.append((p, 'no same-named tracked root file'))
                continue
            b1 = (root/p).read_bytes(); b2 = (root/rootcopy).read_bytes()
            if b1 != b2:
                blocked.append((p, 'bytes differ from '+rootcopy))
                continue
            operations.append(('remove', p, rootcopy))
    for f in REPORTS + LEGACY_READERS:
        if f not in pset:
            continue
        if f in LEGACY_READERS:
            dest = 'tools/legacy/log-analysis/'+f
        else:
            dest = 'archive/reports/'+f
        if dest in pset or (root/dest).exists():
            blocked.append((f, 'destination already exists: '+dest));continue
        # Literal basename references outside the phase-2 generated listing must block.
        hits = references(root, paths, f, [f])
        if hits:
            blocked.append((f, 'referenced from '+', '.join(hits[:6])));continue
        # Never relocate Python files that contain install/apply/restore tooling
        # or direct __file__ anchored imports/manifest paths.
        if f.endswith('.py'):
            body = (root/f).read_text(encoding='utf-8', errors='replace')
            if re.search(r'\b(__file__|runpy|importlib|restore|patch|manifest|install)\b', body, re.I):
                blocked.append((f, 'potential code/relative-path dependency; retained'));continue
        operations.append(('move', f, dest))
    return paths, operations, blocked


def category(name: str) -> str:
    s = name.lower()
    if 'lineage' in s or 'irq0' in s or 'pic_' in s:
        return 'active DOS 6.22 verification / IRQ0 experiments'
    if s.startswith('bb622_') or s.startswith('bb_dos622_'):
        return 'DOS 6.22 versioned installers / utilities (keep fixed paths)'
    if '386' in s or 'tier' in s or 'jit' in s or 'thumb' in s:
        return 'x86/386/JIT development'
    if 'fat' in s or 'hdd' in s or 'disk' in s:
        return 'disk/media analysis'
    return 'other tools / historical experiments'


def documents(root: Path, paths: list[str], ops: list[tuple[str,str,str]], blocked):
    moved = {p: target for kind,p,target in ops if kind=='move'}
    remain = [p for p in paths if not p.__contains__('/') and p.endswith(('.py','.ps1')) and p not in moved]
    buckets = {}
    for p in remain:
        buckets.setdefault(category(p), []).append(p)
    lines = ['# Root tools and historical analysis — phase 3', '',
       'Generated from the local Git checkout. The list is a navigation catalog, not evidence that an unreferenced script is obsolete.', '',
       '## Critical paths not moved', '',
       '- Root `bb622_*.py` and `bb_dos622_*.py` installers, state manifests, backup folders, .inc files and firmware sources retain their original names.',
       '- `DOS622_HDD.IMG` and all other DOS/floppy images are never modified.',
       '- `bb622_lineage_verify_v13.py verify` and `bb622_irq0_trial_v1.py verify` remain the required regression gates.', '',
       '## Categorized remaining root Python / PowerShell tools', '']
    for cat, names in sorted(buckets.items()):
        lines.extend(['### '+cat+' ('+str(len(names))+')', ''])
        lines.extend('- `'+p+'`' for p in sorted(names))
        lines.append('')
    lines.extend(['## Relocated historical log readers (if any)', ''])
    if moved:
        lines.extend('- `'+p+'` → `'+q+'`' for p,q in sorted(moved.items()))
    else: lines.append('No root Python tools eligible for relocation in this checkout.')
    lines.extend(['', 'Use `python .\\scripts\\bb_repo_tools.py list` to enumerate tools or `run TOOL.py ...` from the repository root.',
        'The dispatcher does not bypass Python scripts with their own prerequisites or manifest state checks.', '',
        '## Retained / blocked candidates',''])
    if blocked:
        lines.extend('- `'+p+'`: '+why for p,why in blocked)
    else:lines.append('No candidates blocked.')
    lines.append('')
    policy = ['# Phase 3 conservative root cleanup', '',
      'This pass removes *byte-identical* snapshots only where no tracked text references their folder name; archives reference-free standalone reports; and may relocate two early read-only log-analysis scripts if their dependency guard passes.', '',
      'All .bb*_state directories, original images, source folders and versioned patch installers stay fixed. `reference_do_not_overwrite/` is intentionally kept if `SHA256SUMS.txt` still references its paths.', '',
      '## Staged operations', '']
    policy.extend('- '+kind.upper()+' `'+p+'`'+(' (identical to `'+target+'`)' if kind=='remove' else ' → `'+target+'`') for kind,p,target in ops)
    if not ops:policy.append('None. Indexes will still be generated.')
    policy.extend(['', 'No Git history rewrite. No automatic commit or push. A clean tracked working tree is required for the initial apply.', '',
       'The snapshot under backups/bb_repo_phase3_v1_state keeps original file bytes until commit. `restore` works only before HEAD changes.', '',
       'Git ignore rules do not remove already-tracked images. Never run `git add -A` during DOS image development.', '',
       'The phase-2 REPO_TOOL_INDEX.md is a baseline catalog that may retain historical root locations. REPO_PHASE3_ROOT_AUDIT.md is the latest location map.', '',
       'Untracked README_FIRST.md / README_FIX1.md / README_PHASE2_FIRST.md / PHASE2_REMOTE_AUDIT.md are not deleted automatically. Review and archive locally after the relevant cleanup commits.', ''])
    return {
        DOCS[0]: '\n'.join(lines)+'\n',
        DOCS[1]: '\n'.join(policy)+'\n',
        DOCS[2]: Path(__file__).read_text(encoding='utf-8'),
        DOCS[3]: TOOL_RUNNER,
    }


TOOL_RUNNER = '''#!/usr/bin/env python3
"""Discover and run historical blitzBUS Python tools from the project root."""
from pathlib import Path
import argparse
import subprocess
import sys

def main():
    root=Path(__file__).resolve().parents[1]
    ap=argparse.ArgumentParser(description=__doc__)
    sub=ap.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    p=sub.add_parser("run")
    p.add_argument("tool")
    p.add_argument("args", nargs=argparse.REMAINDER)
    a=ap.parse_args()
    found={p.name:p for base in (root,root/"tools"/"legacy"/"log-analysis") if base.is_dir() for p in base.glob("*.py")}
    # Print ambiguous/duplicated names as an error rather than silently picking one.
    duplicates={p.name for p in root.glob("*.py") if (root/"tools"/"legacy"/"log-analysis"/p.name).exists()}
    if a.command=="list":
        for name in sorted(found):
            print(f"{name:48} {found[name].relative_to(root)}")
        print(f"Total: {len(found)} Python tools")
        return 0
    if a.tool in duplicates:raise SystemExit("Ambiguous basename: "+a.tool)
    path=found.get(a.tool)
    if not path or path.name!=a.tool:raise SystemExit("Unknown tool; use list")
    return subprocess.call([sys.executable,str(path),*a.args],cwd=root)

if __name__=="__main__":sys.exit(main())
'''


def probe(root):
    ensure(root);require_clean(root)
    if (root/STATE).exists():raise RuntimeError('Phase-3 state already exists: use verify/restore')
    for dst in DOCS:
        if (root/dst).exists():raise RuntimeError('Refusing overwrite: '+dst)
    paths, ops, blocked = scan(root)
    print(f'PROBE PASS: {len(paths)} tracked files; {len(ops)} guarded operations')
    for typ,p,tgt in ops:print('  '+typ.upper()+' '+p+' '+('== '+tgt if typ=='remove' else '-> '+tgt))
    for p,why in blocked:print('  KEEP '+p+': '+why)
    print('No images, rollback metadata, firmware, installers or working Git index changed.')
    return paths,ops,blocked


def apply(root):
    paths,ops,blocked=probe(root)
    docs=documents(root,paths,ops,blocked)
    base=git(root,'rev-parse','HEAD').stdout.decode().strip()
    raw={(typ,p,tgt):(root/p).read_bytes() for typ,p,tgt in ops}
    m={'version':1,'base':base,'operations':[{'kind':kind,'src':p,'target':dst,'sha256':sha(raw[(kind,p,dst)])} for kind,p,dst in ops],
       'docs':{p:sha(v.encode('utf-8')) for p,v in docs.items()}}
    state=root/STATE;state.mkdir(parents=True,exist_ok=False)
    try:
        for i,item in enumerate(m['operations']):
            (state/f'backup_{i:03d}.bin').write_bytes(raw[(item['kind'],item['src'],item['target'])])
        (state/'manifest.json').write_text(json.dumps(m,indent=2)+'\n',encoding='utf-8')
        for kind,p,dst in ops:
            if kind=='remove':git(root,'rm','-q','--',p)
            else:
                (root/dst).parent.mkdir(parents=True,exist_ok=True)
                git(root,'mv','--',p,dst)
        for name,data in docs.items():
            d=root/name;d.parent.mkdir(parents=True,exist_ok=True);d.write_bytes(data.encode('utf-8'))
            git(root,'add','--',name)
        verify(root)
    except Exception:
        print('APPLY INCOMPLETE: preserve state; inspect index and backups before restore',file=sys.stderr)
        raise
    print(f'APPLIED: {len(ops)} guarded operations + {len(docs)} docs/tool files STAGED; NO COMMIT, no image/source/manifest edits.')


def load(root):
    s=root/STATE/'manifest.json'
    if not s.is_file():raise RuntimeError('Phase 3 not applied; state missing')
    m=json.loads(s.read_text(encoding='utf-8'))
    if m.get('version')!=1:raise RuntimeError('Unsupported manifest version')
    return m


def verify(root):
    ensure(root);m=load(root)
    if git(root,'rev-parse','HEAD').stdout.decode().strip()!=m['base']:
        raise RuntimeError('HEAD changed after apply. Automatic restore prohibited.')
    for i,item in enumerate(m['operations']):
        source=item['src']; target=item['target']; b=root/STATE/f'backup_{i:03d}.bin'
        if (root/source).exists():raise RuntimeError('Old source path unexpectedly exists: '+source)
        if not b.is_file() or sha(b.read_bytes())!=item['sha256']:
            raise RuntimeError('Backup changed: '+source)
        if item['kind']=='remove':
            kept=root/target
            if not kept.is_file() or sha(kept.read_bytes())!=item['sha256']:
                raise RuntimeError('Retained canonical copy changed: '+target)
        elif sha((root/target).read_bytes())!=item['sha256']:
            raise RuntimeError('Archived file modified: '+target)
    for p,h in m['docs'].items():
        if not (root/p).is_file() or sha((root/p).read_bytes())!=h:raise RuntimeError('Generated file modified: '+p)
    def names(*args):return {x.decode('utf-8','surrogateescape') for x in git(root,*args).stdout.split(b'\x00') if x}
    staged=names('diff','--cached','--no-renames','--name-only','-z')
    expected=set(m['docs'])|{a['src'] for a in m['operations']}|{a['target'] for a in m['operations'] if a['kind']=='move'}
    if staged!=expected:raise RuntimeError('Staged paths differ: extra='+str(sorted(staged-expected))+' missing='+str(sorted(expected-staged)))
    if git(root,'diff','--quiet',check=False).returncode:
        raise RuntimeError('Unstaged tracked modifications present')
    print(f'VERIFY PASS: {len(m["operations"])} archived/removed assets; {len(m["docs"])} generated tools/docs; original backups byte-exact')


def restore(root):
    verify(root);m=load(root)
    for p in m['docs']:
        git(root,'rm','--cached','-q','--',p)
        (root/p).unlink()
    for i,item in enumerate(m['operations']):
        p=item['src']; target=item['target']
        if item['kind']=='move':
            git(root,'rm','--cached','-q','--',target)
            (root/target).unlink()
        git(root,'restore','--source=HEAD','--staged','--',p)
        (root/p).parent.mkdir(parents=True, exist_ok=True)
        (root/p).write_bytes((root/STATE/f'backup_{i:03d}.bin').read_bytes())
    if git(root,'diff','--quiet',check=False).returncode or git(root,'diff','--cached','--quiet',check=False).returncode:
        raise RuntimeError('Git changes remain after restore; backups retained')
    shutil.rmtree(root/STATE)
    print('RESTORE PASS: exact original files returned; tracked Git index clean')


def selftest():
    n=0
    for autocrlf in ('true','false'):
        for ending in (b'\n',b'\r\n'):
            with tempfile.TemporaryDirectory(prefix='bb3-') as td:
                root=Path(td).resolve()
                git(root,'init','-q');git(root,'config','user.name','test');git(root,'config','user.email','test@example.invalid');git(root,'config','core.autocrlf',autocrlf)
                for d in ('src','sd_boot','reference_dependencies_DO_NOT_OVERWRITE','reference_do_not_overwrite','docs'):(root/d).mkdir()
                (root/'src'/'bb_live.c').write_bytes(b'int x;\n');(root/'sd_boot'/'bb_sd_boot.c').write_bytes(b'int y;\n')
                (root/'DOS622_HDD.IMG').write_bytes(b'\x00\xff\x08\x09')
                (root/'bb622_lineage_verify_v13.py').write_bytes(b'# critical\n')
                (root/'bb622_irq0_trial_v1.py').write_bytes(b'# keep\n')
                (root/'bb_tier2a_analyze.py').write_bytes(b'import argparse'+ending)
                (root/'bb_tier2b_analyze.py').write_bytes(b'import argparse'+ending)
                (root/'LAST_DOS_SCREEN_20261014.txt').write_bytes(b'old screen'+ending)
                (root/'LAST_LOG_AUDIT_20261014.json').write_bytes(b'{}'+ending)
                (root/'bb622_boot_eject_v1.py').write_bytes(b'# identical'+ending)
                for d in DUP_DIRS:(root/d/'bb622_boot_eject_v1.py').write_bytes(b'# identical'+ending)
                (root/'SHA256SUMS.txt').write_text('reference_do_not_overwrite/bb622_boot_eject_v1.py')
                (root/'README.md').write_text('root')
                git(root,'add','--all');git(root,'commit','-qm','baseline')
                old={p:(root/p).read_bytes() for p in tracked(root)}
                _,ops,blocked=scan(root)
                assert ('remove','reference_dependencies_DO_NOT_OVERWRITE/bb622_boot_eject_v1.py','bb622_boot_eject_v1.py') in ops
                assert ('remove','reference_do_not_overwrite/bb622_boot_eject_v1.py','bb622_boot_eject_v1.py') not in ops
                assert any(p=='reference_do_not_overwrite/' for p,_ in blocked)
                apply(root);verify(root)
                restore(root)
                assert {p:(root/p).read_bytes() for p in old}==old
                assert not git(root,'status','--porcelain').stdout.strip()
                n+=1
    with tempfile.TemporaryDirectory(prefix='bb3guard-') as td:
        r=Path(td).resolve();git(r,'init','-q');git(r,'config','user.name','test');git(r,'config','user.email','test@example.invalid')
        for d in ('src','sd_boot'):(r/d).mkdir()
        (r/'src'/'x.c').write_text('X');(r/'sd_boot'/'x.c').write_text('X')
        (r/'DOS622_HDD.IMG').write_bytes(b'disk');(r/'bb622_lineage_verify_v13.py').write_text('keep')
        (r/'LAST_DOS_SCREEN_20261014.txt').write_text('old')
        git(r,'add','--all');git(r,'commit','-qm','base')
        (r/'LAST_DOS_SCREEN_20261014.txt').write_text('changed')
        try:probe(r)
        except RuntimeError as e:assert 'changes' in str(e)
        else:raise AssertionError('Uncommitted change was not rejected')
    print(f'SELFTEST PASS: {n} Windows autocrlf/LF/CRLF combinations, SHA duplicate guard, snapshot reference guard, stage/verify/byte-exact restore, modification refusal')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=('selftest','probe','apply','verify','restore'))
    p.add_argument('--root',default='.')
    a=p.parse_args()
    if a.command=='selftest':selftest();return
    root=Path(a.root).resolve()
    {'probe':probe,'apply':apply,'verify':verify,'restore':restore}[a.command](root)


if __name__=='__main__':
    try:main()
    except (OSError,RuntimeError,ValueError,KeyError,AssertionError,subprocess.SubprocessError) as e:
        print(f'ERROR [{type(e).__name__}]: {e}',file=sys.stderr)
        sys.exit(1)
