from pathlib import Path
import argparse,hashlib,sys
EXPECTED="6a409a292072ee405f202301d2bcc8aca86a4b915fbcc549dd1ef623c69a8f18"
NEW=Path(__file__).with_name("bb_v49_pc.h")
p=argparse.ArgumentParser(description="v49e validated exception-frame PC sampler")
p.add_argument("--blitzbus",type=Path,required=True)
g=p.add_mutually_exclusive_group(required=True)
g.add_argument("--check",action="store_true")
g.add_argument("--apply",action="store_true")
g.add_argument("--restore",action="store_true")
a=p.parse_args()
target=a.blitzbus/"src"/"bb_v49_pc.h"
backup=target.with_name("bb_v49_pc.h.before_v49e")
if not target.is_file():sys.exit("ERROR: source header missing: "+str(target))
current=target.read_bytes();replacement=NEW.read_bytes()
sha=lambda data:hashlib.sha256(data).hexdigest()
if a.restore:
    if not backup.is_file():sys.exit("ERROR: backup missing")
    if current!=replacement:sys.exit("ERROR: installed header changed; refusing rollback")
    if sha(backup.read_bytes())!=EXPECTED:sys.exit("ERROR: backup checksum mismatch")
    target.write_bytes(backup.read_bytes());print("RESTORED",target);sys.exit(0)
if current==replacement:print("v49e already installed",target);sys.exit(0)
if sha(current)!=EXPECTED:sys.exit("ERROR: exact v49d header required; no changes made")
if a.check:print("CHECK PASS: exact v49d header found; no changes");sys.exit(0)
if backup.exists():sys.exit("ERROR: backup already exists; refusing overwrite")
backup.write_bytes(current);target.write_bytes(replacement)
print("INSTALLED",target,"BACKUP",backup)
