#!/usr/bin/env python3
"""DOS 6.22 genuine COMMAND.COM CLS / PC BIOS keyboard handling.

Fix INT10 AH=0Bh CGA-compatible border/palette and decode USB CDC ANSI
cursor/F-key escape sequences into PC BIOS INT16 key words.
Commands: selftest | probe | apply | verify | restore | recover
"""
from __future__ import annotations
import argparse, hashlib, json, os, shutil, subprocess, sys, tempfile
from pathlib import Path
import bb_dos622_atbios_v1 as chain

ROOT=Path(__file__).resolve().parent
TAG='BB_DOS622_VGA0B_KEYS_V1'
STATE='.bb_dos622_vga0b_keys_v1_state'
VGA='src/bb_vga.c'
LIVE='src/bb_live.c'
PREV_VGA='.bb_dos622_screen_clear_v1_state/manifest.json'
PREV_LIVE='.bb_dos622_lcd_text_v2_state/manifest.json'
sha=chain.sha
atomic=chain.atomic_bytes

def nl(raw,txt):
    return txt.replace('\n','\r\n').encode('ascii') if b'\r\n' in raw else txt.encode('ascii')

VGA_HANDLER='''    /* BB_DOS622_VGA0B_KEYS_V1: IBM CGA-compatible INT10 AH=0Bh.
       BH=00 changes overscan/border (not text memory), BH=01 chooses
       CGA palette; no AX/FLAGS or guest framebuffer modification. */
    case 0x0B:
        if(mode != 3u && mode != 0x13u) return false;
        if(((*bx >> 8) & 255u)==0u) border=(uint8_t)(*bx & 15u);
        else if(((*bx >> 8) & 255u)==1u) cga_palette_select=(uint8_t)(*bx & 1u);
        else return false;
#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE
        { static unsigned bb622_vga0b_calls;
          extern bool bb_sd_dos622_active(void);
          if(bb_sd_dos622_active() && bb622_vga0b_calls++ < 8u) {
              printf("[bb622-vga0b] INT10 AH=0B BH=%02X BL=%02X accepted; AX=%04X preserved\\n",
                  (unsigned)(*bx>>8), (unsigned)(*bx&255u), (unsigned)*ax);
              fflush(stdout);
          }
        }
#endif
        return true;
'''

