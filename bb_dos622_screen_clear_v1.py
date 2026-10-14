#!/usr/bin/env python3
"""DOS 6.22 VGA BIOS AL=0 clear and dedicated physical text LCD surface.

Commands: selftest | probe | apply | verify | restore | recover
Complete files with SHA-verified atomic installation and backup; no git patches.
Requires earlier bb_dos622_lcd_text_v2.py and bb_dos622_atbios_v1.py.
"""
import argparse, hashlib, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path
import bb_dos622_atbios_v1 as atbios

ROOT = Path(__file__).resolve().parent
STATE = '.bb_dos622_screen_clear_v1_state'
TAG = 'BB_DOS622_SCREEN_CLEAR_V1'
VGA = 'src/bb_vga.c'
LCD = 'src/bb_lcd_console.c'
PRIOR = '.bb_dos622_lcd_text_v2_state/manifest.json'
sha = atbios.sha
atomic = atbios.atomic_bytes


def nl_like(raw, s):
    return s.replace('\n','\r\n').encode('utf-8') if b'\r\n' in raw else s.encode('utf-8')


def vga_fix(raw):
    if TAG.encode() in raw:
        raise ValueError('Already installed in VGA source')
    if b'static void scroll_text(' not in raw or b'case 0x06:if(mode==3)scroll_text(' not in raw or b'case 0x07:if(mode==3)scroll_text(' not in raw:
        raise ValueError('VGA video/text dispatch anchors missing')
    loop=b'for(unsigned r=down?top:bottom-n+1;r<=(down?top+n-1:bottom);r++)'
    if raw.count(loop)!=1:
        raise ValueError('Unexpected scroll_text fill loop; refusing to assume AL=0 semantics')
    anchor = b'    if(n>height)n=height;'
    if raw.count(anchor)!=1:
        raise ValueError('Unexpected scroll_text() clamp layout; no changes made')
    replacement = nl_like(raw, '''    /* BB_DOS622_SCREEN_CLEAR_V1: INT 10h AH=06h/07h with AL=0
       clears the entire window, NOT zero rows. Before this fix AH=06h
       cleared nothing; AH=07h could wrap top+n-1 and write outside B800.
       Preserve normal scrolling and cap oversize AL to the window height. */
    if(n==0u || n>height)n=height;''')
    return raw.replace(anchor, replacement, 1)


def lcd_fix(raw):
    if TAG.encode() in raw:
        raise ValueError('Already installed in LCD source')
    if b'BB_DOS622_LCD_TEXT_V2' not in raw or b'void bb622_lcd_text_mirror(const uint8_t *guest)' not in raw:
        raise ValueError('Previous physical DOS6 text LCD mirror absent')
    out=raw
    anchor=b'static int active;'
    if out.count(anchor)!=1:raise ValueError('LCD active flag anchor ambiguous')
    out=out.replace(anchor, anchor+nl_like(out, '\n/* BB_DOS622_SCREEN_CLEAR_V1: DOS6 has a clean dedicated 80x25 LCD surface. */\nstatic uint8_t bb622_text_owns_lcd;'), 1)
    anchor=b'    row=col=0;characters=paint_rows=batches=0;active=1;next_status_ms=0;'
    if out.count(anchor)!=1:raise ValueError('LCD init reset anchor missing')
    out=out.replace(anchor,anchor+b'bb622_text_owns_lcd=0u;',1)
    anchor=b'if((int32_t)(ms-next_status_ms)>=0){status_update();next_status_ms=ms+1000u;}'
    if out.count(anchor)!=1:raise ValueError('LCD HUD refresh anchor changed')
    out=out.replace(anchor,b'if(!bb622_text_owns_lcd && (int32_t)(ms-next_status_ms)>=0){status_update();next_status_ms=ms+1000u;}',1)
    entry=b'void bb622_lcd_text_mirror(const uint8_t *guest)'
    pos=out.index(entry)
    anchor=b'    if (!active || !guest) return;'
    start=out.find(anchor,pos,pos+650)
    if start<0 or out.count(anchor)!=1:raise ValueError('Cannot locate DOS6 B800 mirror entry')
    addition=nl_like(out, '''
    if (!bb622_text_owns_lcd) {
        /* DOS2 diagnostic HUD occupied the lower 120 physical pixels.
           Clear the WHOLE panel exactly once at DOS6 text-mode takeover.
           Invalidate every cached text cell so even spaces are repainted.
           The DOS2/HUD path remains unchanged outside the DOS6 mirror. */
        bb622_text_owns_lcd=1u;
        mr_pico_ili9341_fill_screen(&lcd,0x0000u,480,320);
        memset(cells,0,sizeof cells);
        memset(dirty,1,sizeof dirty);
        puts("[bb622-lcdclear] DOS6 text LCD takeover, full 480x320 clear; DOS2 HUD disabled");
        fflush(stdout);
    }''')
    out=out[:start+len(anchor)]+addition+out[start+len(anchor):]
    return out


