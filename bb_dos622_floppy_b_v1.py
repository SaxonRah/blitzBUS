#!/usr/bin/env python3
"""Reversible DOS6 BIOS floppy B: DL=01h compatibility on blitzBUS.

Commands: selftest | probe | apply | verify | restore | recover
Does not touch floppy/HDD image bytes, DOS2, or CPU/JIT paths.
"""
from __future__ import annotations
import argparse, hashlib, json, shutil, tempfile, subprocess, sys
from pathlib import Path
import bb_dos622_atbios_v1 as chain

ROOT=Path(__file__).resolve().parent
TAG='BB_DOS622_FLOPPY_B_V1'
STATE='.bb_dos622_floppy_b_v1_state'
BIOS='src/bb_dos622_bios.inc'
SD='sd_boot/bb_sd_boot.c'
HDD_MANIFEST='.bb_dos622_hdd_v1_state/manifest.json'
sha=chain.sha
atomic=chain.atomic_bytes

def newline(raw,txt):
    if b'\r\n' in raw and b'\n' in raw.replace(b'\r\n',b''):raise ValueError('Mixed line endings refused')
    return txt.replace('\n','\r\n').encode('ascii') if b'\r\n' in raw else txt.encode('ascii')

BIOS_HELPER='''/* BB_DOS622_FLOPPY_B_V1: separate, read-only BIOS floppy DL=01h.
 * Physical A is DOS622.IMG, physical B is the already-opened DESCENTn.IMG.
 * Both are 80 cylinders, 2 heads, 18 sectors; never redirect B onto A.
 */
extern bool bb_sd_dos622_b_image_ready(void);
extern bool bb_sd_b_read_sector(uint32_t lba,uint8_t *dst,size_t size);
static bool BB622_FLASH bb622_b_floppy_int13(MdRuntime *rt)
{
    MdX86 *c=&rt->cpu;
    const uint16_t ax=c->r[MD_X86_AX],cx=c->r[MD_X86_CX],dx=c->r[MD_X86_DX];
    const uint8_t fn=(uint8_t)(ax>>8),count=(uint8_t)ax;
    uint32_t cyl,sec,head,lba,i;
    uint16_t flags;
    if(!bb_sd_dos622_b_image_ready()) {bb622_status(c,0x80u,0u);return true;}
    if(fn==0x00u) {bb622_status(c,0u,0u);return true;}
    if(fn==0x01u) {bb622_status(c,bb622_disk_status,0u);return true;}
    if(fn==0x08u) {
        c->r[MD_X86_CX]=0x4F12u;
        c->r[MD_X86_DX]=0x0102u; /* max head 1, TWO physical floppies */
        c->r[MD_X86_BX]=(uint16_t)((c->r[MD_X86_BX]&0xFF00u)|4u);
        c->es=0x0050u;
        c->r[MD_X86_DI]=0x0100u;
        bb622_status(c,0u,0u);return true;
    }
    if(fn==0x15u) {
        c->r[MD_X86_AX]=0x0100u; /* floppy present */
        flags=md_x86_flags(c);
        md_x86_set_flags(c,(uint16_t)(flags&~MD_X86_FLAG_CF));
        return true;
    }
    if(fn==0x16u) {bb622_status(c,0u,0u);return true;}
    if(fn==0x03u || fn==0x05u) {bb622_status(c,0x03u,0u);return true;} /* write protected */
    if(fn!=0x02u && fn!=0x04u) {bb622_status(c,0x01u,0u);return true;}
    cyl=(uint32_t)(cx>>8)|(((uint32_t)cx&0xC0u)<<2);
    sec=(uint32_t)cx&0x3Fu;
    head=(uint32_t)(dx>>8);
    if(!count || cyl>=80u || head>=2u || !sec || sec>18u) {
        bb622_status(c,0x04u,0u);return true;
    }
    lba=(cyl*2u+head)*18u+(sec-1u);
    if(lba+(uint32_t)count>2880u) {bb622_status(c,0x04u,0u);return true;}
    if((uint32_t)c->r[MD_X86_BX]+(uint32_t)count*512u>65536u) {
        bb622_status(c,0x09u,0u);return true;
    }
    for(i=0;i<count;i++) {
        if(!bb_sd_b_read_sector(lba+i,bb622_sector,512u)) {
            bb622_status(c,0x20u,(uint8_t)i);return true;
        }
        if(fn==0x02u)md_x86_write_block(c,c->es,
            (uint16_t)(c->r[MD_X86_BX]+i*512u),bb622_sector,512u);
    }
    bb622_status(c,0u,count);
    return true;
}
'''

