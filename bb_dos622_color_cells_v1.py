#!/usr/bin/env python3
"""Add exact B800 text/attribute/CP437 mirror and an independent color host runner.

No Git patch and no alteration of SD images, DOS2, or old runner.
Commands: selftest, probe, apply, verify, restore. Copy accompanying
bb_dos622_color_host.ps1 and bb_make_dos622_clean_console.py here first.
"""
from __future__ import annotations
import argparse, hashlib, json, re, shutil, subprocess, sys, tempfile
from pathlib import Path

import bb_dos622_atbios_v1 as chain
import bb_make_dos622_clean_console as clean

ROOT=Path(__file__).resolve().parent
TAG='BB_DOS622_COLOR_CELLS_V1'
STATE='.bb_dos622_color_cells_v1_state'
SRC='src/bb_dos622_textio.inc'
VGA='src/bb_vga.c'
EGA_STATE='.bb_dos622_ega_info_v1_state/manifest.json'
RUNNER='scripts/bb_live_run_dos622_color.ps1'
HOST='scripts/bb_dos622_color_host.ps1'
LOCAL_HOST=Path(__file__).with_name('bb_dos622_color_host.ps1')
ORIGINAL_RUNNER='scripts/bb_live_run.ps1'
SHA=lambda b:hashlib.sha256(b).hexdigest()
atomic=chain.atomic_bytes

SNIP='''        /* BB_DOS622_COLOR_CELLS_V1: preserve every VGA text cell,
         * not just printable ASCII. Character+attribute bytes are
         * serialized atomically per changed 80-column row; CP437 and
         * dark/bright/background color choices are decoded by the host.
         * Snapshot is in PSRAM, not near the RP2350 SRAM limit.
         */
        {
            const uint8_t *cells = p + row * 160u;
            uint32_t cell_h = 2166136261u;
            for (unsigned i = 0; i < 160u; ++i)
                cell_h = (cell_h ^ cells[i]) * 16777619u;
            if (cell_h != s->cell_hash[row]) {
                static const char hx[] = "0123456789ABCDEF";
                char wire[321];
                for (unsigned i = 0; i < 160u; ++i) {
                    wire[i * 2u] = hx[cells[i] >> 4u];
                    wire[i * 2u + 1u] = hx[cells[i] & 15u];
                }
                wire[320] = '\\0';
                s->cell_hash[row] = cell_h;
                printf("[bb622-cells] row=%02u |%s|\\n", row, wire);
            }
        }
'''


def convert_newline(raw:bytes,s:str)->bytes:
    if b'\r\n' in raw and b'\n' in raw.replace(b'\r\n',b''):
        raise ValueError('Mixed line endings in text mirror, source left unchanged')
    return s.replace('\n','\r\n').encode() if b'\r\n' in raw else s.encode()


def transform(raw:bytes)->bytes:
    if TAG.encode() in raw:raise ValueError('Color cell mirror already present')
    anchors=[b'    uint32_t row_hash[25];',b"        chars[end] = '\\0';",b'        if (h == s->row_hash[row]) continue;']
    for a in anchors:
        if raw.count(a)!=1:raise ValueError('Expected text mirror anchor absent or ambiguous: '+repr(a))
    if b'BB_DOS622_TEXTIO_PSRAM_V1' not in raw or b'bb622_textio_mirror' not in raw:
        raise ValueError('Expected DOS6 PSRAM textio implementation missing')
    a=anchors[0];raw=raw.replace(a,a+convert_newline(raw,'\n    uint32_t cell_hash[25];'),1)
    a=anchors[1];raw=raw.replace(a,a+convert_newline(raw,'\n'+SNIP),1)
    if raw.count(TAG.encode())!=1:raise AssertionError('Invalid mirror insertion')
    return raw


