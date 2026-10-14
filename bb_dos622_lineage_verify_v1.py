#!/usr/bin/env python3
"""Read-only DOS 6.22 ATBIOS->HDD->LCD checksum-lineage audit.

The ATBIOS V1 verifier is point-in-time: HDD V1 legitimately updates some
parent metadata after ATBIOS was installed, leaving ATBIOS's old `installed`
digests as valid historical digests, not current ones. This checks the
individual transition at each layer instead of rewriting any old manifest.

Usage: python bb_dos622_lineage_verify_v1.py verify|selftest
"""
from pathlib import Path
import argparse, hashlib, json, tempfile, sys

ROOT=Path(__file__).resolve().parent
AT='.bb_dos622_atbios_v1_state'
HDD='.bb_dos622_hdd_v1_state'
LCD='.bb_dos622_lcd_text_v2_state'

def sha(raw):return hashlib.sha256(raw).hexdigest()
def manifest(root,folder,tag):
    p=root/folder/'manifest.json'
    if not p.is_file():raise ValueError(f'Missing manifest: {p}')
    o=json.loads(p.read_bytes())
    if o.get('tag')!=tag or not isinstance(o.get('files'),list):
        raise ValueError(f'Invalid installer tag/entry list in {p}')
    paths=[ent['path'] for ent in o['files']]
    if len(set(paths))!=len(paths):raise ValueError(f'Duplicate entries in {p}')
    return o

def check_backup(root,folder,ent):
    old=ent.get('original');bk=ent.get('backup')
    if old is None:
        if bk is not None:raise ValueError(f'Unexpected backup for new file {ent["path"]}')
    else:
        if not bk:raise ValueError(f'Missing backup reference {ent["path"]}')
        p=root/folder/bk
        if not p.is_file() or sha(p.read_bytes())!=old:
            raise ValueError(f'Backup mismatch: {p}')

def audit(root=ROOT,verbose=True):
    a=manifest(root,AT,'BB_DOS622_ATBIOS_V1')
    h=manifest(root,HDD,'BB_DOS622_HDD_V1')
    lp=root/LCD/'manifest.json'
    lcd=manifest(root,LCD,'BB_DOS622_LCD_TEXT_V2') if lp.is_file() else None
    hm_current={e['path']:e for e in h['files']}
    lm={e['path']:e for e in lcd['files']} if lcd else {}

    # First prove the current (possibly LCD-updated) HDD manifest is valid.
    for ent in h['files']:
        check_backup(root,HDD,ent)
        p=root/ent['path']
        if not p.is_file() or sha(p.read_bytes())!=ent['installed']:
            raise ValueError(f'Current HDD state mismatch: {p}')

    # The LCD install may update the HDD manifest's *active* SHA references.
    # The exact pre-LCD HDD manifest is stored in LCD's byte-exact backup.
    h_pre=h
    if lcd:
        for ent in lcd['files']:
            check_backup(root,LCD,ent)
            p=root/ent['path']
            if not p.is_file() or sha(p.read_bytes())!=ent['installed']:
                raise ValueError(f'Current LCD state mismatch: {p}')
        if f'{HDD}/manifest.json' in lm:
            b=lm[f'{HDD}/manifest.json']
            h_pre=json.loads((root/LCD/b['backup']).read_bytes())
            if h_pre.get('tag')!='BB_DOS622_HDD_V1':
                raise ValueError('HDD pre-LCD backup is not an HDD manifest')
    hm_pre={e['path']:e for e in h_pre['files']}
    assert hm_current, 'HDD state unexpectedly empty'
    seen_h=seen_l=0
    for ent in a['files']:
        check_backup(root,AT,ent)
        path=ent['path']
        expected=ent['installed']
        if path in hm_pre:
            rec=hm_pre[path]
            if rec['original']!=expected:
                raise ValueError(f'ATBIOS->HDD lineage mismatch: {path}')
            expected=rec['installed'];seen_h+=1
        if path in lm:
            rec=lm[path]
            if rec['original']!=expected:
                raise ValueError(f'HDD->LCD lineage mismatch: {path}')
            expected=rec['installed'];seen_l+=1
        p=root/path
        if not p.is_file() or sha(p.read_bytes())!=expected:
            raise ValueError(f'Unexplained change outside ATBIOS/HDD/LCD history: {p}')
    if seen_h==0:raise ValueError('No tracked ATBIOS->HDD lineage found')
    if lcd and seen_l==0:raise ValueError('No tracked ATBIOS/HDD->LCD lineage found')
    if verbose:
        print(f'ATBIOS historical record PASS: {len(a["files"])} files and backups')
        print(f'HDD current state PASS: {len(h["files"])} files and backups')
        if lcd:print(f'LCD current state PASS: {len(lcd["files"])} files and backups')
        print(f'ATBIOS->HDD verified transitions={seen_h}; then LCD transitions={seen_l}')
        print('LINEAGE PASS: ancestor records preserved; all current bytes match verified descendants')

def fixture(root,lcd):
    for name in (AT,HDD): (root/name).mkdir()
    p=root/'test.bin'; b0=b'A';b1=b'B';b2=b'C'
    p.write_bytes(b2 if lcd else b1)
    (root/AT/'save0.bin').write_bytes(b'Z')
    at={'tag':'BB_DOS622_ATBIOS_V1','files':[{'path':'test.bin','backup':'save0.bin','original':sha(b'Z'),'installed':sha(b0)}]}
    (root/AT/'manifest.json').write_text(json.dumps(at))
    hp={'tag':'BB_DOS622_HDD_V1','files':[{'path':'test.bin','backup':'save1.bin','original':sha(b0),'installed':sha(b1)}]}
    (root/HDD/'save1.bin').write_bytes(b0)
    if lcd:
        (root/LCD).mkdir()
        (root/LCD/'save2.bin').write_bytes(b1)
        before=json.dumps(hp).encode()
        (root/LCD/'save3.bin').write_bytes(before)
        hc={'tag':'BB_DOS622_HDD_V1','files':[{'path':'test.bin','backup':'save1.bin','original':sha(b0),'installed':sha(b2)}]}
        final=json.dumps(hc).encode()
        lp={'tag':'BB_DOS622_LCD_TEXT_V2','files':[
          {'path':'test.bin','backup':'save2.bin','original':sha(b1),'installed':sha(b2)},
          {'path':f'{HDD}/manifest.json','backup':'save3.bin','original':sha(before),'installed':sha(final)}]}
        (root/HDD/'manifest.json').write_bytes(final)
        (root/LCD/'manifest.json').write_text(json.dumps(lp))
    else:(root/HDD/'manifest.json').write_text(json.dumps(hp))

def selftest():
    with tempfile.TemporaryDirectory() as td:
        root=Path(td);fixture(root,False);audit(root,False)
        print('SELFTEST ATBIOS->HDD lineage PASS')
    with tempfile.TemporaryDirectory() as td:
        root=Path(td);fixture(root,True);audit(root,False)
        (root/'test.bin').write_bytes(b'X')
        try:audit(root,False)
        except ValueError as e:assert 'mismatch' in str(e).lower()
        else:raise AssertionError('Undetected later source corruption')
        print('SELFTEST ATBIOS->HDD->LCD lineage, corruption refusal PASS')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['verify','selftest']);a=p.parse_args()
    try:(selftest if a.action=='selftest' else audit)()
    except (ValueError,AssertionError,KeyError,TypeError,FileNotFoundError) as e:
        print('ERROR:',e,file=sys.stderr);sys.exit(1)
if __name__=='__main__':main()