def unique_replace(raw,old,new,label):
    if raw.count(old)!=1:raise ValueError(f'Missing or ambiguous {label}: {raw.count(old)}')
    return raw.replace(old,new,1)

def transform_bios(raw):
    if TAG.encode() in raw:raise ValueError('DOS6 floppy B layer already installed')
    for mark in (b'BB_DOS622_HDD_V1',b'bb622_int13(MdRuntime *rt)',b'bb622_boot_floppy(MdRuntime *rt)'):
        if mark not in raw:raise ValueError(f'Expected BIOS prerequisite missing: {mark.decode()}')
    s=raw
    old=b'static bool BB622_FLASH bb622_int13(MdRuntime *rt)'
    s=unique_replace(s,old,newline(raw,BIOS_HELPER)+old,'BIOS B helper insertion')
    old=b'if ((uint8_t)c->r[MD_X86_DX] == 0x80u) return bb622_hd_int13(rt); /* BB_DOS622_HDD_V1 */'
    new=old+newline(raw,'\n    if ((uint8_t)c->r[MD_X86_DX] == 0x01u) return bb622_b_floppy_int13(rt); /* BB_DOS622_FLOPPY_B_V1 */').rstrip(b'\r\n')
    s=unique_replace(s,old,new,'BIOS INT13 drive dispatch')
    old=b'c->r[MD_X86_DX] = 0x0101u; /* head 1, 1 floppy drive */'
    new=b'c->r[MD_X86_DX] = bb_sd_dos622_b_image_ready()?0x0102u:0x0101u; /* max head 1, physical drive count */'
    s=unique_replace(s,old,new,'A: AH08 physical drive count')
    old=b'case 0x11u: c->r[MD_X86_AX] = 0x0021u; return true; /* CGA, floppy */'
    new=b'case 0x11u: c->r[MD_X86_AX] = bb_sd_dos622_b_image_ready()?0x0061u:0x0021u; return true; /* CGA, one/two floppies */'
    s=unique_replace(s,old,new,'INT11 equipment word')
    old=b'md_x86_write16(c, 0x0040u, 0x0010u, 0x0021u); /* equipment */'
    new=b'md_x86_write16(c, 0x0040u, 0x0010u, bb_sd_dos622_b_image_ready()?0x0061u:0x0021u); /* BB_DOS622_FLOPPY_B_V1 physical equipment */'
    s=unique_replace(s,old,new,'BDA equipment word')
    old=b'printf("[bb-dos622] ENTER real boot sector 0000:7C00, BIOS DL=00; image read-only\\n");'
    new=(b'if(bb_sd_dos622_b_image_ready()) printf("[bb622-floppyb] BIOS DL=01 physical B: read-only 1.44MiB, two-drive equipment\\n");\n    '+old)
    new=new.replace(b'\n',b'\r\n' if b'\r\n' in raw else b'\n')
    s=unique_replace(s,old,new,'physical B boot diagnostic')
    if s.count(TAG.encode())!=3:raise ValueError('Unexpected BIOS marker count')
    return s

def transform_sd(raw):
    if TAG.encode() in raw:raise ValueError('SD helper already present')
    if b'bb_sd_b_read_sector(uint32_t sector' not in raw or b'bb_b_open = true;' not in raw:
        raise ValueError('Existing SD B: image reader/mount is missing')
    old=b'bool bb_sd_b_available(void) { return true; }'
    add=newline(raw,'''/* BB_DOS622_FLOPPY_B_V1: actual physical B media, unlike DOS2's logical always-present unit. */
bool bb_sd_dos622_b_image_ready(void) { return bb_b_open; }
''')
    s=unique_replace(raw,old,add+old,'SD B media readiness')
    if s.count(TAG.encode())!=1:raise ValueError('Expected one B media marker')
    return s

