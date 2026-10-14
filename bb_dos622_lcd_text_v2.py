#!/usr/bin/env python3
"""Reversible DOS 6.22 B800->physical LCD text mirror V2 (correct HDD gate). No git patches.
Requires installed bb_dos622_hdd_v1.py and bb_dos622_atbios_v1.py in repo root.
Commands: selftest | probe | apply | verify | restore | recover
"""
from pathlib import Path
import os,sys,json,re,argparse,hashlib,shutil,tempfile,subprocess
import bb_dos622_atbios_v1 as prior

ROOT=Path(__file__).resolve().parent
STATE='.bb_dos622_lcd_text_v2_state'
TAG='BB_DOS622_LCD_TEXT_V2'
LIVE='src/bb_live.c'
LCD='src/bb_lcd_console.c'
sha=prior.sha
atomic=prior.atomic_bytes

HDD_SOURCES=('sd_boot/bb_sd_boot.c','src/bb_dos622_bios.inc')
ATBIOS_STATE='.bb_dos622_atbios_v1_state/manifest.json'
HDD_STATE='.bb_dos622_hdd_v1_state/manifest.json'

def validated_hdd_state(root):
    path=root/HDD_STATE
    if not path.is_file():raise ValueError(f'Missing HDD installer state: {path}')
    obj=json.loads(path.read_bytes())
    if obj.get('tag')!='BB_DOS622_HDD_V1' or not isinstance(obj.get('files'),list):
        raise ValueError('Unexpected HDD installer manifest schema or tag')
    paths={}
    for ent in obj['files']:
        rel=ent.get('path');inst=ent.get('installed')
        if not isinstance(rel,str) or not re.fullmatch('[a-fA-F0-9]{64}',str(inst)):
            raise ValueError('Invalid HDD manifest path/digest')
        paths[rel]=ent
        p=root/rel
        if not p.is_file() or sha(p.read_bytes())!=inst.lower():
            raise ValueError(f'HDD installed checksum mismatch: {p}; do not stack another installer')
        backup=ent.get('backup');original=ent.get('original')
        if backup is not None:
            bp=root/'.bb_dos622_hdd_v1_state'/backup
            if not bp.is_file() or sha(bp.read_bytes())!=original:
                raise ValueError(f'HDD backup mismatch: {bp}')
        elif original is not None:
            raise ValueError(f'Invalid HDD new-file record: {rel}')
    for rel in HDD_SOURCES:
        p=root/rel
        if rel not in paths or b'BB_DOS622_HDD_V1' not in p.read_bytes():
            raise ValueError(f'Installed HDD signature missing in {rel}')
    return obj

def validated_atbios_live(root, raw):
    path=root/ATBIOS_STATE
    if not path.is_file():raise ValueError('Missing installed ATBIOS state')
    obj=json.loads(path.read_bytes())
    if obj.get('tag')!='BB_DOS622_ATBIOS_V1':
        raise ValueError('Unexpected ATBIOS state tag')
    candidates=[f for f in obj.get('files',[]) if f.get('path')==LIVE]
    if len(candidates)!=1 or sha(raw)!=candidates[0]['installed']:
        raise ValueError('Live source differs from installed ATBIOS source; unsafe to apply')
    return obj

# The LCD hardware driver already owns 80x25 character cells and an 8-row flush.
# No guest buffers or separate framebuffers are allocated.
NEW_FUNCTION=r'''/* BB_DOS622_LCD_TEXT_V2: LCD text-mode mirror from the real guest B800h RAM.
 * This is an LCD observer only. The DOS guest, text BIOS, and DOS2 remain unchanged.
 * Mirror runs at most 12.5 Hz, has no allocations, and flushes only changed rows.
 * It operates on the existing 80x25/6x8 font and does not reset the VGA device. */
void bb622_lcd_text_mirror(const uint8_t *guest)
{
    static uint32_t last_ms;
    static uint8_t sampled;
    static uint8_t first_change_logged;
    if (!active || !guest) return;
    const uint32_t now_ms=to_ms_since_boot(get_absolute_time());
    if (sampled && (uint32_t)(now_ms-last_ms) < 80u) return;
    sampled=1u;
    last_ms=now_ms;
    const uint8_t *const text=guest+0xB8000u;
    unsigned changed_rows=0;
    for (unsigned y=0; y<ROWS; ++y) {
        unsigned dirty_row=0;
        for (unsigned x=0; x<COLS; ++x) {
            const uint8_t raw=text[(y*COLS+x)*2u];
            const uint8_t ch=(raw>=32u && raw<=126u) ? raw : (uint8_t)' ';
            if (cells[y][x] != ch) { cells[y][x]=ch; dirty_row=1u; }
        }
        if (dirty_row) { dirty[y]=1u; ++changed_rows; }
    }
    if (changed_rows) {
        bb_lcd_console_flush();
        if (!first_change_logged) {
            first_change_logged=1u;
            printf("[bb622-lcdtext] B800 text shown on LCD; updated-rows=%u\n",changed_rows);
            fflush(stdout);
        }
    }
}
'''
HOOK=r'''    /* BB_DOS622_LCD_TEXT_V2: refresh physical LCD during real DOS6 text mode.
       The serial B800 mirror is only a diagnostic; the actual LCD needs this path. */
#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE && defined(BLITZBUS_LCD_CONSOLE) && BLITZBUS_LCD_CONSOLE
    if (R && rt==R && bb_sd_dos622_active() && !bb_vga_active()) {
        extern void bb622_lcd_text_mirror(const uint8_t *guest);
        bb622_lcd_text_mirror(rt->cpu.memory);
    }
#endif
'''

