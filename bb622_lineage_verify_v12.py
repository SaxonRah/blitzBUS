#!/usr/bin/env python3
"""READ-ONLY byte-exact DOS 6.22 installer-chain auditor.

Walks newest-to-oldest: ATBIOS -> HDD V1 -> LCD V2 -> SCREEN CLEAR V1 -> HDD V2 -> VGA0B/KEYS V1 -> VGA0B STDIO V1.
Restores each layer into a virtual in-memory view (does NOT touch disk) and
proves every installed digest and original backup across all 13 layers.
Command: python bb622_lineage_verify_v11.py verify|selftest
"""
import argparse, hashlib, json, sys, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
LAYERS=[
    ('.bb_dos622_atbios_v1_state','BB_DOS622_ATBIOS_V1'),
    ('.bb_dos622_hdd_v1_state','BB_DOS622_HDD_V1'),
    ('.bb_dos622_lcd_text_v2_state','BB_DOS622_LCD_TEXT_V2'),
    ('.bb_dos622_screen_clear_v1_state','BB_DOS622_SCREEN_CLEAR_V1'),
    ('.bb_dos622_hdd_v2_state','BB_DOS622_HDD_V2'),
    ('.bb_dos622_vga0b_keys_v1_state','BB_DOS622_VGA0B_KEYS_V1'),
    ('.bb_dos622_vga0b_stdio_fix_v1_state','BB_DOS622_VGA0B_STDIO_FIX_V1'),
    ('.bb_dos622_floppy_b_v1_state','BB_DOS622_FLOPPY_B_V1'),
    ('.bb_dos622_ega_info_v1_state','BB_DOS622_EGA_INFO_V1'),
    ('.bb_dos622_color_cells_v1_state','BB_DOS622_COLOR_CELLS_V1'),
    ('.bb_dos622_swap_lcd_v2_state','BB_DOS622_SWAP_LCD_V2'),
    ('.bb_dos622_boot_eject_v1_state','BB_DOS622_BOOT_EJECT_V1'),
    ('.bb622_descent_swap_v1_state','BB622_DESCENT_SWAP_V1'),
]

def sha(b):return hashlib.sha256(b).hexdigest()

def checkrel(path):
    p=Path(path)
    if not isinstance(path,str) or p.is_absolute() or '..' in p.parts or not p.parts:
        raise ValueError(f'Unsafe installer relative path: {path}')
    return path

def audit(root=ROOT,verbose=True):
    virtual={}
    def read(rel):
        rel=checkrel(rel)
        if rel in virtual:return virtual[rel]
        p=root/rel
        return p.read_bytes() if p.is_file() else None
    counts=[]
    prior=[(folder,tag) for folder,tag in LAYERS if (root/folder/'manifest.json').is_file()]
    if len(prior)<3:raise ValueError('Required ATBIOS/HDD/LCD layers missing')
    if [tag for _,tag in prior[:3]] != [tag for _,tag in LAYERS[:3]]:
        raise ValueError('Unexpected install chain; refusing incomplete history')
    for folder,tag in reversed(prior):
        rel=f'{folder}/manifest.json';raw=read(rel)
        if raw is None:raise ValueError(f'Missing layer record {rel}')
        ob=json.loads(raw)
        if ob.get('tag')!=tag or not isinstance(ob.get('files'),list):
            raise ValueError(f'Invalid manifest {rel}')
        if not ob['files']:raise ValueError(f'Empty manifest {rel}')
        entries=ob['files']
        seen=set();rollback={}
        for e in entries:
            path=checkrel(e['path']);inst=e.get('installed');orig=e.get('original');back=e.get('backup')
            if path in seen:raise ValueError(f'Duplicate path {path} in {rel}')
            seen.add(path)
            if not isinstance(inst,str) or len(inst)!=64:raise ValueError(f'Malformed SHA for {path}')
            data=read(path)
            if data is None or sha(data)!=inst:
                raise ValueError(f'{tag} current/virtual installed checksum mismatch: {path}')
            if orig is None:
                if back is not None:raise ValueError(f'Unexpected backup for new file {path}')
                rollback[path]=None
            else:
                if not isinstance(back,str) or not back.startswith('backup_'):
                    # Other stages use original_00.bin or other fixed basename.
                    if not isinstance(back,str) or not back.endswith('.bin'):
                        raise ValueError(f'Invalid backup field for {path}')
                backpath=f'{folder}/{checkrel(back)}'
                backup=read(backpath)
                if backup is None or sha(backup)!=orig:
                    raise ValueError(f'{tag} damaged original backup for {path}: {backpath}')
                rollback[path]=backup
        virtual.update(rollback)
        counts.append((tag,len(entries)))
    if verbose:
        for tag,n in reversed(counts):print(f'{tag}: PASS {n} installed SHA transitions and byte-exact backups')
        print('LINEAGE PASS: verified current files plus all earlier installed states, without edits')
    return counts


def selftest():
    with tempfile.TemporaryDirectory() as td:
        root=Path(td)
        f=root/'file.bin'; f.write_bytes(b'0')
        # Each stage snapshots the version present before installation.
        for i,(folder,tag) in enumerate(LAYERS):
            d=root/folder;d.mkdir()
            old=f.read_bytes();d.joinpath('backup_000.bin').write_bytes(old)
            newer=str(i+1).encode();f.write_bytes(newer)
            ob={'tag':tag,'files':[{'path':'file.bin','backup':'backup_000.bin','original':sha(old),'installed':sha(newer)}]}
            d.joinpath('manifest.json').write_text(json.dumps(ob))
        audit(root,False)
        f.write_bytes(b'bad')
        try:audit(root,False)
        except ValueError as e:assert 'mismatch' in str(e).lower()
        else:raise AssertionError('Failed to catch corrupt latest file')
        f.write_bytes(str(len(LAYERS)).encode())
        (root/LAYERS[1][0]/'backup_000.bin').write_bytes(b'corrupt')
        try:audit(root,False)
        except ValueError as e:assert 'backup' in str(e).lower()
        else:raise AssertionError('Failed to catch corrupt ancestor backup')
    print('SELFTEST PASS: thirteen-stage audit, latest corruption, historical backup corruption')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['verify','selftest']);args=p.parse_args()
    try: (selftest if args.action=='selftest' else audit)()
    except (ValueError,OSError,KeyError,TypeError,AssertionError,json.JSONDecodeError) as e:
        print('ERROR:',e,file=sys.stderr);sys.exit(1)
if __name__=='__main__':main()