def parent(root):
    p=root/HDD_MANIFEST
    if not p.is_file():raise ValueError('Missing HDD V1 installer manifest')
    ob=json.loads(p.read_bytes())
    if ob.get('tag')!='BB_DOS622_HDD_V1' or not isinstance(ob.get('files'),list):
        raise ValueError('Unexpected HDD V1 manifest shape')
    for rel in (BIOS,SD):
        ent=[x for x in ob['files'] if x.get('path')==rel]
        if len(ent)!=1 or sha((root/rel).read_bytes())!=ent[0].get('installed'):
            raise ValueError('Current source does not match HDD V1 recorded installed SHA: '+rel)
    for rel in ('.bb_dos622_vga0b_stdio_fix_v1_state/manifest.json', '.bb_dos622_hdd_v2_state/manifest.json'):
        p=root/rel
        if not p.is_file():raise ValueError('Missing installed prerequisite: '+rel)
        ob=json.loads(p.read_bytes())
        if ob.get('tag') not in ('BB_DOS622_VGA0B_STDIO_FIX_V1','BB_DOS622_HDD_V2'):
            raise ValueError('Unexpected prerequisite tag: '+rel)

def cascade(root,before,after):
    original=chain.active_metadata(root)
    updated=dict(original)
    digest={sha(before[k]):sha(after[k]) for k in before}
    for _ in range(8*len(original)+8):
        changed=False
        for rel,raw in original.items():
            new,_=chain._update_metadata(raw,digest,rel)
            if updated[rel]!=new:updated[rel]=new;changed=True
            if new!=raw and digest.get(sha(raw))!=sha(new):
                digest[sha(raw)]=sha(new);changed=True
        if not changed:break
    else:raise ValueError('SHA metadata cascade failed convergence')
    if original[HDD_MANIFEST]==updated[HDD_MANIFEST]:
        raise ValueError('HDD V1 manifest did not update both BIOS and SD digests')
    o=json.loads(updated[HDD_MANIFEST]);entries={x.get('path'):x for x in o['files']}
    for rel in (BIOS,SD):
        if entries[rel]['installed']!=sha(after[rel]):raise ValueError('Manifest installed SHA not updated for '+rel)
    return {rel:(original[rel],updated[rel]) for rel in original if original[rel]!=updated[rel]}

def prepare(root=ROOT,verbose=True):
    if (root/STATE).exists():raise ValueError('Already installed; run verify or restore')
    parent(root)
    before={rel:(root/rel).read_bytes() for rel in (BIOS,SD)}
    after={BIOS:transform_bios(before[BIOS]),SD:transform_sd(before[SD])}
    changes={rel:(before[rel],after[rel]) for rel in before}
    changes.update(cascade(root,before,after))
    if verbose:
        for rel in before:print(f'{rel}: {len(before[rel])}->{len(after[rel])} SHA {sha(before[rel])[:12]}->{sha(after[rel])[:12]}')
        print(f'Metadata cascade: {len(changes)-2} files')
        print('PROBE PASS: no repository files modified')
    return changes

def load_state(root):
    p=root/STATE/'manifest.json'
    if not p.is_file():raise ValueError('Missing installer state: '+str(p))
    ob=json.loads(p.read_bytes())
    if ob.get('tag')!=TAG or not isinstance(ob.get('files'),list):raise ValueError('Invalid state schema')
    return ob

def check_rel(rel):
    p=Path(rel)
    if not isinstance(rel,str) or not rel or p.is_absolute() or '..' in p.parts:
        raise ValueError('Unsafe state relative path: '+str(rel))
    return rel

def verify(root=ROOT):
    ob=load_state(root)
    seen=set()
    for e in ob['files']:
        rel=check_rel(e['path']);bk=check_rel(e['backup'])
        if rel in seen:raise ValueError('Duplicate file in manifest: '+rel)
        seen.add(rel)
        if not (root/rel).is_file() or sha((root/rel).read_bytes())!=e['installed']:
            raise ValueError('Current installed file checksum mismatch: '+rel)
        if not (root/STATE/bk).is_file() or sha((root/STATE/bk).read_bytes())!=e['original']:
            raise ValueError('Installer backup checksum mismatch: '+rel)
    print(f'VERIFY PASS: {len(ob["files"])} installed source/metadata files and original backups')

def apply(root=ROOT):
    changes=prepare(root)
    dest=root/STATE
    dest.mkdir()
    ob={'tag':TAG,'files':[]}
    try:
        for i,(rel,(old,new)) in enumerate(changes.items()):
            bn=f'backup_{i:03d}.bin'
            atomic(dest/bn,old)
            ob['files'].append({'path':rel,'backup':bn,'original':sha(old),'installed':sha(new)})
        atomic(dest/'manifest.json',(json.dumps(ob,indent=2)+'\n').encode())
        for rel,(_,new) in changes.items():atomic(root/rel,new)
        verify(root)
    except BaseException:
        for rel,(old,_) in changes.items():atomic(root/rel,old)
        shutil.rmtree(dest,ignore_errors=True)
        raise
    print('APPLIED: DOS6 A: setup floppy + physical B: Descent image, BIOS DL=00/01; DOS2 unchanged')

