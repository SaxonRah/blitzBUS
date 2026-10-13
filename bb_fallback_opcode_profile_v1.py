#!/usr/bin/env python3
"""Sample fallback interpreter opcodes in blitz86 without changing guest behavior.

This experiment is intended to be layered ON TOP OF the already-working
chain audit -> exit split -> hotspot -> eager-unchaining ON installation.
It adds approximately 1,120 bytes to the existing PSRAM JIT metadata allocation,
and 8 bytes of JIT state in SRAM. It samples one out of every 64 calls to
b86h_step(), including both sequential helpers and control-flow helpers.
It reports the 12 hottest opcodes plus F6/F7/FF ModR/M /reg subgroups.

The report is a SAMPLED distribution of ALL interpreter-step helper calls,
not necessarily just the exits counted as normal-dynamic. It is for finding
which unsupported opcodes merit native implementation next, not an A/B
performance improvement. The sampling itself may change benchmark scores.

Usage from C:\\blitzBUS:
    python .\\bb_fallback_opcode_profile_v1.py probe
    python .\\bb_fallback_opcode_profile_v1.py apply
    python .\\bb_fallback_opcode_profile_v1.py verify
    # rebuild and run with your usual bb_live_run.ps1 command
    python .\\bb_fallback_opcode_profile_v1.py analyze
    python .\\bb_fallback_opcode_profile_v1.py restore

VERY IMPORTANT: restore THIS profiler before using the eager unchaining
controller's set/restore commands, because that controller refuses to
overwrite jit.c if later instrumentation is present.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import sys
import glob
from pathlib import Path

ROOT=Path(__file__).resolve().parent
MARK='BB_FALLBACK_OPCODE_PROFILE_V1'
MANIFEST=ROOT/'bb_fallback_opcode_profile_v1_manifest.json'


def digest(b:bytes)->str: return hashlib.sha256(b).hexdigest()
def decode(b:bytes):
    bom=b.startswith(b'\xef\xbb\xbf')
    s=b.decode('utf-8-sig')
    return s, '\r\n' if '\r\n' in s else '\n', bom

def encode(s:str,bom:bool)->bytes:
    return (b'\xef\xbb\xbf' if bom else b'')+s.encode('utf-8')

def once(s:str,needle:str,replacement:str,label:str)->str:
    n=s.count(needle)
    if n!=1: raise RuntimeError(f'{label}: expected one anchor; found {n}; no edits applied')
    return s.replace(needle,replacement,1)

def lines(s:str,nl:str)->str:
    return s.replace('\n',nl)

def patch_jit(s:str,nl:str)->str:
    if MARK in s: raise RuntimeError('JIT profiler already installed')
    if 'BB_EXIT_HOTSPOT_V1' not in s or 'BB_DEADSTUB_UNCHAIN_AB_V1' not in s:
        raise RuntimeError('Expected previous exit-hotspot and dead-stub experiments in jit.c')
    s=once(s,'#define PLOGN 4096u', lines('''/* BB_FALLBACK_OPCODE_PROFILE_V1: diagnostic-only, 1/64 helper sampling.
   256 opcodes + 8 each for FF/F6/F7 ModR/M groups = 280 uint32s.
   The table is allocated via B86_CALLOC (the existing PSRAM allocator). */
#define BB_FB_SAMPLING_MASK 63u
#define PLOGN 4096u''',nl),'jit compile-time options')
    s=once(s,'    uint32_t nfree;',lines('''    uint32_t nfree;
    uint32_t *bb_fb_hist; /* BB_FALLBACK_OPCODE_PROFILE_V1: PSRAM, 280 entries */
    uint32_t bb_fb_tick;  /* counts interpreter helper calls */''',nl),'jit J fields')
    # Allocate after the original hot/codemap allocation success check and
    # before returning from the JIT constructor. No change to existing
    # allocation failure or native-cache behavior.
    needle='    j->cpu = c;'
    s=once(s,needle,lines('''    /* BB_FALLBACK_OPCODE_PROFILE_V1: optional PSRAM diagnostic table. */
    j->bb_fb_hist = B86_CALLOC(280u, sizeof *j->bb_fb_hist);
''',nl)+needle,'jit JIT constructor PSRAM allocation')
    s=once(s,'    B86_FREE(j->cov); B86_FREE(j->ent); B86_FREE(j->heat_key); B86_FREE(j->heat);',
           '    B86_FREE(j->cov); B86_FREE(j->ent); B86_FREE(j->heat_key); B86_FREE(j->heat);'+nl+
           '    B86_FREE(j->bb_fb_hist); /* '+MARK+' */', 'jit destructor')
    needle='    c->jit->st.rt_step++;'
    code='''    /* BB_FALLBACK_OPCODE_PROFILE_V1: sample interpreter fallbacks sparsely.
       fb() uses existing guest paging logic; no writes to guest memory. */
    {
        J *pj = c->jit;
        uint32_t tick = ++pj->bb_fb_tick;
        if (pj->bb_fb_hist && (tick & BB_FB_SAMPLING_MASK) == 0u) {
            uint32_t ip = ip_next & 0xFFFFu;
            uint32_t cs = c->seg[B86_CS];
            uint8_t op = 0;
            for (unsigned p = 0; p < 8u; ++p) {
                op = fb(c, cs, ip++);
                if (op != 0x26 && op != 0x2E && op != 0x36 && op != 0x3E &&
                    op != 0xF2 && op != 0xF3 && op != 0xF0 && op != 0xF1) break;
            }
            ++pj->bb_fb_hist[op];
            if (op == 0xFF || op == 0xF6 || op == 0xF7) {
                unsigned reg = (fb(c, cs, ip) >> 3) & 7u;
                unsigned base = op == 0xFF ? 256u : op == 0xF6 ? 264u : 272u;
                ++pj->bb_fb_hist[base + reg];
            }
        }
    }
'''
    s=once(s,needle,needle+nl+lines(code,nl).rstrip('\r\n'),'jit step helper instrumentation')
    # Expose a read-only histogram pointer to the blitzBUS reporting code.
    needle='B86_HOT const B86JitStats *b86_jit_stats(J *j)'
    api='''/* BB_FALLBACK_OPCODE_PROFILE_V1: read-only diagnostic API, no copy or new SRAM table. */
B86_HOT const uint32_t *b86_jit_fallback_counts(J *j, uint32_t *calls)
{
    if (calls) *calls = j ? j->bb_fb_tick : 0u;
    return j ? j->bb_fb_hist : NULL;
}

'''
    s=once(s,needle,lines(api,nl)+needle,'jit reporter function')
    return s

def patch_public(s:str,nl:str)->str:
    if MARK in s:raise RuntimeError('Public profiler API already installed')
    needle='const B86JitStats *b86_jit_stats(struct B86Jit *j);'
    return once(s,needle,needle+nl+
                '/* '+MARK+': opcodes [0..255], FF groups [256..263], F6 [264..271], F7 [272..279]. */'+nl+
                'const uint32_t *b86_jit_fallback_counts(struct B86Jit *j, uint32_t *calls);',
                'public profiler API')

def patch_live(s:str,nl:str)->str:
    if MARK in s:raise RuntimeError('Live profiler reporting already installed')
    anchor='    printf("[bb-jit] native-ms='
    report=r'''    /* BB_FALLBACK_OPCODE_PROFILE_V1: expensive only when reporting (Ctrl+]). */
    {
        uint32_t calls = 0;
        const uint32_t *h = b86_jit_fallback_counts(J, &calls);
        if (h) {
            unsigned op[12]; uint32_t count[12];
            for (unsigned k = 0; k < 12u; ++k) {
                uint32_t best = 0; unsigned bestop = 256u;
                for (unsigned o = 0; o < 256u; ++o) {
                    if (h[o] <= best) continue;
                    int seen = 0;
                    for (unsigned a = 0; a < k; ++a)
                        if (op[a] == o) { seen = 1; break; }
                    if (!seen) { best = h[o]; bestop = o; }
                }
                op[k] = bestop; count[k] = best;
            }
            printf("[bb-fallback] calls=%lu period=64 samples=%lu top=",
                   (unsigned long)calls, (unsigned long)(calls >> 6));
            for (unsigned k = 0; k < 12u && count[k]; ++k)
                printf("%s%02X:%lu", k ? "," : "", op[k], (unsigned long)count[k]);
            printf(" ff=");
            for (unsigned i = 0; i < 8u; ++i)
                printf("%s%lu", i ? "," : "", (unsigned long)h[256u+i]);
            printf(" f6=");
            for (unsigned i = 0; i < 8u; ++i)
                printf("%s%lu", i ? "," : "", (unsigned long)h[264u+i]);
            printf(" f7=");
            for (unsigned i = 0; i < 8u; ++i)
                printf("%s%lu", i ? "," : "", (unsigned long)h[272u+i]);
            printf("\n");
        } else {
            printf("[bb-fallback] PSRAM allocation unavailable; diagnostics disabled\n");
        }
    }
'''
    # The raw string contains literal \\n escape sequences needed by C; only
    # source newline characters are normalized to match the existing file.
    return once(s,anchor,lines(report,nl)+anchor,'live profile output')

def file_paths(blitz86:Path):
    return {'jit':blitz86/'src'/'jit.c',
            'public':blitz86/'include'/'b86.h',
            'live':ROOT/'src'/'bb_live.c'}

def plan(blitz86:Path):
    ret={}
    for name,path in file_paths(blitz86).items():
        if not path.exists():raise RuntimeError('Missing source '+str(path))
        old=path.read_bytes();s,nl,bom=decode(old)
        new={'jit':patch_jit,'public':patch_public,'live':patch_live}[name](s,nl)
        newdata=encode(new,bom)
        backup=path.with_name(path.name+'.bb-fallback-profile-v1.bak')
        if backup.exists():raise RuntimeError('Existing backup; refusing overwrite: '+str(backup))
        ret[name]=dict(file=path,backup=backup,old=old,new=newdata)
    return ret

def probe(blitz86:Path):
    errors=0
    for name,path in file_paths(blitz86).items():
        try:
            s,nl,bom=decode(path.read_bytes())
            changed={'jit':patch_jit,'public':patch_public,'live':patch_live}[name](s,nl)
            print(f'{name:8s} READY {path} (+{len(changed)-len(s)} chars)')
        except Exception as e:
            errors+=1;print(f'{name:8s} STOP {e}')
    if errors:raise RuntimeError('Probe failed; no source files changed.')

def apply(blitz86:Path):
    if MANIFEST.exists():raise RuntimeError('Already applied; use verify or restore.')
    changes=plan(blitz86)  # all anchors checked before files are touched
    made=[];written=[]
    try:
        for v in changes.values():
            v['backup'].write_bytes(v['old']);made.append(v['backup'])
        for v in changes.values():
            v['file'].write_bytes(v['new']);written.append(v['file'])
        manifest={'marker':MARK,'files':{name:dict(path=str(v['file']),backup=str(v['backup']),
                  original_sha=digest(v['old']),installed_sha=digest(v['new'])) for name,v in changes.items()}}
        MANIFEST.write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    except BaseException:
        for v in changes.values():
            if v['file'] in written:v['file'].write_bytes(v['old'])
        for b in made:b.unlink(missing_ok=True)
        raise
    print('Profiler installed. Diagnostic-only; PSRAM histogram and sampling enabled.')
    verify()

def read_manifest():
    if not MANIFEST.exists():raise RuntimeError('Manifest missing; run apply.')
    m=json.loads(MANIFEST.read_text(encoding='utf-8'))
    if m.get('marker')!=MARK:raise RuntimeError('Manifest marker mismatch')
    return m

def verify():
    m=read_manifest()
    for name,v in m['files'].items():
        path=Path(v['path']);backup=Path(v['backup'])
        if not path.exists() or digest(path.read_bytes())!=v['installed_sha']:
            raise RuntimeError(name+': source changed since profiler installation; refusing to overwrite')
        if not backup.exists() or digest(backup.read_bytes())!=v['original_sha']:
            raise RuntimeError(name+': backup missing or modified')
        print(f'{name:8s} OK {path}')
    print('Checksums verified. Firmware compilation and RP2350 behavior not yet tested.')

def restore():
    verify()  # refuse to clobber independent changes
    m=read_manifest()
    for v in m['files'].values(): Path(v['path']).write_bytes(Path(v['backup']).read_bytes())
    for v in m['files'].values():Path(v['backup']).unlink()
    MANIFEST.unlink()
    print('Original files restored byte-for-byte. Rebuild firmware for prior behavior.')

def analyze(pattern:str):
    files=glob.glob(pattern)
    if not files:raise RuntimeError('No console logs match '+pattern)
    for path in sorted(files,key=lambda x:Path(x).stat().st_mtime)[-8:]:
        entries=[]
        for line in Path(path).read_text(encoding='utf-8',errors='replace').splitlines():
            if '[bb-fallback]' not in line or ' top=' not in line:continue
            fields={m.group(1):int(m.group(2)) for m in re.finditer(r'\b(calls|period|samples)=(\d+)',line)}
            top=re.search(r'\btop=([^ ]+)',line)
            if not top:continue
            counts={int(k,16):int(v) for k,v in re.findall(r'\b([0-9A-F]{2}):(\d+)',top.group(1))}
            entries.append((fields,counts))
        if not entries:continue
        print('\nLOG',path)
        prev={}
        last_samples=0
        for n,(f,counts) in enumerate(entries,1):
            samples=f.get('samples',0)
            # If an opcode dropped from top-12, its cumulative count is not
            # available. Flag intervals with incomplete top-N accounting.
            keys=set(prev)|set(counts)
            delta={k:counts.get(k,0)-prev.get(k,0) for k in keys if k in counts and k in prev}
            pct=100.0*sum(max(0,x) for x in delta.values())/max(1,samples-last_samples)
            print(f'report={n} calls={f.get("calls",0)} samples={samples} '
                  f'delta-samples={samples-last_samples} overlap-top12-share={pct:.1f}%')
            print('  cumulative top:', ', '.join(f'{k:02X}:{v}' for k,v in counts.items()))
            last_samples=samples;prev=counts

def main():
    ap=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('action',choices=['probe','apply','verify','restore','analyze'])
    ap.add_argument('--blitz86',default=r'C:\blitz86_v2')
    ap.add_argument('--log',default=str(ROOT/'logs'/'bb-live-*-console.txt'))
    args=ap.parse_args()
    try:
        if args.action=='probe':probe(Path(args.blitz86))
        elif args.action=='apply':apply(Path(args.blitz86))
        elif args.action=='verify':verify()
        elif args.action=='restore':restore()
        else:analyze(args.log)
    except Exception as e:
        print('ERROR:',e,file=sys.stderr);sys.exit(1)

if __name__=='__main__':main()