def make_runner(raw:bytes)->bytes:
    buf=clean.compile_runner(raw)
    utf=buf.decode('utf-8-sig');nl='\r\n' if '\r\n' in utf else '\n'
    normalized=utf.replace('\r\n','\n')
    a="(Join-Path $PSScriptRoot 'bb_dos622_screen_host.ps1')"
    b="(Join-Path $PSScriptRoot 'bb_dos622_color_host.ps1')"
    if normalized.count(a)!=1:raise ValueError('Generated helper anchor missing')
    normalized=normalized.replace(a,b)
    for before,after in [('Write-BbDos622ConsoleChunk','Write-BbDos622ColorConsoleChunk'),
                         ('Show-BbDos622HostFrame','Show-BbDos622ColorFrame')]:
        if normalized.count(before)!=1:raise ValueError(f'Runner {before} anchor missing')
        normalized=normalized.replace(before,after)
    # [Console]::ReadKey() has KeyChar=0 for arrows/function keys.
    # The existing DOS6 firmware VT decoder can translate these CSI/SS3 sequences.
    key_anchor='                    if($k.Key -eq [ConsoleKey]::Enter){'
    if normalized.count(key_anchor)!=1:raise ValueError('Host input key dispatch anchor missing')
    key_text='''                    $bb622SpecialKey = switch ([string]$k.Key) {
                        'F1' {'OP'} 'F2' {'OQ'} 'F3' {'OR'} 'F4' {'OS'}
                        'F5' {'[15~'} 'F6' {'[17~'} 'F7' {'[18~'} 'F8' {'[19~'}
                        'F9' {'[20~'} 'F10' {'[21~'} 'F11' {'[23~'} 'F12' {'[24~'}
                        'UpArrow' {'[A'} 'DownArrow' {'[B'}
                        'RightArrow' {'[C'} 'LeftArrow' {'[D'}
                        'Home' {'[H'} 'End' {'[F'}
                        'Insert' {'[2~'} 'Delete' {'[3~'}
                        'PageUp' {'[5~'} 'PageDown' {'[6~'}
                        default {''}
                    }
                    if ($bb622SpecialKey) {
                        $serial.Write(([string][char]27) + $bb622SpecialKey)
                    } elseif($k.Key -eq [ConsoleKey]::Enter){'''
    normalized=normalized.replace(key_anchor,key_text,1)
    normalized=normalized.replace('BB_DOS622_CLEAN_CONSOLE_HOST_V1','BB_DOS622_COLOR_CELLS_V1')
    return (b'\xef\xbb\xbf' if buf.startswith(b'\xef\xbb\xbf') else b'')+normalized.replace('\n',nl).encode('utf8')


def guarded_eqa(root:Path):
    p=root/EGA_STATE
    if not p.is_file():raise ValueError('Install and verify EGA_INFO_V1 first; missing '+str(p))
    o=json.loads(p.read_bytes())
    if o.get('tag')!='BB_DOS622_EGA_INFO_V1':raise ValueError('Wrong EGA_INFO_V1 installation metadata')
    ents=[e for e in o.get('files',[]) if e.get('path')==VGA]
    if len(ents)!=1 or not (root/VGA).is_file() or SHA((root/VGA).read_bytes())!=ents[0]['installed']:
        raise ValueError('EGA source differs from installed state; refusing to patch')


def cascade(root:Path, old:bytes,new:bytes):
    # Older installers have many active-SHA manifests; update only active
    # digests. Preserve every historical SHA and byte-exact rollback backup.
    originals=chain.active_metadata(root)
    after=dict(originals);changes={SHA(old):SHA(new)}
    for _ in range(len(originals)*8+8):
        any_change=False
        for rel,raw in originals.items():
            transformed,_=chain._update_metadata(raw,changes,rel)
            if transformed!=after[rel]:after[rel]=transformed;any_change=True
            if transformed!=raw and changes.get(SHA(raw))!=SHA(transformed):
                changes[SHA(raw)]=SHA(transformed);any_change=True
        if not any_change:break
    else:raise ValueError('SHA cascade failed to converge')
    return {rel:(raw,after[rel]) for rel,raw in originals.items() if raw!=after[rel]}