def nl_like(raw, s):
    if raw.count(b'\r\n')>raw.count(b'\n')//2:
        return s.replace('\n','\r\n').encode('utf-8')
    return s.encode('utf-8')

def transform_live(raw):
    if TAG.encode() in raw:raise ValueError('Already installed in bb_live.c')
    # HDD V1 never edits bb_live.c. Its marker belongs to
    # sd_boot/bb_sd_boot.c and src/bb_dos622_bios.inc, not this file.
    markers=(b'BB_DOS622_ATBIOS_V1',b'BB_DOS622_P61_REFRESH_V1')
    for m in markers:
        if m not in raw:raise ValueError(f'Expected live DOS6 layer missing: {m.decode()}')
    sig=b'B86_HOT int bb_live_try(MdRuntime *rt, uint64_t left)'
    if raw.count(sig)!=1:raise ValueError('Cannot uniquely identify bb_live_try')
    p=raw.index(sig)
    anchor=b'bb_v23_poll_input();'
    x=raw.find(anchor,p,p+2500)
    if x<0:raise ValueError('Cannot locate early common guest dispatch poll')
    if raw.find(anchor,x+len(anchor),p+2500)>=0:raise ValueError('Multiple early poll anchors')
    stop=x+len(anchor)
    return raw[:stop] + nl_like(raw,'\n'+HOOK) + raw[stop:]

def transform_lcd(raw):
    if TAG.encode() in raw:raise ValueError('Already installed in bb_lcd_console.c')
    if raw.count(b'void bb_lcd_console_flush(void)')!=1:raise ValueError('Unexpected LCD console flush layout')
    anchor=b'/* v27: MicroRender\'s DMA presenter on core 1.'
    if raw.count(anchor)!=1:raise ValueError('Cannot identify LCD text/graphics boundary')
    p=raw.index(anchor)
    return raw[:p] + nl_like(raw,NEW_FUNCTION+'\n') + raw[p:]

def cascade(root, before,after):
    meta=prior.active_metadata(root)
    current={r:d for r,d in meta.items()}
    changes={sha(before[r]):sha(after[r]) for r in before}
    count={}
    for n in range(len(meta)*8+8):
        progress=False
        for rel,base in meta.items():
            new,hits=prior._update_metadata(base,changes,rel)
            if new != current[rel]:
                current[rel]=new;count[rel]=hits;progress=True
            if new != base:changes[sha(base)]=sha(new)
        if not progress:break
    else:raise ValueError('Manifest checksum cascade did not converge')
    live_digest=sha(before[LIVE])
    if not any(live_digest.encode() in base.lower() and rel in count for rel,base in meta.items()):
        raise ValueError('No parent manifest tracks the old bb_live.c SHA; unsafe')
    return {r:(meta[r],current[r]) for r in meta if current[r]!=meta[r]}

def prepare(root=ROOT,report=True):
    if (root/STATE).exists():raise ValueError('Installer state already exists; use verify or restore')
    validated_hdd_state(root)
    before={};after={}
    validated_atbios_live(root,(root/LIVE).read_bytes())
    for r,fn in ((LIVE,transform_live),(LCD,transform_lcd)):
        p=root/r
        if not p.is_file():raise ValueError(f'Missing {p}')
        old=p.read_bytes();new=fn(old)
        before[r]=old;after[r]=new
    updates=cascade(root,before,after)
    changes={r:(before[r],after[r]) for r in (LIVE,LCD)}
    changes.update(updates)
    if report:
        for rel in (LIVE,LCD):
            print(f'{rel}: {len(before[rel])}->{len(after[rel])}, sha {sha(before[rel])[:12]}->{sha(after[rel])[:12]}')
        print(f'Parent metadata SHA cascade: {len(updates)} files')
        print('PROBE PASS: no repository files modified')
    return changes

