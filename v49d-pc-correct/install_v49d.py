from pathlib import Path
import argparse, hashlib, sys

EXPECTED='86834a05be5ef0035c053be15e2f6a3d916fa3591789bca929954f911d60fd63'
NEW = Path(__file__).with_name('bb_v49_pc.h')
p=argparse.ArgumentParser(description='v49d PC profile corrected frame decoder')
p.add_argument('--blitzbus', type=Path, required=True)
g=p.add_mutually_exclusive_group(required=True)
g.add_argument('--check', action='store_true')
g.add_argument('--apply', action='store_true')
g.add_argument('--restore', action='store_true')
a=p.parse_args()
target=a.blitzbus/'src'/'bb_v49_pc.h'
backup=target.with_name(target.name+'.before_v49d')
def hash_bytes(data): return hashlib.sha256(data).hexdigest()
if not target.is_file(): sys.exit('ERROR: expected header missing: '+str(target))
current=target.read_bytes()
replacement=NEW.read_bytes()
if a.restore:
    if not backup.is_file(): sys.exit('ERROR: rollback backup missing: '+str(backup))
    if current!=replacement: sys.exit('ERROR: source changed since v49d installation; refusing overwrite')
    if hash_bytes(backup.read_bytes())!=EXPECTED: sys.exit('ERROR: rollback backup checksum mismatch')
    target.write_bytes(backup.read_bytes())
    print('RESTORED',target)
    sys.exit(0)
if current==replacement:
    print('v49d already installed:',target)
    sys.exit(0)
if hash_bytes(current)!=EXPECTED: sys.exit('ERROR: expected v49c header not found; no files changed')
if a.check:
    print('CHECK PASS: exact v49c header found; no files changed')
    sys.exit(0)
if backup.exists(): sys.exit('ERROR: rollback backup already exists; refusing overwrite')
backup.write_bytes(current)
target.write_bytes(replacement)
print('INSTALLED',target,'BACKUP',backup)