# This code sits after bb_v23_enqueue_ascii(), so it reuses the existing
# authentic PC BIOS BDA queue and normal ASCII conversion.
KEY_HELPER='''/* BB_DOS622_VGA0B_KEYS_V1: translate CDC terminal keys to BIOS INT16 scan codes.
 * ESC O P/R (F1/F3), CSI cursor keys and numeric tilde codes are consumed
 * as one PC BIOS key.  Never enqueue the ESC, '[', digits and '~' separately.
 * Standalone Escape is delivered after a short timeout.
 * No changes to DOS2 or to the guest CPU/JIT.
 */
static uint8_t bb622_vt_state;      /* 0 idle, 1 ESC, 2 CSI, 3 SS3 */
static uint16_t bb622_vt_number;
static uint64_t bb622_vt_last_us;
static uint16_t bb622_vt_logged;
static void bb622_vt_reset(void) {
    bb622_vt_state=0u; bb622_vt_number=0u; bb622_vt_last_us=0u;
    bb622_vt_logged=0u;
}
static void bb622_vt_scancode(uint8_t *m,uint8_t scan) {
    uint16_t h,t,next;
    if(!scan)return;
    bb_v22_queue_init(m);
    h=bb_v22_word(m,0x41au); t=bb_v22_word(m,0x41cu);
    next=(uint16_t)(t+2u); if(next>=0x3eu)next=0x1eu;
    if(next==h){++bb_v23_key_drop;return;}
    bb_v22_write_word(m,0x400u+t,(uint16_t)((uint16_t)scan<<8));
    bb_v22_write_word(m,0x41cu,next);
    ++bb_v23_keys;
    if(bb622_vt_logged++<32u) {
        printf("[bb622-vtkey] scan=%02X AX=%04X queued=%lu\\n",
            (unsigned)scan,(unsigned)(scan<<8),(unsigned long)bb_v23_keys);
        fflush(stdout);
    }
}
static uint8_t bb622_vt_cursor(unsigned c) {
    switch(c) {
    case 'A':return 0x48u; /* Up */
    case 'B':return 0x50u; /* Down */
    case 'C':return 0x4Du; /* Right */
    case 'D':return 0x4Bu; /* Left */
    case 'H':return 0x47u; /* Home */
    case 'F':return 0x4Fu; /* End */
    default:return 0u;
    }
}
static uint8_t bb622_vt_function(unsigned c) {
    switch(c) {
    case 'P':return 0x3Bu; /* F1 */
    case 'Q':return 0x3Cu; /* F2 */
    case 'R':return 0x3Du; /* F3 */
    case 'S':return 0x3Eu; /* F4 */
    default:return 0u;
    }
}
static uint8_t bb622_vt_tilde(unsigned n) {
    switch(n) {
    case 1u:case 7u:return 0x47u;  /* Home */
    case 2u:return 0x52u;          /* Insert */
    case 3u:return 0x53u;          /* Delete */
    case 4u:case 8u:return 0x4Fu;  /* End */
    case 5u:return 0x49u;          /* Page Up */
    case 6u:return 0x51u;          /* Page Down */
    case 11u:return 0x3Bu;case 12u:return 0x3Cu;
    case 13u:return 0x3Du;case 14u:return 0x3Eu;
    case 15u:return 0x3Fu;case 17u:return 0x40u;
    case 18u:return 0x41u;case 19u:return 0x42u;
    case 20u:return 0x43u;case 21u:return 0x44u;
    case 23u:return 0x85u;case 24u:return 0x86u;
    default:return 0u;
    }
}
static void bb622_vt_expire(uint8_t *m,uint64_t now) {
    if(bb622_vt_state && now-bb622_vt_last_us > 120000ull) {
        if(bb622_vt_state==1u) bb_v23_enqueue_ascii(m,27u);
        bb622_vt_state=0u;
        bb622_vt_number=0u;
    }
}
static void bb622_vt_feed(uint8_t *m,unsigned c,uint64_t now) {
    uint8_t key=0u;
    bb622_vt_expire(m,now);
    if(c==27u) {
        /* An ESC starts an ANSI sequence; a second ESC first commits the
           prior standalone key instead of injecting terminal syntax. */
        if(bb622_vt_state==1u)bb_v23_enqueue_ascii(m,27u);
        bb622_vt_state=1u; bb622_vt_number=0u;bb622_vt_last_us=now;
        return;
    }
    if(bb622_vt_state==0u){bb_v23_enqueue_ascii(m,c);return;}
    bb622_vt_last_us=now;
    if(bb622_vt_state==1u) {
        if(c=='['){bb622_vt_state=2u;bb622_vt_number=0u;return;}
        if(c=='O'){bb622_vt_state=3u;return;}
        bb622_vt_state=0u;
        /* An unrecognized ESC prefix is a genuine Escape key followed
           by its literal character. */
        bb_v23_enqueue_ascii(m,27u);
        bb_v23_enqueue_ascii(m,c);
        return;
    }
    if(bb622_vt_state==3u) {
        key=bb622_vt_function(c);
        if(!key)key=bb622_vt_cursor(c);
        bb622_vt_state=0u;
        bb622_vt_scancode(m,key);
        return;
    }
    /* CSI: tolerate numeric private/modifier parameters but don't type
       terminal control bytes into the DOS shell. */
    if(c>='0' && c<='9') {
        if(bb622_vt_number<1000u)bb622_vt_number=(uint16_t)(bb622_vt_number*10u+c-'0');
        return;
    }
    if(c==';')return; /* ignore modifier parameters; use base scan code */
    if(c=='~')key=bb622_vt_tilde(bb622_vt_number);
    else key=bb622_vt_cursor(c);
    bb622_vt_state=0u;
    bb622_vt_number=0u;
    bb622_vt_scancode(m,key);
}
'''