def _state(root):
    p=root/STATE/'manifest.json'
    if not p.is_file():raise ValueError(f'Missing install state: {p}')
    j=json.loads(p.read_bytes())
    if j.get('tag')!=TAG:raise ValueError('State tag mismatch')
    return j

def verify(root=ROOT):
    j=_state(root)
    for ent in j['files']:
        p=root/ent['path'];back=root/STATE/ent['backup']
        if not p.is_file() or sha(p.read_bytes())!=ent['installed']:
            raise ValueError(f'Installed checksum mismatch: {p}')
        if not back.is_file() or sha(back.read_bytes())!=ent['original']:
            raise ValueError(f'Original backup mismatch: {back}')
    print(f'VERIFY PASS: {len(j["files"])} source/metadata files, byte-exact backups')

def apply(root=ROOT):
    changes=prepare(root)
    state=root/STATE
    state.mkdir()
    manifest={'tag':TAG,'files':[]}
    try:
        for i,(rel,(old,new)) in enumerate(changes.items()):
            backup=f'backup_{i:03d}.bin';atomic(state/backup,old)
            manifest['files'].append({'path':rel,'backup':backup,'original':sha(old),'installed':sha(new)})
        atomic(state/'manifest.json',(json.dumps(manifest,indent=2)+'\n').encode())
        for rel,(old,new) in changes.items():atomic(root/rel,new)
        verify(root)
    except BaseException:
        for rel,(old,new) in changes.items():atomic(root/rel,old)
        shutil.rmtree(state,ignore_errors=True)
        raise
    print('APPLIED: DOS622 physical B800 LCD mirror; DOS2 and guest BIOS untouched')

def restore(root=ROOT,recover=False):
    if not recover:verify(root)
    j=_state(root)
    for ent in j['files']:
        p=root/ent['path'];bk=root/STATE/ent['backup']
        if not bk.is_file() or sha(bk.read_bytes())!=ent['original']:
            raise ValueError(f'Original backup damaged: {bk}')
        if recover and p.is_file() and sha(p.read_bytes()) not in (ent['original'],ent['installed']):
            raise ValueError(f'Unknown source modification: {p}; refusing recover')
    for ent in j['files']:
        atomic(root/ent['path'],(root/STATE/ent['backup']).read_bytes())
    shutil.rmtree(root/STATE)
    print('RESTORED: original source/metadata bytes, no git patches')