def changes(root=ROOT,verbose=True):
    if (root/STATE).exists():raise ValueError('Already installed; run verify')
    guarded_eqa(root)
    if not LOCAL_HOST.is_file():raise ValueError('Missing bundled helper '+str(LOCAL_HOST))
    for rel in (RUNNER,HOST):
        if (root/rel).exists():raise ValueError('Refusing to overwrite '+rel)
    r=root/SRC;b=root/ORIGINAL_RUNNER
    if not r.is_file() or not b.is_file():raise ValueError('Required source or original runner not found')
    old=r.read_bytes();new=transform(old)
    old_runner=b.read_bytes();gen=make_runner(old_runner)
    host=LOCAL_HOST.read_bytes()
    updates={SRC:(old,new),RUNNER:(None,gen),HOST:(None,host)}
    updates.update(cascade(root,old,new))
    if verbose:
        print(f'{SRC}: {len(old)}->{len(new)} bytes, SHA {SHA(old)[:12]}->{SHA(new)[:12]}')
        print(f'Host runner: {len(gen)} bytes; CP437 + VGA color renderer: {len(host)} bytes')
        print(f'Active metadata updates: {len(updates)-3} files')
        print('PROBE PASS: all source and old runners unchanged')
    return updates


def verify(root=ROOT):
    p=root/STATE/'manifest.json'
    if not p.is_file():raise ValueError('Missing installation state '+str(p))
    m=json.loads(p.read_bytes())
    if m.get('tag')!=TAG or not m.get('files'):raise ValueError('Bad installation state')
    for e in m['files']:
        rel=e['path']; path=root/rel;bn=e.get('backup')
        if not path.is_file() or SHA(path.read_bytes())!=e['installed']:
            raise ValueError('Changed/missing installed file '+str(path))
        if e['original'] is not None:
            if not bn:raise ValueError('Backup field missing for '+rel)
            back=root/STATE/bn
            if not back.is_file() or SHA(back.read_bytes())!=e['original']:
                raise ValueError('Damaged original backup '+str(back))
    print(f'VERIFY PASS: {len(m["files"])} source/host/metadata entries and backups')


def apply(root=ROOT):
    updates=changes(root)
    dest=root/STATE;dest.mkdir()
    m={'tag':TAG,'files':[]}
    touched=[]
    try:
        for n,(rel,(before,after)) in enumerate(updates.items()):
            back=None
            if before is not None:
                back=f'backup_{n:03d}.bin'; atomic(dest/back,before)
            m['files'].append({'path':rel,'backup':back,'original':SHA(before) if before is not None else None,'installed':SHA(after)})
        atomic(dest/'manifest.json',(json.dumps(m,indent=2)+'\n').encode())
        for rel,(before,after) in updates.items():
            path=root/rel;path.parent.mkdir(parents=True,exist_ok=True)
            atomic(path,after);touched.append(rel)
        verify(root)
    except BaseException:
        for rel in reversed(touched):
            original=updates[rel][0]; path=root/rel
            if original is None:path.unlink(missing_ok=True)
            else:atomic(path,original)
        shutil.rmtree(dest,ignore_errors=True)
        raise
    print('APPLIED: CP437+VGA color cell mirror and independent host color runner; old DOS2 runner and SD images untouched')


def restore(root=ROOT):
    verify(root)
    d=root/STATE;m=json.loads((d/'manifest.json').read_bytes())
    for e in m['files']:
        path=root/e['path']
        if e['original'] is None:path.unlink()
        else:atomic(path,(d/e['backup']).read_bytes())
    shutil.rmtree(d)
    print('RESTORED: exact previous sources/metadata; generated color runner and helper removed')