def state(root):
    p=root/STATE/'manifest.json'
    if not p.is_file():raise ValueError(f'Missing installer state {p}')
    ob=json.loads(p.read_bytes())
    if ob.get('tag')!=TAG or not isinstance(ob.get('files'),list):raise ValueError('Unexpected installer state schema')
    return ob


def current_prior(root):
    p=root/PRIOR
    if not p.is_file():raise ValueError(f'Missing prerequisite LCD V2 manifest: {p}')
    o=json.loads(p.read_bytes())
    if o.get('tag')!='BB_DOS622_LCD_TEXT_V2' or not isinstance(o.get('files'),list):
        raise ValueError('Unrecognized LCD V2 state; not safe to stack')
    targets={f.get('path'):f for f in o['files']}
    if LCD not in targets or not (root/LCD).is_file():raise ValueError('LCD V2 source record missing')
    if sha((root/LCD).read_bytes())!=targets[LCD]['installed']:
        raise ValueError('LCD source modified since LCD V2 installation; refusing')
    # VGA source is the unchanged public base for the DOS6 chain, and is
    # validated structurally (clear and both scroll directions) in vga_fix().
    for pth in ('src/bb_dos622_bios.inc','sd_boot/bb_sd_boot.c'):
        p=root/pth
        if not p.is_file() or b'BB_DOS622_HDD_V1' not in p.read_bytes():
            raise ValueError(f'Required HDD V1 marker missing: {pth}')
    return o


def cascade(root, before, after):
    original=atbios.active_metadata(root)
    updated=dict(original)
    changes={sha(before[k]):sha(after[k]) for k in before}
    for iteration in range(len(original)*8+8):
        progress=False
        for rel, base in original.items():
            new,hits=atbios._update_metadata(base,changes,rel)
            if new!=updated[rel]:updated[rel]=new;progress=True
            if new!=base: changes[sha(base)]=sha(new)
        if not progress:break
    else:raise ValueError('SHA metadata cascade failed to converge')
    prior_changed=False
    for rel,base in original.items():
        if rel==PRIOR and updated[rel]!=base:prior_changed=True
    if not prior_changed:raise ValueError('LCD V2 manifest not updated in metadata chain')
    return {r:(original[r],updated[r]) for r in original if original[r]!=updated[r]}


def prepare(root=ROOT,report=True):
    if (root/STATE).exists():raise ValueError(f'Already installed: {STATE}; use verify/restore')
    current_prior(root)
    for rel in (VGA,LCD):
        if not (root/rel).is_file():raise ValueError(f'Missing source {rel}')
    before={VGA:(root/VGA).read_bytes(), LCD:(root/LCD).read_bytes()}
    after={VGA:vga_fix(before[VGA]), LCD:lcd_fix(before[LCD])}
    changes={k:(before[k],after[k]) for k in (VGA,LCD)}
    metas=cascade(root,before,after)
    changes.update(metas)
    if report:
        for k in (VGA,LCD):print(f'{k}: {len(before[k])}->{len(after[k])} SHA {sha(before[k])[:12]}->{sha(after[k])[:12]}')
        print(f'Metadata updates: {len(metas)} (prerequisite manifest and dependent chains)')
        print('PROBE PASS: no files modified')
    return changes


def verify(root=ROOT):
    manifest=state(root)
    for ent in manifest['files']:
        rel=ent['path'];p=root/rel; b=root/STATE/ent['backup']
        if not p.is_file() or sha(p.read_bytes())!=ent['installed']:
            raise ValueError(f'Installed SHA mismatch: {p}')
        if not b.is_file() or sha(b.read_bytes())!=ent['original']:
            raise ValueError(f'Original backup SHA mismatch: {b}')
    print(f'VERIFY PASS: {len(manifest["files"])} current source/metadata entries and backups')


def apply(root=ROOT):
    changes=prepare(root)
    d=root/STATE
    d.mkdir()
    m={'tag':TAG,'files':[]}
    try:
        for idx,(rel,(old,new)) in enumerate(changes.items()):
            bn=f'backup_{idx:03d}.bin';atomic(d/bn,old)
            m['files'].append({'path':rel,'backup':bn,'original':sha(old),'installed':sha(new)})
        atomic(d/'manifest.json',(json.dumps(m,indent=2)+'\n').encode())
        for rel,(_,new) in changes.items():atomic(root/rel,new)
        verify(root)
    except BaseException:
        for rel,(old,_) in changes.items():atomic(root/rel,old)
        shutil.rmtree(d,ignore_errors=True)
        raise
    print('APPLIED: correct shared VGA scroll-clear semantics + DOS6-only LCD takeover; DOS2 disk/boot untouched')


