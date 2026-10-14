#!/usr/bin/env python3
"""READ ONLY: inspect DOS622_HDD.IMG boot chain, FAT16 and DOS boot files."""
import argparse,struct,sys
from pathlib import Path

def u16(b,p):return struct.unpack_from('<H',b,p)[0]
def u32(b,p):return struct.unpack_from('<I',b,p)[0]
def audit(path:Path):
    size=path.stat().st_size
    issues=[];info=[]
    def issue(s):issues.append(s)
    with path.open('rb') as f:
        m=f.read(512)
        if len(m)<512:raise ValueError('Image too short for MBR')
        if m[510:512]!=b'\x55\xaa':issue('MBR boot signature missing')
        entries=[]
        for i in range(4):
            q=m[446+i*16:462+i*16]
            entries.append((q[0],q[4],u32(q,8),u32(q,12)))
        active=[(i,x) for i,x in enumerate(entries) if x[0]==0x80 and x[1] in (4,6,14)]
        if not active:issue('No active DOS FAT16 partition in MBR');part=(0,(0,0,0,0))
        else:part=active[0]
        i,(boot,typ,start,count)=part
        info.append(f'MBR signature={m[510:512].hex()} boot_code_nonzero={any(m[:446])} size={size:,} bytes')
        info.append(f'Partition={i+1} active={boot==0x80} type=0x{typ:02X} start={start} sectors={count}')
        if not any(m[:446]):issue('MBR bootstrap code is entirely zero')
        if count==0 or (start+count)*512>size:issue('Partition exceeds disk image')
        if count==0 or (start+count)*512>size:return info,issues
        f.seek(start*512);b=f.read(512)
        if b[510:512]!=b'\x55\xaa':issue('Partition boot-sector signature missing')
        if b[0] not in (0xe9,0xeb):issue('Partition boot-sector jump missing')
        bps=u16(b,11);spc=b[13];reserved=u16(b,14);fats=b[16];root_entries=u16(b,17);spf=u16(b,22)
        info.append(f'PBR boot_sector={b[:8].hex()} bytes_per_sector={bps} sectors_per_cluster={spc} FATs={fats} root_entries={root_entries} sectors_per_FAT={spf}')
        if bps!=512 or spc<1 or reserved<1 or fats not in (1,2) or root_entries<1 or spf<1:
            issue('Invalid FAT16 BPB');return info,issues
        root_sect=start+reserved+fats*spf
        root_bytes=root_entries*32
        f.seek(root_sect*512)
        entries=f.read(root_bytes)
        found={}
        for offset in range(0,len(entries)-31,32):
            e=entries[offset:offset+32]
            if not e or e[0]==0:break
            if e[0]==0xe5 or (e[11]&0x0f)==0x0f or (e[11]&0x08):continue
            name=e[:8].decode('ascii','replace').rstrip()+'.'+e[8:11].decode('ascii','replace').rstrip() if e[8:11].strip() else e[:8].decode('ascii','replace').rstrip()
            found[name.upper()]={'size':u32(e,28),'cluster':u16(e,26),'attr':e[11]}
        for name in ['IO.SYS','MSDOS.SYS','COMMAND.COM']:
            value=found.get(name)
            if value is None:issue(f'Missing root file {name}')
            elif value['size']==0:issue(f'{name} has zero bytes (install incomplete or placeholders)')
            elif value['cluster']<2:issue(f'{name} has invalid first cluster')
            info.append(f'{name}: '+(str(value) if value else 'MISSING'))
        info.append('Root DOS directory: '+str(found.get('DOS','MISSING')))
        if not found.get('DOS'):issue('C:\\DOS directory is absent (may be a custom install path)')
    return info,issues

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('image',help='Path to DOS622_HDD.IMG on a disconnected SD or copied image');args=ap.parse_args()
    p=Path(args.image)
    if not p.is_file():ap.error('No such image: '+str(p))
    info,issues=audit(p)
    print('IMAGE:',p)
    for v in info:print('  '+v)
    for e in issues:print('WARNING:',e)
    if issues:print('AUDIT: INCOMPLETE / needs attention (image was not modified)');sys.exit(2)
    print('AUDIT: filesystem and boot-file checks PASS; guest C: boot still requires hardware test')
if __name__=='__main__':main()