def restore(root=ROOT,recover=False):
    if not recover:verify(root)
    ob=load_state(root)
    changes={}
    for e in ob['files']:
        rel=check_rel(e['path']);bk=check_rel(e['backup'])
        p=root/STATE/bk
        if not p.is_file() or sha(p.read_bytes())!=e['original']:raise ValueError('Corrupt backup: '+str(p))
        cur=root/rel
        if recover and cur.is_file() and sha(cur.read_bytes()) not in (e['original'],e['installed']):
            raise ValueError('Intervening edits to '+rel+'; refusing recovery')
        changes[rel]=p.read_bytes()
    for rel,raw in changes.items():atomic(root/rel,raw)
    shutil.rmtree(root/STATE)
    print('RESTORE PASS: exact pre-B: source/metadata bytes restored')

def selftest():
    for ending in ('\n','\r\n'):
        with tempfile.TemporaryDirectory() as td:
            r=Path(td)
            (r/'src').mkdir();(r/'sd_boot').mkdir()
            bios='''/* BB_DOS622_HDD_V1 */
static void bb622_status(void *c,int s,int n){}
#include "bb_dos622_hdd_bios_v1.inc"
static bool BB622_FLASH bb622_int13(MdRuntime *rt)
{
 MdX86 *c=&rt->cpu;
 if ((uint8_t)c->r[MD_X86_DX] == 0x80u) return bb622_hd_int13(rt); /* BB_DOS622_HDD_V1 */
 c->r[MD_X86_DX] = 0x0101u; /* head 1, 1 floppy drive */
 return true;
}
static bool BB622_FLASH bb622_bios_interrupt(MdRuntime *rt, uint8_t vector, void *user)
{
 MdX86 *c=&rt->cpu;
 switch(vector){
 case 0x11u: c->r[MD_X86_AX] = 0x0021u; return true; /* CGA, floppy */
 }
}
static bool BB622_FLASH bb622_boot_floppy(MdRuntime *rt)
{
 MdX86 *c=&rt->cpu;
 md_x86_write16(c, 0x0040u, 0x0010u, 0x0021u); /* equipment */
 printf("[bb-dos622] ENTER real boot sector 0000:7C00, BIOS DL=00; image read-only\\n");
}
'''
            sd='''static bool bb_b_open;
static bool bb_generic_b_open;
bool bb_sd_b_available(void) { return true; }
bool bb_sd_b_read_sector(uint32_t sector, uint8_t *data, size_t size)
{
  bb_b_open = true;
  return false;
}
'''
            bsrc=bios.replace('\n',ending).encode();ssrc=sd.replace('\n',ending).encode()
            (r/BIOS).write_bytes(bsrc);(r/SD).write_bytes(ssrc)
            for rel in (BIOS,SD):
                pass
            p=r/HDD_MANIFEST;p.parent.mkdir(parents=True)
            p.write_text(json.dumps({'tag':'BB_DOS622_HDD_V1','files':[{'path':k,'backup':None,'original':None,'installed':sha((r/k).read_bytes())} for k in (BIOS,SD)]}))
            for rel,tag in (('.bb_dos622_hdd_v2_state/manifest.json','BB_DOS622_HDD_V2'),('.bb_dos622_vga0b_stdio_fix_v1_state/manifest.json','BB_DOS622_VGA0B_STDIO_FIX_V1')):
                p=r/rel;p.parent.mkdir(parents=True);p.write_text(json.dumps({'tag':tag,'files':[]}))
            for rel in ('.bb_dos622_ipl_v1_state/manifest.json','.bb_dos622_boot_diag_v1_state/repair.json','.bb_dos622_heap_rescue_v1_state/manifest.json','.bb_dos622_vga12_34_v1_state/manifest.json','.bb_dos622_vga12_30_v1_state/manifest.json','.bb_dos622_keyb92_v1_state/manifest.json'):
                p=r/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps({'tag':'FIXTURE','files':[]}))
            changes=prepare(r,False)
            assert BIOS in changes and SD in changes and HDD_MANIFEST in changes
            apply(r);verify(r);restore(r)
            assert (r/BIOS).read_bytes()==bsrc and (r/SD).read_bytes()==ssrc
            print('SELFTEST '+('CRLF' if ending=='\r\n' else 'LF')+': manifest cascade/rollback PASS')
    # Focused compiled C11 contract tests on exact helper included by transformer.
    cc=shutil.which('cc') or shutil.which('gcc') or shutil.which('clang')
    if not cc:
        print('C11 compiled contract SKIPPED (no compiler)')
    else:
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);source=p/'bios_test.c';binary=p/'bios_test'
            prefix='''#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <assert.h>
#define BB622_FLASH
#define MD_X86_AX 0
#define MD_X86_BX 3
#define MD_X86_CX 1
#define MD_X86_DX 2
#define MD_X86_DI 7
#define MD_X86_FLAG_CF 1u
typedef struct MdX86{uint16_t r[8],es,flags;uint8_t mem[65536];}MdX86;
typedef struct MdRuntime{MdX86 cpu;}MdRuntime;
static uint8_t bb622_sector[512];static uint8_t bb622_disk_status;
static bool ready=true;static uint32_t last_lba,reads;
static bool bb_sd_dos622_b_image_ready(void){return ready;}
static bool bb_sd_b_read_sector(uint32_t lba,uint8_t *dst,size_t sz){assert(sz==512);assert(lba<2880);last_lba=lba;reads++;memset(dst,0x5A,sz);return true;}
static uint16_t md_x86_flags(MdX86*c){return c->flags;}
static void md_x86_set_flags(MdX86*c,uint16_t f){c->flags=f;}
static void bb622_status(MdX86*c,uint8_t s,uint8_t n){bb622_disk_status=s;c->r[0]=(uint16_t)((s<<8)|n);if(s)c->flags|=1;else c->flags&=(uint16_t)~1u;}
static void md_x86_write_block(MdX86*c,uint16_t seg,uint16_t off,const uint8_t*p,size_t n){(void)seg;memcpy(c->mem+off,p,n);}
'''
            tail='''static uint16_t call(MdRuntime*r,uint16_t ax,uint16_t bx,uint16_t cx,uint16_t dx){
 memset(&r->cpu,0,sizeof(r->cpu));r->cpu.r[0]=ax;r->cpu.r[3]=bx;r->cpu.r[1]=cx;r->cpu.r[2]=dx;r->cpu.flags=0x0203;
 assert(bb622_b_floppy_int13(r));return r->cpu.r[0];}
int main(void){MdRuntime*r=calloc(1,sizeof(*r));assert(r);
 assert(call(r,0x0800,0,0,0x0001)==0);assert(r->cpu.r[1]==0x4F12);assert(r->cpu.r[2]==0x0102);
 assert(call(r,0x1500,0,0,0x0001)==0x0100);assert(!(r->cpu.flags&1));
 assert(call(r,0x0202,0x100,0x0012,0x0001)==2);assert(last_lba==18);assert(r->cpu.mem[0x100]=='Z');
 assert(call(r,0x0301,0x100,0x0001,0x0001)==0x0300);assert(r->cpu.flags&1);
 assert(call(r,0x0201,0xFF00,0x0001,0x0001)==0x0900);
 assert(call(r,0x0202,0x100,0x4F12,0x0101)==0x0400);
 ready=false;assert(call(r,0x0201,0x100,0x0001,0x0001)==0x8000);
 assert(reads==2);free(r);puts("C11 DOS6 BIOS physical B: read-only and boundary tests PASS");return 0;}
'''
            # sys contract uses calloc and free
            content=prefix.replace('#include <assert.h>','#include <assert.h>\n#include <stdlib.h>')+BIOS_HELPER+tail
            source.write_text(content)
            q=subprocess.run([cc,'-std=c11','-Wall','-Wextra','-Werror','-Wno-unused-function',str(source),'-o',str(binary)],capture_output=True,text=True)
            if q.returncode:raise RuntimeError('C11 BIOS build failed:\n'+q.stderr)
            out=subprocess.run([str(binary)],capture_output=True,text=True)
            if out.returncode:raise RuntimeError('C11 BIOS assertions failed:\n'+out.stderr)
            print(out.stdout.strip())
    print('SELFTEST PASS: no repository files modified')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['selftest','probe','apply','verify','restore','recover'])
    a=p.parse_args()
    try:{'selftest':selftest,'probe':prepare,'apply':apply,'verify':verify,'restore':restore,'recover':lambda:restore(recover=True)}[a.action]()
    except (OSError,ValueError,RuntimeError,AssertionError,KeyError,TypeError) as e:
        print('ERROR:',e);sys.exit(1)
if __name__=='__main__':main()