def restore(root=ROOT,recover=False):
    if not recover:verify(root)
    m=state(root)
    for ent in m['files']:
        p=root/ent['path'];bk=root/STATE/ent['backup']
        if not bk.is_file() or sha(bk.read_bytes())!=ent['original']:raise ValueError(f'Backup damaged: {bk}')
        if recover and p.is_file() and sha(p.read_bytes()) not in (ent['original'],ent['installed']):
            raise ValueError(f'Unknown modified file; refusing recovery: {p}')
    for ent in m['files']:atomic(root/ent['path'],(root/STATE/ent['backup']).read_bytes())
    shutil.rmtree(root/STATE)
    print('RESTORED: exact original sources + metadata; new state removed')


def test_c_scroll():
    cc=shutil.which('cc') or shutil.which('gcc') or shutil.which('clang')
    if not cc:
        print('SELFTEST C11: skipped (no GCC/Clang); Python AL=0 behavioral tests still execute')
        return
    # The exact loop structure from the upstream scroll_text(), with the V1
    # normalization, linked against a bounded 80x25 B800 region and sentinels.
    c=r'''#include <stdint.h>
#include <string.h>
#include <assert.h>
#include <stdio.h>
static uint8_t guest[0xB8000u+4000u+32u];
static uint8_t *mem=guest;
static void scroll_text(unsigned top,unsigned left,unsigned bottom,unsigned right,unsigned n,uint8_t fill,int down){
    if(top>24||left>79)return;
    if(bottom>24)bottom=24;if(right>79)right=79;
    if(bottom<top||right<left)return;
    unsigned width=right-left+1,height=bottom-top+1;
    /* BB_DOS622_SCREEN_CLEAR_V1 */
    if(n==0u || n>height)n=height;
    if(n&&n<height){
        if(down){for(int r=(int)bottom;r>=(int)(top+n);r--)memmove(mem+0xB8000+(r*80+left)*2,mem+0xB8000+((r-n)*80+left)*2,width*2);}
        else {for(unsigned r=top;r+n<=bottom;r++)memmove(mem+0xB8000+(r*80+left)*2,mem+0xB8000+((r+n)*80+left)*2,width*2);}
    }
    for(unsigned r=down?top:bottom-n+1;r<=(down?top+n-1:bottom);r++){
        for(unsigned c=left;c<=right;c++) {unsigned o=0xB8000+(r*80+c)*2;mem[o]=' ';mem[o+1]=fill;}
        if(!n)break;
    }
}
static uint8_t ch(unsigned y,unsigned x){return mem[0xB8000+2*(80*y+x)];}
static uint8_t at(unsigned y,unsigned x){return mem[0xB8000+2*(80*y+x)+1];}
static void prep(void){memset(guest,0xC3,sizeof guest);for(unsigned y=0;y<25;y++)for(unsigned x=0;x<80;x++){unsigned o=0xB8000+2*(y*80+x);guest[o]='A'+y%26;guest[o+1]=0x1F;}}
static void guard(void){for(unsigned i=0;i<32;i++)assert(guest[0xB8000+4000+i]==0xC3);}
int main(void){
  prep();scroll_text(0,0,24,79,0,7,0);for(unsigned y=0;y<25;y++)for(unsigned x=0;x<80;x++){assert(ch(y,x)==' '&&at(y,x)==7);}guard();
  prep();scroll_text(0,0,24,79,0,0x17,1);for(unsigned y=0;y<25;y++)for(unsigned x=0;x<80;x++){assert(ch(y,x)==' '&&at(y,x)==0x17);}guard();
  prep();scroll_text(3,5,8,12,0,0x31,0);for(unsigned y=0;y<25;y++)for(unsigned x=0;x<80;x++){
    if(y>=3&&y<=8&&x>=5&&x<=12)assert(ch(y,x)==' '&&at(y,x)==0x31);
    else assert(ch(y,x)=='A'+y%26 && at(y,x)==0x1F);
  }guard();
  prep();scroll_text(3,5,8,12,0,0x2E,1);for(unsigned y=0;y<25;y++)for(unsigned x=0;x<80;x++){
    if(y>=3&&y<=8&&x>=5&&x<=12)assert(ch(y,x)==' '&&at(y,x)==0x2E);
    else assert(ch(y,x)=='A'+y%26 && at(y,x)==0x1F);
  }guard();
  prep();scroll_text(0,0,24,79,1,7,0);assert(ch(0,0)=='B' && ch(23,0)=='Y' && ch(24,0)==' ');guard();
  prep();scroll_text(0,0,24,79,1,7,1);assert(ch(1,0)=='A' && ch(0,0)==' ');guard();
  prep();scroll_text(0,0,24,79,255,7,1);for(unsigned y=0;y<25;y++)assert(ch(y,0)==' ');guard();
  puts("C11 scroll clear PASS: full/partial, up/down, 1-line, oversized, sentinels");return 0;
}'''
    with tempfile.TemporaryDirectory() as td:
        src=Path(td)/'t.c';exe=Path(td)/('t.exe' if os.name=='nt' else 't')
        src.write_text(c)
        p=subprocess.run([cc,'-std=c11','-Wall','-Wextra','-O1',str(src),'-o',str(exe)],capture_output=True,text=True)
        if p.returncode:raise ValueError(f'C11 scroll test compile failed: {p.stderr}')
        p=subprocess.run([str(exe)],capture_output=True,text=True)
        if p.returncode:raise ValueError(f'C11 scroll test failure: {p.stdout} {p.stderr}')
        print(p.stdout.strip())


