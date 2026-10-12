#!/usr/bin/env python3
"""Read-only FAT16 directory/cluster-chain integrity checker (Python 3 stdlib)."""
import argparse
import collections
import json
import struct
from pathlib import Path


def u16(b, off): return struct.unpack_from('<H', b, off)[0]
def u32(b, off): return struct.unpack_from('<I', b, off)[0]


def audit(path):
    data = Path(path).read_bytes()
    if len(data) < 512: raise ValueError('Image too short')
    bps, spc, reserved, fats, root_entries = u16(data,11), data[13], u16(data,14), data[16], u16(data,17)
    fat_sectors, total16, total32 = u16(data,22), u16(data,19), u32(data,32)
    total = total16 or total32
    if bps != 512 or not spc or spc & (spc-1) or fats != 2 or fat_sectors == 0:
        raise ValueError('Not a supported 512-byte, two-FAT FAT16 image')
    if total * bps != len(data): raise ValueError('BPB image size mismatch')
    root_sectors=(root_entries*32+bps-1)//bps
    root_lba=reserved+fats*fat_sectors
    data_lba=root_lba+root_sectors
    clusters=(total-data_lba)//spc
    if not 4085 <= clusters < 65525: raise ValueError('Cluster count is not FAT16')
    fatlen=fat_sectors*bps
    f1=data[reserved*bps:reserved*bps+fatlen]
    f2=data[(reserved+fat_sectors)*bps:(reserved+2*fat_sectors)*bps]
    if len(f1)<(clusters+2)*2: raise ValueError('FAT too small for data region')
    table=[u16(f1,2*i) for i in range(clusters+2)]
    maxcluster=clusters+1
    cluster_bytes=spc*bps
    problems=[]
    files=[]
    claims=collections.defaultdict(list)
    referenced=set()
    dirs_seen=set()
    def cluster_data(n):
        p=(data_lba+(n-2)*spc)*bps
        return data[p:p+cluster_bytes]
    def walk(start, label, needed=None):
        chain=[]; visited=set(); n=start; issue=None
        if start == 0:
            if needed and needed>0: issue='nonempty entry has start cluster zero'
            return chain,issue
        while True:
            if not 2<=n<=maxcluster:
                issue=f'cluster {n} out of range';break
            if n in visited:
                issue=f'cycle at cluster {n}';break
            visited.add(n);chain.append(n)
            claims[n].append(label);referenced.add(n)
            v=table[n]
            if v>=0xFFF8: break
            if v==0: issue=f'free cluster at {n} within chain';break
            if v==0xFFF7: issue=f'bad cluster marker at {n}';break
            if 0xFFF0<=v<=0xFFF6: issue=f'reserved marker 0x{v:04X} at {n}';break
            if v<2 or v>maxcluster:
                issue=f'out-of-range link {n}->0x{v:04X}';break
            n=v
        if needed is not None:
            expected=(needed+cluster_bytes-1)//cluster_bytes
            if len(chain)!=expected:
                issue=(issue+'; ' if issue else '')+f'chain length {len(chain)} vs expected {expected}'
        return chain,issue
    def listdir(raw,prefix):
        for i in range(0,len(raw)-31,32):
            e=raw[i:i+32]
            if e[0]==0: return
            if e[0]==0xE5 or e[11]==0x0F or e[11]&0x08: continue
            base=e[:8].decode('cp437','replace').rstrip(); ext=e[8:11].decode('cp437','replace').rstrip()
            name=base+('.'+ext if ext else '')
            if name in ('.','..'): continue
            start=u16(e,26); size=u32(e,28); isdir=bool(e[11]&0x10)
            label=prefix+name+('/' if isdir else '')
            chain,issue=walk(start,label,None if isdir else size)
            files.append(dict(path=label,kind='DIR' if isdir else 'FILE',size=size,start=start,clusters=len(chain),issue=issue))
            if issue: problems.append(dict(path=label,problem=issue))
            if isdir and start and start not in dirs_seen:
                dirs_seen.add(start)
                listdir(b''.join(cluster_data(n) for n in chain),label)
    listdir(data[root_lba*bps:(root_lba+root_sectors)*bps],'')
    cross={n:owners for n,owners in claims.items() if len(owners)>1}
    alloc={n for n in range(2,maxcluster+1) if table[n]!=0}
    orphans=alloc-referenced
    raw_invalid=[(n,v) for n in range(2,maxcluster+1) if (v:=table[n]) not in (0,0xFFF7) and not (2<=v<=maxcluster or 0xFFF0<=v<=0xFFFF)]
    return dict(image=str(path),image_bytes=len(data),fat_copies_identical=f1==f2,cluster_count=clusters,cluster_size=cluster_bytes,free_clusters=sum(table[n]==0 for n in range(2,maxcluster+1)),files=files,problems=problems,crosslinks=cross,orphan_clusters=sorted(orphans),raw_invalid=raw_invalid)


def main():
    ap=argparse.ArgumentParser(description='Read-only FAT16 chain verifier')
    ap.add_argument('image');ap.add_argument('--json',dest='json_path');args=ap.parse_args()
    d=audit(args.image)
    print(f"IMAGE: {d['image']} ({d['image_bytes']:,} bytes)")
    print(f"FAT copies identical: {d['fat_copies_identical']}")
    print(f"Clusters: {d['cluster_count']:,}; bytes/cluster: {d['cluster_size']}; free: {d['free_clusters']:,} ({d['free_clusters']*d['cluster_size']:,} bytes)")
    print(f"Directory entries: {len(d['files'])}; broken chains: {len(d['problems'])}; crosslinked clusters: {len(d['crosslinks'])}; orphaned allocated clusters: {len(d['orphan_clusters'])}; invalid FAT values: {len(d['raw_invalid'])}")
    print('\nBROKEN CHAINS:')
    for p in d['problems'][:100]:print(' ',p['path'],p['problem'])
    if len(d['problems'])>100:print(' ... more in JSON')
    print('\nCROSSLINKS (first 30):')
    for n,owners in list(d['crosslinks'].items())[:30]:print(' ',n,owners)
    print('\nINVALID FAT LINKS:')
    for n,v in d['raw_invalid'][:100]:print(f'  cluster {n} -> 0x{v:04X}; owners: {d["crosslinks"].get(n, [f["path"] for f in d["files"] if f["start"]==n])}')
    print('\nINTERESTING FILES:')
    for f in d['files']:
        if any(s in f['path'].upper() for s in ('DESCENT.HOG','DESCENT.PIG','TEST.TXT','DISK.COM')):print(f"  {f['path']} {f['size']:,} bytes; chain={f['clusters']} clusters; issue={f['issue'] or 'none'}")
    if args.json_path:
        Path(args.json_path).write_text(json.dumps(d,indent=2),encoding='utf-8')
        print('\nFull report:',args.json_path)
    print('\nREAD-ONLY: no image was modified')
if __name__=='__main__': main()