def selftest():
    for ending in ('LF','CRLF'):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root/'src').mkdir()
            (root/'sd_boot').mkdir()
            (root/'.bb_dos622_hdd_v1_state').mkdir()
            live=b'BB_DOS622_ATBIOS_V1 BB_DOS622_P61_REFRESH_V1\nB86_HOT int bb_live_try(MdRuntime *rt, uint64_t left)\n{\n    bb_v23_poll_input();\n    return 0;\n}\n'
            lcd=b'void bb_lcd_console_flush(void){return;}\n/* v27: MicroRender\'s DMA presenter on core 1. */\n'
            if ending=='CRLF':live=live.replace(b'\n',b'\r\n');lcd=lcd.replace(b'\n',b'\r\n')
            (root/LIVE).write_bytes(live);(root/LCD).write_bytes(lcd)
            for rel in HDD_SOURCES:
                p=root/rel;p.parent.mkdir(parents=True,exist_ok=True)
                p.write_bytes(b'/* BB_DOS622_HDD_V1 installed */\n')
            hdd_entries=[{'path':rel,'backup':None,'original':None,'installed':sha((root/rel).read_bytes())}
                         for rel in HDD_SOURCES]
            (root/HDD_STATE).write_text(json.dumps({'tag':'BB_DOS622_HDD_V1','files':hdd_entries}))
            ap=root/ATBIOS_STATE;ap.parent.mkdir(exist_ok=True)
            ap.write_text(json.dumps({'tag':'BB_DOS622_ATBIOS_V1','files':[{'path':LIVE,'installed':sha(live)}]}))
            manifests={
              '.bb_dos622_ipl_v1_state/manifest.json':{'files':{LIVE:{'installed':sha(live),'old':'a'*64}}},
              '.bb_dos622_boot_diag_v1_state/repair.json':{'files':{LIVE:{'new':sha(live),'old':'a'*64}}},
              '.bb_dos622_heap_rescue_v1_state/manifest.json':{'files':{LIVE:{'installed':sha(live)}}},
              '.bb_dos622_keyb92_v1_state/manifest.json':{'files':{LIVE:{'after':sha(live)}}},
              '.bb_dos622_vga12_34_v1_state/manifest.json':{'files':{}},
              '.bb_dos622_vga12_30_v1_state/manifest.json':{'files':{}},
            }
            for rel,obj in manifests.items():
                p=root/rel;p.parent.mkdir(exist_ok=True,parents=True);p.write_text(json.dumps(obj))
            before={p:p.read_bytes() for p in [root/LIVE,root/LCD,*[root/x for x in manifests]]}
            prepare(root,False);apply(root);verify(root);restore(root)
            for p,b in before.items():assert p.read_bytes()==b, p
            print(f'SELFTEST {ending}: PASS real HDD signature locations, SHA cascade, exact rollback')
    with tempfile.TemporaryDirectory() as td:
        root=Path(td);(root/'src').mkdir();(root/'sd_boot').mkdir()
        (root/'.bb_dos622_hdd_v1_state').mkdir()
        for rel in HDD_SOURCES:(root/rel).write_text('/* no actual HDD implementation */')
        (root/HDD_STATE).write_text(json.dumps({'tag':'BB_DOS622_HDD_V1','files':[
            {'path':rel,'backup':None,'original':None,'installed':sha((root/rel).read_bytes())}
            for rel in HDD_SOURCES]}))
        try:validated_hdd_state(root)
        except ValueError as e:assert 'signature missing' in str(e)
        else:raise AssertionError('HDD marker check accepted a missing real layer')
        print('SELFTEST misplaced-HDD-marker refusal: PASS')
    # Tiny compiled C11 behavior test of the actual mirror function source.
    cc=shutil.which('cc') or shutil.which('gcc')
    if cc:
        with tempfile.TemporaryDirectory() as td:
            src=Path(td)/'t.c';exe=Path(td)/('test.exe' if os.name=='nt' else 'test')
            program='''#include <stdint.h>\n#include <stdio.h>\n#include <string.h>\n#include <assert.h>\n#define ROWS 25u\n#define COLS 80u\nstatic uint8_t cells[ROWS][COLS];\nstatic uint8_t dirty[ROWS];\nstatic int active=1;\nstatic uint32_t ticks;\nstatic unsigned flushes;\nstatic uint32_t to_ms_since_boot(uint32_t t){return t;}\nstatic uint32_t get_absolute_time(void){return ticks;}\nstatic void bb_lcd_console_flush(void){++flushes;memset(dirty,0,sizeof dirty);}\n''' + NEW_FUNCTION + '''\nint main(void){static uint8_t guest[0xB8000+4000]; memset(cells,' ',sizeof cells); memset(guest+0xB8000,' ',4000); for(unsigned i=1;i<4000;i+=2)guest[0xB8000+i]=7; guest[0xB8000]='M';bb622_lcd_text_mirror(guest); assert(flushes==1 && cells[0][0]=='M'); guest[0xB8000+2]='S';ticks=20;bb622_lcd_text_mirror(guest);assert(flushes==1);ticks=80;bb622_lcd_text_mirror(guest);assert(flushes==2&&cells[0][1]=='S');printf("C11 LCD mirror PASS\\n");return 0;}\n'''
            src.write_text(program)
            cp=subprocess.run([cc,'-std=c11','-O0',str(src),'-o',str(exe)],capture_output=True,text=True)
            if cp.returncode:raise ValueError('C11 compile failed: '+cp.stderr)
            rp=subprocess.run([str(exe)],capture_output=True,text=True)
            if rp.returncode:raise ValueError('C11 behavior failed: '+rp.stdout+rp.stderr)
            print(rp.stdout.strip())
    print('SELFTEST PASS: no files modified outside temp; Pico compile/hardware not tested')

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action',choices=['selftest','probe','apply','verify','restore','recover'])
    a=ap.parse_args()
    try:{'selftest':selftest,'probe':prepare,'apply':apply,'verify':verify,'restore':restore,'recover':lambda:restore(recover=True)}[a.action]()
    except (ValueError,OSError,AssertionError,KeyError,json.JSONDecodeError) as e:
        print('ERROR:',e,file=sys.stderr);sys.exit(1)
if __name__=='__main__':main()