def test_c11(updated:bytes):
    cc=shutil.which('gcc') or shutil.which('clang') or shutil.which('cc')
    if not cc:print('C compiler absent: skipped C11 integration test');return
    program=r'''#include <stdint.h>
#include <stdio.h>
#include <stdbool.h>
#include <string.h>
#include <stdlib.h>
#define __uninitialized_psram(name)
typedef struct {uint8_t *memory;} MdX86;
typedef struct {MdX86 cpu;} MdRuntime;
static int bb_video_seen=0;
static bool bb_vga_active(void){return false;}
static bool bb_sd_dos622_active(void){return true;}
static uint64_t bb_now_us(void){static uint64_t t=1; t+=300000;return t;}
#include "test.inc"
int main(void){
  uint8_t *m=calloc(1,0x110000); if(!m)return 3;
  MdRuntime rt={{m}};
  for(unsigned i=0;i<2000;i++){m[0xB8000+2*i]=' '; m[0xB8000+2*i+1]=7;}
  m[0xB8000+2*160]=0xC4; m[0xB8000+2*160+1]=0x1E; /* CP437 horizontal rule in yellow/blue */
  bb622_textio_reset();bb622_textio_mirror(&rt);
  /* A color-only update MUST yield new full-row event. */
  m[0xB8000+2*160+1]=0x70; bb622_textio_mirror(&rt);
  free(m);return 0;
}
'''
    with tempfile.TemporaryDirectory() as td:
        path=Path(td);(path/'test.inc').write_bytes(updated);(path/'main.c').write_text(program)
        exe=path/'main'
        p=subprocess.run([cc,'-std=c11','-Wall','-Wextra','-Werror','-DPICO_ON_DEVICE=1',str(path/'main.c'),'-o',str(exe)],capture_output=True,text=True)
        if p.returncode:raise AssertionError('Firmware textio C11 compilation failed:\n'+p.stderr[:3500])
        p=subprocess.run([str(exe)],capture_output=True,text=True)
        if p.returncode:raise AssertionError('Firmware textio C11 runtime failed:\n'+p.stderr[:3500])
        out=p.stdout
        rows=re.findall(r'^\[bb622-cells\] row=02 \|([0-9A-F]{320})\|$',out,re.M)
        if len(rows)!=2:raise AssertionError('Expected first full cell mirror and second color-only update; got '+str(len(rows)))
        if rows[0][0:4]!='C41E' or rows[1][0:4]!='C470':raise AssertionError('CP437 color bytes not preserved')
        if len(re.findall(r'^\[bb622-cells\] row=',out,re.M))!=26:
            raise AssertionError('Expected 25 initial row events plus one attr-change row event')
        print('C11 PASS: full 25 rows, 80 char+attr cells, CP437 0xC4, color-only update retransmitted')


