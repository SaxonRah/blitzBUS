from pathlib import Path
import argparse,hashlib,re,sys
HERE=Path(__file__).resolve().parent
OLD_SHA="d24c4e887d4a0192aa7ac4a18e2371d921d8a075e2e18248714430584df14274"
p=argparse.ArgumentParser(description="v49f dual-candidate SysTick PC profiler")
p.add_argument('--blitzbus',type=Path,required=True)
p.add_argument('--hz',type=int,choices=(100,1000),default=100)
g=p.add_mutually_exclusive_group(required=True)
g.add_argument('--check',action='store_true');g.add_argument('--apply',action='store_true');g.add_argument('--restore',action='store_true')
a=p.parse_args(); header=a.blitzbus/'src'/'bb_v49_pc.h';live=a.blitzbus/'src'/'bb_live.c'
hbackup=header.with_name('bb_v49_pc.h.before_v49f');lbackup=live.with_name('bb_live.c.before_v49f')
if not header.is_file() or not live.is_file():sys.exit('ERROR: missing bb_live.c or profiler header')
replacement=(HERE/'bb_v49_pc.h').read_text().replace('#define BB49_SAMPLE_HZ 100u',f'#define BB49_SAMPLE_HZ {a.hz}u')
source=header.read_bytes(); current=live.read_bytes()
sha=lambda b:hashlib.sha256(b).hexdigest()
old_call='bb49_init(clock_get_hz(clk_sys)/1000u);'
new_call='bb49_init(clock_get_hz(clk_sys)/BB49_SAMPLE_HZ);'
if a.restore:
    if not hbackup.exists() or not lbackup.exists():sys.exit('ERROR: missing backup')
    if new_call.encode() not in current or 'v49f: dual-candidate' not in header.read_text():sys.exit('ERROR: unexpected installed version; refuse restore')
    header.write_bytes(hbackup.read_bytes());live.write_bytes(lbackup.read_bytes());print('RESTORED both source files');sys.exit(0)
if sha(source)!=OLD_SHA:sys.exit('ERROR: exact v49e header expected; no changes made')
if current.count(old_call.encode())!=1:sys.exit('ERROR: expected exactly one original 1000 Hz init call; no changes made')
if hbackup.exists() or lbackup.exists():sys.exit('ERROR: v49f backup exists; no changes made')
if a.check:print(f'CHECK PASS: exact v49e header, one clock init; target hz={a.hz}; no changes');sys.exit(0)
# Stage both byte replacements before touching originals.
newlive=current.replace(old_call.encode(),new_call.encode())
hbackup.write_bytes(source);lbackup.write_bytes(current)
try:
    header.write_text(replacement);live.write_bytes(newlive)
except Exception:
    header.write_bytes(source);live.write_bytes(current);raise
print(f'INSTALLED v49f sample_hz={a.hz}');print('BACKUPS:',hbackup,lbackup)
