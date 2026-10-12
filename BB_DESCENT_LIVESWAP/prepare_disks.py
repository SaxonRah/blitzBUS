from pathlib import Path
import argparse,shutil,os

def main():
 p=argparse.ArgumentParser(description='Stage original Descent floppy images on the SD card for virtual B:')
 p.add_argument('--source',default=r'C:\blitzBUS\games');p.add_argument('--sd',default=r'O:\BLITZBUS')
 p.add_argument('--select',type=int,choices=range(1,6),default=1)
 p.add_argument('--selection-only',action='store_true')
 a=p.parse_args();src=Path(a.source);dst=Path(a.sd)
 if not dst.is_dir():raise SystemExit('Missing destination directory: '+str(dst))
 if not a.selection_only:
  ops=[]
  for n in range(1,6):
   f=src/f'descent_disk{n}.img'; d=dst/f'DESCENT{n}.IMG'
   if not f.is_file() or f.stat().st_size != 1474560:
    raise SystemExit(f'Invalid/missing floppy {n}: {f} (expected 1474560 bytes)')
   ops.append((f,d))
  for f,d in ops:
   shutil.copyfile(f,d)
   if d.stat().st_size != 1474560:raise SystemExit('Copy verification failed: '+str(d))
   print(f'Disk copied: {f.name} -> {d.name} ({d.stat().st_size} bytes)')
 f=dst/'B_DISK.TXT'
 with open(f,'wb') as h:
  h.write(str(a.select).encode('ascii')+b'\r\n');h.flush();os.fsync(h.fileno())
 print(f'Selected floppy B: disk {a.select}. Turn off Pico before editing; safely eject SD.')
if __name__=='__main__':main()