def selftest():
    for eol in ('LF','CRLF'):
        # Exercise exact source transform and C11 on both EOL styles.
        s='''/* BB_DOS622_TEXTIO_PSRAM_V1 */\ntypedef struct Bb622TextIOState {\n    uint64_t sample_us;\n    uint32_t row_hash[25];\n    uint8_t row_visible[25];\n    unsigned announced;\n} Bb622TextIOState;\nstatic void bb622_textio_mirror(void) {\n    uint8_t *p=0; unsigned row=0; Bb622TextIOState *s=0;\n    char chars[81];uint32_t h=0;unsigned end=0;\n        chars[end] = '\\0';\n        if (h == s->row_hash[row]) continue;\n}\n'''
        # Transform smoke with a synthetic source, compiled integration with
        # the repository's real source (not this un-compilable mock).
        b=s.replace('\n','\r\n' if eol=='CRLF' else '\n').encode()
        updated=transform(b)
        if updated.count(TAG.encode())!=1:raise AssertionError('Duplicate marker')
        if transform.__name__ != 'transform':raise AssertionError('Unexpected transform')
        print('TRANSFORM',eol,'PASS')
    src=ROOT/SRC
    if src.exists():
        updated=transform(src.read_bytes())
        test_c11(updated)
    # Confirm new runner is independent from old clean runner, and raw log saved.
    if (ROOT/'bb_make_dos622_clean_console.py').is_file():
        raw=Path(__file__).with_name('bb_make_dos622_clean_console.py').read_text('utf8')
        pattern=b'''[CmdletBinding()]\nparam(\n    [switch]$PhaseProfile\n)\n$serial=$null\nif($chunk){\n            Write-Host -NoNewline $chunk\n            [System.IO.File]::AppendAllText($log,$chunk)\n}\n                    if($k.Key -eq [ConsoleKey]::Enter){\n                        $serial.Write("`r")\n                    }\n        Start-Sleep -Milliseconds 15\n'''
        generated=make_runner(pattern)
        if b'Write-BbDos622ColorConsoleChunk' not in generated or b'AppendAllText($log,$chunk)' not in generated or b'UpArrow' not in generated or b'F1' not in generated:
            raise AssertionError('Generated runner missing color channel/raw file output')
        print('RUNNER PASS: raw transcript maintained, independent color helper')
    # End-to-end SHA/metadata cascade and exact rollback across mock layers.
    orig=(ROOT/SRC).read_bytes() if (ROOT/SRC).exists() else None
    if orig is not None:
        for endings in ('LF','CRLF'):
            with tempfile.TemporaryDirectory() as td:
                r=Path(td);(r/'src').mkdir();(r/'scripts').mkdir()
                contents=orig.replace(b'\r\n',b'\n')
                if endings=='CRLF':contents=contents.replace(b'\n',b'\r\n')
                (r/SRC).write_bytes(contents)
                (r/VGA).write_text('/* BB_DOS622_EGA_INFO_V1 */\n')
                # Synthetic original runner matching all known source anchors.
                (r/ORIGINAL_RUNNER).write_bytes(pattern)
                parents={
                  '.bb_dos622_ipl_v1_state/manifest.json':{'tag':'IPL','installed':SHA(contents)},
                  '.bb_dos622_boot_diag_v1_state/repair.json':{'tag':'BOOT','parent_after':'x'*64},
                  '.bb_dos622_heap_rescue_v1_state/manifest.json':{'tag':'HEAP','files':[]},
                  '.bb_dos622_vga12_34_v1_state/manifest.json':{'tag':'VGA12','files':[]},
                  '.bb_dos622_vga12_30_v1_state/manifest.json':{'tag':'VGA30','files':[]},
                  '.bb_dos622_keyb92_v1_state/manifest.json':{'tag':'KEYB92','files':[]},
                  EGA_STATE:{'tag':'BB_DOS622_EGA_INFO_V1','files':[{'path':VGA,'installed':SHA((r/VGA).read_bytes()),'original':SHA(b'vga-before')}]},
                }
                for path,ob in parents.items():
                    dest=r/path;dest.parent.mkdir(parents=True,exist_ok=True)
                    dest.write_text(json.dumps(ob)+'\n')
                path=r/'.bb_dos622_ipl_v1_state/manifest.json'
                parents['.bb_dos622_boot_diag_v1_state/repair.json']['parent_after']=SHA(path.read_bytes())
                (r/'.bb_dos622_boot_diag_v1_state/repair.json').write_text(json.dumps(parents['.bb_dos622_boot_diag_v1_state/repair.json'])+'\n')
                baseline={f.relative_to(r).as_posix():f.read_bytes() for f in r.rglob('*') if f.is_file()}
                found=changes(r,False)
                assert SRC in found and RUNNER in found and HOST in found
                assert '.bb_dos622_ipl_v1_state/manifest.json' in found
                assert '.bb_dos622_boot_diag_v1_state/repair.json' in found
                apply(r);verify(r);restore(r)
                after={f.relative_to(r).as_posix():f.read_bytes() for f in r.rglob('*') if f.is_file()}
                assert baseline==after, 'Exact rollback mismatch'
                print('INSTALL',endings,'PASS: SHA cascade, original runner untouched, rollback')
    print('SELFTEST PASS: no repository files altered; Pico hardware not tested')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action',choices=['selftest','probe','apply','verify','restore'])
    args=ap.parse_args()
    try:
        if args.action=='selftest':selftest()
        elif args.action=='probe':changes()
        elif args.action=='apply':apply()
        elif args.action=='verify':verify()
        elif args.action=='restore':restore()
    except (ValueError,OSError,KeyError,AssertionError,TypeError,json.JSONDecodeError) as e:
        print('ERROR:',e,file=sys.stderr);sys.exit(1)

if __name__=='__main__':main()