def vga_fix(raw:bytes)->bytes:
    if TAG.encode() in raw:raise ValueError('VGA0B layer already installed')
    if b'BB_DOS622_SCREEN_CLEAR_V1' not in raw or b'bool bb_vga_int10(' not in raw:
        raise ValueError('Screen-clear compatibility layer absent from VGA source')
    anchor=b'    case 0x0C:\n'
    if b'\r\n' in raw: anchor=b'    case 0x0C:\r\n'
    if raw.count(anchor)!=1:raise ValueError('VGA INT10 AH=0C dispatch anchor ambiguous')
    out=raw.replace(anchor,nl(raw,VGA_HANDLER)+anchor,1)
    variable=b'static uint8_t mode, page, cols;'
    if out.count(variable)!=1:raise ValueError('VGA global variables altered')
    out=out.replace(variable,variable+nl(raw,'\nstatic uint8_t cga_palette_select;'),1)
    init=b'mem=memory; mode=3;page=0;cols=80;pel_mask=255;'
    if out.count(init)!=1:raise ValueError('VGA initialization anchor missing')
    out=out.replace(init,init+b'cga_palette_select=0u;',1)
    if out.count(TAG.encode())!=1:raise ValueError('Incorrect VGA marker count')
    return out

def live_fix(raw:bytes)->bytes:
    if TAG.encode() in raw:raise ValueError('Keyboard layer already installed')
    if b'BB_DOS622_KEYBA2_V3' not in raw:
        raise ValueError('DOS6 keyboard A2h compatibility layer absent')
    anchor=b'static void bb_v23_poll_input(void) {'
    if raw.count(anchor)!=1:raise ValueError('CDC input handler anchor missing')
    out=raw.replace(anchor,nl(raw,KEY_HELPER)+anchor,1)
    old=b'    if(c>=0)bb_v23_enqueue_ascii(R->cpu.memory,(unsigned)c);'
    if out.count(old)!=1:raise ValueError('Expected original ASCII-only CDC queue line missing')
    replacement=nl(raw,'''    if (bb_sd_dos622_active()) {
        if(c>=0)bb622_vt_feed(R->cpu.memory,(unsigned)c,bb_now_us());
        else bb622_vt_expire(R->cpu.memory,bb_now_us());
    } else if(c>=0)bb_v23_enqueue_ascii(R->cpu.memory,(unsigned)c);''')
    out=out.replace(old,replacement,1)
    reset=b'bb622_textio_reset();'
    if out.count(reset)!=1:raise ValueError('Cannot identify unique DOS622 textio reset')
    out=out.replace(reset,reset+b' bb622_vt_reset();',1)
    if out.count(TAG.encode())!=1:raise ValueError('Incorrect keyboard marker count')
    return out

def state(root):
    p=root/STATE/'manifest.json'
    if not p.is_file():raise ValueError(f'Missing installer state: {p}')
    o=json.loads(p.read_bytes())
    if o.get('tag')!=TAG or not isinstance(o.get('files'),list):raise ValueError('Invalid install state schema')
    return o

def prereq(root):
    specs=[(PREV_VGA,'BB_DOS622_SCREEN_CLEAR_V1',VGA),
           (PREV_LIVE,'BB_DOS622_LCD_TEXT_V2',LIVE)]
    for meta,tag,source in specs:
        m=root/meta
        if not m.is_file():raise ValueError(f'Missing earlier install metadata: {m}')
        o=json.loads(m.read_bytes())
        if o.get('tag')!=tag or not isinstance(o.get('files'),list):
            raise ValueError(f'Unexpected earlier install manifest: {meta}')
        items=[x for x in o['files'] if x.get('path')==source]
        if len(items)!=1 or not (root/source).is_file() or sha((root/source).read_bytes())!=items[0].get('installed'):
            raise ValueError(f'Source is not latest verified version in {meta}: {source}')
    h=root/'.bb_dos622_hdd_v2_state/manifest.json'
    if not h.is_file() or json.loads(h.read_bytes()).get('tag')!='BB_DOS622_HDD_V2':
        raise ValueError('HDD V2 layer must be installed first')