def selftest():
    test_c_scroll()
    for ending in ('LF','CRLF'):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root/'src').mkdir();(root/'.bb_dos622_lcd_text_v2_state').mkdir()
            (root/'sd_boot').mkdir()
            vga=(b'static void scroll_text(\n' + b'    if(n>height)n=height;\n' + b'    for(unsigned r=down?top:bottom-n+1;r<=(down?top+n-1:bottom);r++)\n' +
                 b'case 0x06:if(mode==3)scroll_text(\ncase 0x07:if(mode==3)scroll_text(\n')
            lcd=(b'static int active;\n    row=col=0;characters=paint_rows=batches=0;active=1;next_status_ms=0;\n'
                 b'if((int32_t)(ms-next_status_ms)>=0){status_update();next_status_ms=ms+1000u;}\n'
                 b'/* BB_DOS622_LCD_TEXT_V2 */\nvoid bb622_lcd_text_mirror(const uint8_t *guest)\n{\n'
                 b'    if (!active || !guest) return;\n}\n')
            if ending=='CRLF':vga=vga.replace(b'\n',b'\r\n');lcd=lcd.replace(b'\n',b'\r\n')
            (root/VGA).write_bytes(vga);(root/LCD).write_bytes(lcd)
            (root/'src/bb_dos622_bios.inc').write_bytes(b'BB_DOS622_HDD_V1')
            (root/'sd_boot/bb_sd_boot.c').write_bytes(b'BB_DOS622_HDD_V1')
            (root/PRIOR).write_text(json.dumps({'tag':'BB_DOS622_LCD_TEXT_V2','files':[{'path':LCD,'backup':'saved.bin','original':sha(b'old'), 'installed':sha(lcd)}]}))
            (root/'.bb_dos622_lcd_text_v2_state/saved.bin').write_bytes(b'old')
            for rel in ['.bb_dos622_ipl_v1_state/manifest.json','.bb_dos622_boot_diag_v1_state/repair.json', '.bb_dos622_heap_rescue_v1_state/manifest.json','.bb_dos622_vga12_34_v1_state/manifest.json','.bb_dos622_vga12_30_v1_state/manifest.json', '.bb_dos622_keyb92_v1_state/manifest.json']:
                p=root/rel;p.parent.mkdir(exist_ok=True);p.write_text(json.dumps({'files':{VGA:{'installed':sha(vga)},LCD:{'installed':sha(lcd)}}}))
            prev=sorted(root.rglob('*.json'))+[root/VGA,root/LCD]
            snapshots={str(p.relative_to(root)):p.read_bytes() for p in prev}
            prepare(root,False)
            apply(root);verify(root)
            assert b'n==0u || n>height' in (root/VGA).read_bytes()
            assert b'bb622_text_owns_lcd' in (root/LCD).read_bytes()
            restore(root)
            for rel,old in snapshots.items():assert (root/rel).read_bytes()==old,rel
            print(f'SELFTEST {ending} PASS: anchors, SHA cascade, apply, verify, byte-exact restore')
    # refusal: no HDD / wrong LCD SHA
    with tempfile.TemporaryDirectory() as td:
        root=Path(td);(root/'.bb_dos622_lcd_text_v2_state').mkdir()
        try:prepare(root,False)
        except ValueError as e:assert 'source' in str(e).lower() or 'missing' in str(e).lower()
        else:raise AssertionError('Expected missing-source refusal')
    print('SELFTEST PASS: no repository files touched')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['selftest','probe','apply','verify','restore','recover'])
    a=p.parse_args()
    try:
        {'selftest':selftest,'probe':prepare,'apply':apply,'verify':verify,'restore':restore,'recover':lambda:restore(recover=True)}[a.action]()
    except (ValueError, OSError, AssertionError, KeyError, TypeError, json.JSONDecodeError) as e:
        print('ERROR:',e,file=sys.stderr);sys.exit(1)
if __name__=='__main__':main()
