from pathlib import Path
import argparse,shutil
MARK='BB_GENERIC_DISK_V1'
def one(s,old,new,tag):
 n=s.count(old)
 if n!=1:raise RuntimeError(f'{tag}: expected one anchor, found {n}. Nothing changed.')
 return s.replace(old,new,1)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--root',default=r'C:\blitzBUS');ap.add_argument('--restore',action='store_true');a=ap.parse_args()
 sd=Path(a.root)/'sd_boot';boot=sd/'bb_sd_boot.c';drv=sd/'bb_msdos2_boot.c';back=sd/'generic_disk_v1_backup'
 if a.restore:
  for p in (boot,drv):
   if not (back/p.name).is_file():raise RuntimeError('Missing backup '+str(p))
  for p in (boot,drv):shutil.copy2(back/p.name,p)
  print('Restored previous virtual floppy firmware sources');return
 if not boot.exists() or not drv.exists():raise RuntimeError('Install the current live-swap virtual B: firmware first')
 b=boot.read_text();d=drv.read_text()
 if MARK in b:print('Already installed');return
 if 'BB_DESCENT_LIVESWAP_V1' not in b or 'bb_sd_b_select(unsigned' not in b or 'bb_sd_b_read_sector(uint32_t' not in b:raise RuntimeError('Live-swap baseline not present. No files changed.')
 if 'if (vector == 0xF6u' not in d:raise RuntimeError('Missing INT F6 handler. No files changed.')
 # Append new independent backend. Preserve original read handler as fallback for numeric DISK mode.
 src=Path(__file__).with_name('generic_mount.c.txt').read_text()
 b+='\n'+src+'\n/* '+MARK+' */\n'
 b=one(b,'    if (!bb_b_open || !data || size != 512u || sector >= 2880u) return false;',
 '''    if (bb_generic_b_open) return bb_sd_b_read_generic(sector,data,size);
    if (!bb_b_open || !data || size != 512u || sector >= 2880u) return false;''','read dispatch')
 b=one(b,'bool bb_sd_b_available(void) { return bb_b_open; }','bool bb_sd_b_available(void) { return true; }','B availability')
 # Forward declarations for functions defined later in the same translation unit.
 b=one(b,'/* BB_DESCENT_VFLOPPY_B_V1',
 '''static bool bb_generic_b_open;
static bool bb_sd_b_read_generic(uint32_t, uint8_t *, size_t);
/* BB_DESCENT_VFLOPPY_B_V1''','forward decl')
 # The generic FAT16 resolver uses the existing C: sector cache; forward declaration already present in source.
 # DOS hook: copy DS:DX nul-terminated path; avoid reading outside 128-byte command tail.
 key='    if (vector == 0xF6u && ((cpu->r[MD_X86_AX] >> 8) & 0xFFu) == 0xB0u) {'
 hook='''    if (vector == 0xF6u && ((cpu->r[MD_X86_AX] >> 8) & 0xFFu) == 0xB1u) {
        char path[128]; unsigned i; bool ok=false;
        uint16_t dx=cpu->r[MD_X86_DX];
        for (i=0u;i<sizeof(path)-1u;i++) {
            uint8_t c=md_x86_read8(cpu,cpu->ds,(uint16_t)(dx+i));
            if (!c || c==13u)break;
            if (c<32u || c>=127u)break;
            path[i]=(char)c;
        }
        path[i]=0;
        if (i>0u && i<sizeof(path)-1u)ok=bb_sd_b_select_path(path);
        cpu->r[MD_X86_AX]=(uint16_t)((ok?0u:1u)<<8);
        return true;
    }
'''
 d=one(d,key,hook+key,'DISK F6 B1 hook')
 d=one(d,'extern bool bb_sd_b_select(unsigned);','extern bool bb_sd_b_select_path(const char *);\nextern bool bb_sd_b_select(unsigned);','mount extern')
 # A generic mounted image makes B: available. Existing B changes reported to DOS on each media check.
 back.mkdir(exist_ok=True)
 for p in (boot,drv):
  if not (back/p.name).exists():shutil.copy2(p,back/p.name)
 boot.write_text(b);drv.write_text(d)
 print('Installed generic DISK SD:/C: path support. Original firmware sources backed up:',back)
 print('Only 1.44 MB FAT12 floppy images are supported by this first build. B: is read-only.')
if __name__=='__main__': main()