def cascade(root,before,after):
    originals=chain.active_metadata(root)
    updated=dict(originals)
    dig={sha(before[rel]):sha(after[rel]) for rel in before}
    for _ in range(8*len(originals)+8):
        changed=False
        for rel,raw in originals.items():
            new,_=chain._update_metadata(raw,dig,rel)
            if new!=updated[rel]:updated[rel]=new;changed=True
            if new!=raw:dig[sha(raw)]=sha(new)
        if not changed:break
    else:raise ValueError('Manifest dependency SHA changes did not converge')
    if updated[PREV_LIVE]==originals[PREV_LIVE] or updated[PREV_VGA]==originals[PREV_VGA]:
        raise ValueError('Both prior source manifests must advance')
    return {k:(originals[k],v) for k,v in updated.items() if v!=originals[k]}

def prepare(root=ROOT,verbose=True):
    if (root/STATE).exists():raise ValueError('Already installed; verify or restore')
    prereq(root)
    before={VGA:(root/VGA).read_bytes(),LIVE:(root/LIVE).read_bytes()}
    after={VGA:vga_fix(before[VGA]),LIVE:live_fix(before[LIVE])}
    changes={p:(before[p],after[p]) for p in (VGA,LIVE)}
    changes.update(cascade(root,before,after))
    if verbose:
        for p in before:print(f'{p}: {len(before[p])}->{len(after[p])} SHA {sha(before[p])[:12]}->{sha(after[p])[:12]}')
        print(f'Parent metadata updates: {len(changes)-2}; PROBE PASS; files untouched')
    return changes

def verify(root=ROOT):
    m=state(root)
    for ent in m['files']:
        p=root/ent['path'];bk=root/STATE/ent['backup']
        if not p.is_file() or sha(p.read_bytes())!=ent['installed']:
            raise ValueError(f'Installed file changed unexpectedly: {p}')
        if not bk.is_file() or sha(bk.read_bytes())!=ent['original']:
            raise ValueError(f'Original backup altered: {bk}')
    print(f'VERIFY PASS: {len(m["files"])} source/metadata files, original backups intact')

def apply(root=ROOT):
    changes=prepare(root)
    d=root/STATE;d.mkdir()
    m={'tag':TAG,'files':[]}
    try:
        for i,(rel,(old,new)) in enumerate(changes.items()):
            bn=f'backup_{i:03d}.bin'
            atomic(d/bn,old)
            m['files'].append({'path':rel,'backup':bn,'original':sha(old),'installed':sha(new)})
        atomic(d/'manifest.json',(json.dumps(m,indent=2)+'\n').encode())
        for rel,(_,new) in changes.items():atomic(root/rel,new)
        verify(root)
    except BaseException:
        for rel,(old,_) in changes.items():atomic(root/rel,old)
        shutil.rmtree(d,ignore_errors=True)
        raise
    print('APPLIED: VGA INT10/AH=0B and DOS6 CDC VT key decoder; DOS2 unchanged')

def restore(root=ROOT,recover=False):
    if not recover:verify(root)
    m=state(root)
    for ent in m['files']:
        bk=root/STATE/ent['backup'];p=root/ent['path']
        if not bk.is_file() or sha(bk.read_bytes())!=ent['original']:
            raise ValueError(f'Missing/corrupt backup: {bk}')
        if recover and p.is_file() and sha(p.read_bytes()) not in {ent['original'],ent['installed']}:
            raise ValueError(f'Unknown intervening edit; recovery refused: {p}')
    for ent in m['files']:atomic(root/ent['path'],(root/STATE/ent['backup']).read_bytes())
    shutil.rmtree(root/STATE)
    print('RESTORE PASS: exact original source/manifest bytes')

def selftest():
    import textwrap
    for line in ('\n','\r\n'):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for path in (VGA,LIVE): (root/path).parent.mkdir(parents=True,exist_ok=True)
            vga='''static uint8_t mode, page, cols;
static uint8_t border;
static void bb_vga_init(uint8_t *memory){mem=memory; mode=3;page=0;cols=80;pel_mask=255;}
/* BB_DOS622_SCREEN_CLEAR_V1 */
bool bb_vga_int10(void){switch(ah){
    case 0x0C:
        return true;
}}
'''
            live='''/* BB_DOS622_KEYBA2_V3 */
static void bb_v23_enqueue_ascii(uint8_t *m,unsigned c){}
static void bb_v23_poll_input(void) {
    if(c>=0)bb_v23_enqueue_ascii(R->cpu.memory,(unsigned)c);
}
void boot(void) {bb622_textio_reset();}
'''
            (root/VGA).write_bytes(vga.replace('\n',line).encode())
            (root/LIVE).write_bytes(live.replace('\n',line).encode())
            for rel,tag,source in ((PREV_VGA,'BB_DOS622_SCREEN_CLEAR_V1',VGA),(PREV_LIVE,'BB_DOS622_LCD_TEXT_V2',LIVE)):
                o={'tag':tag,'files':[{'path':source,'backup':'original.bin','original':'0'*64,'installed':sha((root/source).read_bytes())}]}
                p=root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(o))
            (root/'.bb_dos622_hdd_v2_state').mkdir()
            (root/'.bb_dos622_hdd_v2_state/manifest.json').write_text(json.dumps({'tag':'BB_DOS622_HDD_V2'}))
            # The cascading updater expects all parent manifests and the first
            # KEYB92 layer; fixtures keep their installed digests coherent.
            all_meta=['.bb_dos622_ipl_v1_state/manifest.json','.bb_dos622_boot_diag_v1_state/repair.json',
            '.bb_dos622_heap_rescue_v1_state/manifest.json','.bb_dos622_vga12_34_v1_state/manifest.json',
            '.bb_dos622_vga12_30_v1_state/manifest.json','.bb_dos622_keyb92_v1_state/manifest.json']
            for rel in all_meta:
                p=root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps({'tag':'FIXTURE','files':[]}))
            changed=prepare(root,verbose=False)
            assert VGA in changed and LIVE in changed and PREV_VGA in changed and PREV_LIVE in changed
            assert b'case 0x0B:' in changed[VGA][1]
            assert b'bb622_vt_feed(' in changed[LIVE][1]
            apply(root); verify(root);restore(root)
            assert (root/VGA).read_bytes()==vga.replace('\n',line).encode()
            assert (root/LIVE).read_bytes()==live.replace('\n',line).encode()
            print('SELFTEST '+('CRLF' if line=='\r\n' else 'LF')+': byte-exact source/metadata rollback PASS')
    # Standalone compiled C11 harness exercises the exact parse helpers used
    # by the patch, including BIOS scan codes and the bare-ESC timeout.
    cc=shutil.which('cc') or shutil.which('gcc') or shutil.which('clang')
    if cc:
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);vga=p/'keyboard.c';binary=p/'keyboard'
            # Create a minimal host contract supplying a real ring buffer.
            stub='''#include <stdint.h>\n#include <stdbool.h>\n#include <stdio.h>\n#include <assert.h>\n#include <string.h>\nstatic uint32_t bb_v23_keys,bb_v23_key_drop;\nstatic uint16_t bb_v22_word(const uint8_t*m,unsigned o){return (uint16_t)(m[o]|(m[o+1]<<8));}\nstatic void bb_v22_write_word(uint8_t*m,unsigned o,uint16_t n){m[o]=n&255;m[o+1]=n>>8;}\nstatic void bb_v22_queue_init(uint8_t*m){if(!bb_v22_word(m,0x41a))bb_v22_write_word(m,0x41a,0x1e);if(!bb_v22_word(m,0x41c))bb_v22_write_word(m,0x41c,0x1e);}\nstatic void bb_v23_enqueue_ascii(uint8_t*m,unsigned c){bb_v22_queue_init(m);uint16_t t=bb_v22_word(m,0x41c);bb_v22_write_word(m,0x400+t,(uint16_t)c);bb_v22_write_word(m,0x41c,t+2);}\n'''
            stub+=KEY_HELPER
            stub+='''\nstatic uint8_t m[0x500];\nstatic uint16_t pop(void){unsigned h=bb_v22_word(m,0x41a);uint16_t x=bb_v22_word(m,0x400+h);unsigned t=h+2;bb_v22_write_word(m,0x41a,t>=0x3e?0x1e:t);return x;}\nstatic void sequence(const char *s,uint64_t us){while(*s)bb622_vt_feed(m,(uint8_t)*s++,us+=500u);}\nint main(void){\n bb622_vt_reset();sequence("\\x1bOP",200u);assert(pop()==0x3b00);\n sequence("\\x1bOR",10000u);assert(pop()==0x3d00);\n sequence("\\x1b[A",20000u);assert(pop()==0x4800);\n sequence("\\x1b[24~",30000u);assert(pop()==0x8600);\n sequence("\\x1b[3~",40000u);assert(pop()==0x5300);\n sequence("\\x1b",60000u);bb622_vt_expire(m,190001u);assert(pop()==0x001b);\n sequence("abc",200000u);assert(pop()=='a');assert(pop()=='b');assert(pop()=='c');\n puts("C11 keyboard sequences PASS");return 0;}\n'''
            vga.write_text(stub)
            q=subprocess.run([cc,'-std=c11','-Wall','-Wextra','-Werror','-Wno-unused-function',str(vga),'-o',str(binary)],capture_output=True,text=True)
            if q.returncode:raise RuntimeError('C11 test compile failure:\n'+q.stdout+'\n'+q.stderr)
            z=subprocess.run([str(binary)],capture_output=True,text=True)
            if z.returncode:raise RuntimeError('C11 keyboard contract failure:\n'+z.stdout+'\n'+z.stderr)
            print(z.stdout.strip())
    else:print('C11 keyboard test skipped (no compiler)')
    if cc:
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);source=p/'bios.c';binary=p/'bios'
            vga_case=VGA_HANDLER
            stub='''#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <assert.h>
static uint8_t mode=3u,border=0u,cga_palette_select=0u;
static bool bios(uint16_t *ax,uint16_t *bx,uint16_t *cx,uint16_t *dx,uint16_t *flags) {
 (void)cx;(void)dx;(void)flags;
 uint8_t ah=(uint8_t)(*ax>>8);
 switch(ah) {
'''
            stub+=vga_case
            stub+=''' default:return false;
 }
}
int main(void){
 uint16_t ax=0x0b40,bx=0,cx=0x037f,dx=0x184f,flags=0x0246;
 assert(bios(&ax,&bx,&cx,&dx,&flags));
 assert(ax==0x0b40&&bx==0&&cx==0x037f&&dx==0x184f&&flags==0x0246);
 assert(border==0);
 bx=0x000e;assert(bios(&ax,&bx,&cx,&dx,&flags));assert(border==14);
 bx=0x0101;assert(bios(&ax,&bx,&cx,&dx,&flags));assert(cga_palette_select==1);
 bx=0x0200;assert(!bios(&ax,&bx,&cx,&dx,&flags));
 mode=7;bx=0;assert(!bios(&ax,&bx,&cx,&dx,&flags));
 puts("C11 VGA 0Bh contract PASS");return 0;
}
'''
            source.write_text(stub)
            q=subprocess.run([cc,'-std=c11','-Wall','-Wextra','-Werror',str(source),'-o',str(binary)],capture_output=True,text=True)
            if q.returncode:raise RuntimeError('C11 VGA compile failure:\n'+q.stdout+'\n'+q.stderr)
            z=subprocess.run([str(binary)],capture_output=True,text=True)
            if z.returncode:raise RuntimeError('C11 VGA contract failure:\n'+z.stdout+'\n'+z.stderr)
            print(z.stdout.strip())
    print('SELFTEST PASS (Pico firmware and user hardware not tested)')

def main():
    pa=argparse.ArgumentParser(description=__doc__)
    pa.add_argument('action',choices=['selftest','probe','apply','verify','restore','recover'])
    args=pa.parse_args()
    try:
        {'selftest':selftest,'probe':prepare,'apply':apply,'verify':verify,
         'restore':restore,'recover':lambda:restore(recover=True)}[args.action]()
    except (OSError,ValueError,RuntimeError,AssertionError) as exc:
        print('ERROR:',exc);sys.exit(1)
if __name__=='__main__':main()
