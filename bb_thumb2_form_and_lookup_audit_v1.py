#!/usr/bin/env python3
"""blitz86 RP2350: opcode-form fallback + native fast-lookup miss audit.

Layer this on the working chain-exit-split + hotspot + eager-unchaining ON
installation, AFTER restoring both older fallback/INT profilers.

Edits FULL files (no git patch), preserving original bytes/line endings:
  C:\\blitz86_v2\\src\\jit.c
  C:\\blitz86_v2\\include\\b86.h
  C:\\blitzBUS\\src\\bb_live.c

PSRAM: 224 uint32 histogram slots (~896 bytes); SRAM: two uint32 J counters.
No guest CPU state/semantics are changed. This is a DIAGNOSTIC build;
measure 3DBench FPS only after restore, with 232 KiB code cache.

  cd C:\\blitzBUS
  python bb_int_vector_profile_v1.py restore       # only if installed
  python bb_fallback_opcode_profile_v1.py restore  # only if installed
  python bb_deadstub_unchain_ab_v2.py verify       # should say ON
  python bb_thumb2_form_and_lookup_audit_v1.py probe
  python bb_thumb2_form_and_lookup_audit_v1.py apply
  python bb_thumb2_form_and_lookup_audit_v1.py verify
  # Build/flash with normal 232 KiB, threshold=32, and run T2ECPU + 3DBENCH.
  python bb_thumb2_form_and_lookup_audit_v1.py analyze
  python bb_thumb2_form_and_lookup_audit_v1.py restore

Counters:
  [bb-form-audit] tier=step  - sampled interpreter helper calls (1 in 32)
  [bb-form-audit] tier=native - opcode forms emitted natively, by translation
  [bb-form-audit] tier=helper - opcode forms compiled through b86h_step
  [bb-lookup-audit]          - native fast lookup miss categories (1 in 16)

The native/helper tiers are code-generation counts, NOT execution counts.
Top-N form lists are cumulative; the analyzer reports common-key deltas.
"""
from __future__ import annotations
import argparse, hashlib, json, glob, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MARK = 'BB_THUMB2_FORM_LOOKUP_AUDIT_V1'
MANIFEST = ROOT / 'bb_thumb2_form_and_lookup_audit_v1_manifest.json'
SRC = {'jit': Path(r'C:\blitz86_v2\src\jit.c'),
       'public': Path(r'C:\blitz86_v2\include\b86.h'),
       'live': ROOT / 'src' / 'bb_live.c'}
N_SLOTS=224


def sha(x:bytes)->str: return hashlib.sha256(x).hexdigest()
def read(b:bytes):
    bom=b.startswith(b'\xef\xbb\xbf')
    t=b.decode('utf-8-sig')
    return t, '\r\n' if '\r\n' in t else '\n', bom

def enc(t:str,bom:bool)->bytes:
    return (b'\xef\xbb\xbf' if bom else b'')+t.encode('utf-8')

def nlf(t:str,nl:str)->str: return t.replace('\n',nl)

def one(t:str,needle:str,replacement:str,desc:str)->str:
    n=t.count(needle)
    if n!=1:raise RuntimeError(f'{desc}: expected 1 exact anchor, found {n}; no source changed')
    return t.replace(needle,replacement,1)


def patch_jit(t:str,nl:str)->str:
    if MARK in t:raise RuntimeError('Audit already installed')
    if 'BB_EXIT_HOTSPOT_V1' not in t or 'BB_DEADSTUB_UNCHAIN_AB_V1' not in t or 'XR_FASTMISS' not in t:
        raise RuntimeError('Requires chain-exit-split V2, hotspot V1, eager-unchain instrumentation')
    if 'BB_INT_VECTOR_PROFILE_V1' in t or 'BB_FALLBACK_OPCODE_PROFILE_V1' in t:
        raise RuntimeError('First restore bb_int_vector_profile_v1.py, then bb_fallback_opcode_profile_v1.py')

    t=one(t,'    uint32_t nfree;',nlf('''    uint32_t nfree;
    /* BB_THUMB2_FORM_LOOKUP_AUDIT_V1: sampled runtime forms / translated forms / fast misses in PSRAM. */
    uint32_t *bb_audit_hist; /* 224 uint32 words, PSRAM allocator */
    uint32_t bb_audit_steps;
    uint32_t bb_audit_native_misses;''',nl),'J struct fields')
    t=one(t,'    j->cpu = c;',nlf(f'''    /* {MARK}: optional ~896B PSRAM histogram. */
    j->bb_audit_hist = B86_CALLOC({N_SLOTS}u, sizeof *j->bb_audit_hist);
''',nl)+'    j->cpu = c;','PSRAM diagnostic allocation')
    needle='    B86_FREE(j->cov); B86_FREE(j->ent); B86_FREE(j->heat_key); B86_FREE(j->heat);'
    t=one(t,needle,needle+nl+f'    B86_FREE(j->bb_audit_hist); /* {MARK} */','histogram destructor')

    step_code='''    /* BB_THUMB2_FORM_LOOKUP_AUDIT_V1: 1/32 interpreter-helper samples.
       Decode only the four candidate opcodes. No guest state is changed. */
    {
        J *aj = c->jit;
        uint32_t st = ++aj->bb_audit_steps;
        if (aj->bb_audit_hist && !(st & 31u)) {
            uint32_t ip = ip_next & 0xFFFFu, cs = c->seg[B86_CS];
            uint8_t op = 0;
            for (unsigned p = 0; p < 8u; ++p) {
                op = fb(c, cs, ip++);
                if (op != 0x26 && op != 0x2E && op != 0x36 && op != 0x3E &&
                    op != 0xF0 && op != 0xF2 && op != 0xF3) break;
            }
            int family = op == 0xD1 ? 0 : op == 0xD2 ? 1 :
                         op == 0x81 ? 2 : op == 0x83 ? 3 : -1;
            if (family >= 0) {
                uint8_t m = fb(c, cs, ip);
                uint32_t form = (uint32_t)family * 16u + ((m >> 3) & 7u)*2u + ((m >> 6) != 3u);
                ++aj->bb_audit_hist[form];
            }
        }
    }
'''
    anchor='    c->jit->st.rt_step++;'
    t=one(t,anchor,anchor+nl+nlf(step_code,nl).rstrip('\r\n'),'interpreter-step sample')

    form_code='''            /* BB_THUMB2_FORM_LOOKUP_AUDIT_V1: compiled forms, not runtime frequencies.
               A demoted native instruction is counted only on its retry. */
            if (j->bb_audit_hist && (ok || !d->native)) {
                int family = d->op == 0xD1 ? 0 : d->op == 0xD2 ? 1 :
                             d->op == 0x81 ? 2 : d->op == 0x83 ? 3 : -1;
                if (family >= 0) {
                    uint32_t form = (uint32_t)family * 16u + (d->reg & 7u)*2u + (d->mod != 3u);
                    ++j->bb_audit_hist[(ok ? 64u : 128u) + form];
                }
            }
'''
    anchor='            if (!ok) {\r\n' if nl=='\r\n' else '            if (!ok) {\n'
    # Count only the fallback after the demotion retry, not other `if (!ok)` sites.
    old=nlf('''            if (!ok && d->native) { d->native = 0; demoted = 1; break; }
            if (!ok) {''',nl)
    new=nlf('''            if (!ok && d->native) { d->native = 0; demoted = 1; break; }
'''+form_code+'''            if (!ok) {''',nl)
    t=one(t,old,new,'native-vs-helper lowering form counts')

    miss_code='''        /* BB_THUMB2_FORM_LOOKUP_AUDIT_V1: classify every 16th native
           fast-table miss.  The target key is now in ctx CS:IP (NOT `key`,
           which identifies the previously dispatched source block). */
        if (r == XR_FASTMISS) {
            uint32_t mt = ++j->bb_audit_native_misses;
            if (j->bb_audit_hist && !(mt & 15u)) {
                uint32_t target = (c->seg[B86_CS] << 16) | (c->ip & 0xFFFFu);
                uint32_t fslot = fast_hash(target);
                uint32_t stored = j->fast[fslot].key;
                uint32_t *h = j->bb_audit_hist;
                Block *live = map_find(j, target);
                ++h[192u];
                if (stored == 0xFFFFFFFFu) { ++h[193u]; if (live) ++h[200u]; }
                else if (stored != target) { ++h[194u]; if (live) ++h[199u]; }
                else ++h[195u];
                if (live) ++h[196u]; else ++h[197u];
                if (j->fast[fslot].host == be_code_ptr(j->e.x_miss)) ++h[198u];
            }
        }
'''
    anchor='        int r = j->enter(c, be_code_ptr(host));'
    t=one(t,anchor,anchor+nl+nlf(miss_code,nl).rstrip('\r\n'),'native-fast-miss categorization')

    api='''/* BB_THUMB2_FORM_LOOKUP_AUDIT_V1: read-only metadata histogram.
   [0..63] runtime helper forms sampled 1/32
   [64..127] forms lowered to Thumb-2
   [128..191] forms translated using interpreter helper
   [192..200] sampled fast-lookup miss categories */
const uint32_t *b86_jit_form_lookup_counts(J *j, uint32_t *step_calls,
                                             uint32_t *fast_misses)
{
    if (step_calls) *step_calls = j ? j->bb_audit_steps : 0u;
    if (fast_misses) *fast_misses = j ? j->bb_audit_native_misses : 0u;
    return j ? j->bb_audit_hist : NULL;
}

'''
    anchor='B86_HOT const B86JitStats *b86_jit_stats(J *j)'
    t=one(t,anchor,nlf(api,nl)+anchor,'read-only histogram access API')
    return t


def patch_public(t:str,nl:str)->str:
    if MARK in t: raise RuntimeError('Already installed')
    needle='const B86JitStats *b86_jit_stats(struct B86Jit *j);'
    return one(t,needle,needle+nl+f'/* {MARK}: diagnostic-only, PSRAM-backed histogram. */'+nl+
               'const uint32_t *b86_jit_form_lookup_counts(struct B86Jit *j, uint32_t *step_calls,'+nl+
               '                                          uint32_t *fast_misses);','public declaration')


def patch_live(t:str,nl:str)->str:
    if MARK in t:raise RuntimeError('Already installed')
    report=r'''    /* BB_THUMB2_FORM_LOOKUP_AUDIT_V1: read histogram only on Ctrl+] reports. */
    {
        uint32_t steps = 0, misses = 0;
        const uint32_t *h = b86_jit_form_lookup_counts(J, &steps, &misses);
        if (!h) {
            printf("[bb-form-audit] PSRAM diagnostic allocation failed\n");
        } else {
            const unsigned opcode[4] = {0xD1u, 0xD2u, 0x81u, 0x83u};
            const char *tiers[3] = {"step", "native", "helper"};
            for (unsigned tier = 0u; tier < 3u; ++tier) {
                uint32_t total = 0;
                for (unsigned i = 0; i < 64u; ++i) total += h[tier*64u+i];
                printf("[bb-form-audit] tier=%s total=%lu step-calls=%lu rate=32 top=",
                       tiers[tier], (unsigned long)total, (unsigned long)steps);
                unsigned chosen[12];
                for (unsigned k = 0; k < 12u; ++k) {
                    unsigned besti = 64u; uint32_t best = 0;
                    for (unsigned i = 0; i < 64u; ++i) {
                        uint32_t v = h[tier*64u+i];
                        if (v <= best) continue;
                        int seen = 0;
                        for (unsigned p = 0; p < k; ++p)
                            if (chosen[p] == i) { seen = 1; break; }
                        if (!seen) { best = v; besti = i; }
                    }
                    chosen[k] = besti;
                    if (!best) break;
                    printf("%s%02X/%u%c:%lu", k ? "," : "", opcode[besti/16u],
                           (besti%16u)/2u, (besti & 1u) ? 'm' : 'r',
                           (unsigned long)best);
                }
                printf("\n");
            }
            printf("[bb-lookup-audit] native-misses=%lu sampled=%lu empty=%lu "
                   "collision=%lu same=%lu live=%lu absent=%lu miss-host=%lu "
                   "collision-live=%lu empty-live=%lu\n",
                   (unsigned long)misses, (unsigned long)h[192u],
                   (unsigned long)h[193u], (unsigned long)h[194u],
                   (unsigned long)h[195u], (unsigned long)h[196u],
                   (unsigned long)h[197u], (unsigned long)h[198u],
                   (unsigned long)h[199u], (unsigned long)h[200u]);
        }
    }
'''
    anchor='    printf("[bb-jit] native-ms='
    return one(t,anchor,nlf(report,nl)+anchor,'live reporter insert')


PATCH={'jit':patch_jit,'public':patch_public,'live':patch_live}


def paths(blitz86:Path):
    return {'jit':blitz86/'src'/'jit.c',
            'public':blitz86/'include'/'b86.h',
            'live':ROOT/'src'/'bb_live.c'}


def plan(blitz86:Path):
    items={}
    for name,path in paths(blitz86).items():
        if not path.is_file(): raise RuntimeError(f'{name}: file missing: {path}')
        raw=path.read_bytes();t,nl,bom=read(raw)
        changed=PATCH[name](t,nl)
        back=path.with_name(path.name+'.bb-form-lookup-audit-v1.bak')
        if back.exists():raise RuntimeError(f'Backup already exists, refusing overwrite: {back}')
        items[name]={'source':path,'backup':back,'before':raw,'after':enc(changed,bom)}
    return items


def probe(blitz86:Path):
    errors=0
    for name,path in paths(blitz86).items():
        try:
            old=path.read_bytes(); s,nl,bom=read(old)
            new=PATCH[name](s,nl)
            print(f'{name:6s} READY {path} (+{len(new)-len(s)} characters)')
        except Exception as ex:
            print(f'{name:6s} STOP {ex}')
            errors+=1
    if errors:raise RuntimeError('Probe failed; no files were changed')


def install(blitz86:Path):
    if MANIFEST.exists():raise RuntimeError('Manifest already exists; verify or restore instead')
    entries=plan(blitz86)
    backed=[];written=[]
    try:
        for e in entries.values():
            e['backup'].write_bytes(e['before']);backed.append(e)
        for e in entries.values():
            e['source'].write_bytes(e['after']);written.append(e)
        record={'marker':MARK,'files':{name:{
                'source':str(e['source']),'backup':str(e['backup']),
                'original_sha':sha(e['before']),'installed_sha':sha(e['after'])}
                for name,e in entries.items()}}
        MANIFEST.write_text(json.dumps(record,indent=2),encoding='utf-8')
    except BaseException:
        for e in written:e['source'].write_bytes(e['before'])
        for e in backed:e['backup'].unlink(missing_ok=True)
        MANIFEST.unlink(missing_ok=True)
        raise
    print('Installed form + lookup diagnostic; earlier instrumentation retained.')
    verify()


def manifest():
    if not MANIFEST.exists():raise RuntimeError('Manifest missing; run apply first')
    m=json.loads(MANIFEST.read_text(encoding='utf-8'))
    if m.get('marker')!=MARK:raise RuntimeError('Invalid manifest marker')
    return m


def verify():
    m=manifest()
    for name,f in m['files'].items():
        p,b=Path(f['source']),Path(f['backup'])
        if not p.is_file() or sha(p.read_bytes())!=f['installed_sha']:
            raise RuntimeError(f'{name}: installed file changed; refusing unsafe restore')
        if not b.is_file() or sha(b.read_bytes())!=f['original_sha']:
            raise RuntimeError(f'{name}: backup corrupted or missing')
        print(f'{name:6s} OK {p}')
    print('SHA256 verified; compilation and hardware behavior not yet verified.')


def restore():
    verify()
    m=manifest()
    for f in m['files'].values():Path(f['source']).write_bytes(Path(f['backup']).read_bytes())
    for f in m['files'].values():Path(f['backup']).unlink(missing_ok=True)
    MANIFEST.unlink()
    print('Restored all three source files byte-for-byte. Earlier instrumentation remains.')


def parse_top(line):
    m=re.search(r'\btop=([^\s]*)',line)
    if not m:return {}
    return {k:int(v) for k,v in re.findall(r'([0-9A-Fa-f]{2}/[0-7][mr]):(\d+)',m.group(1))}


def extract_number(line,key):
    m=re.search(r'(?:^|\s)'+re.escape(key)+r'=(\d+)',line)
    return int(m.group(1)) if m else 0


def analyze(log_pattern:str):
    files=glob.glob(log_pattern)
    if not files:raise RuntimeError('No logs matched '+log_pattern)
    good=False
    for path in sorted(files,key=lambda f:Path(f).stat().st_mtime)[-10:]:
        lines=Path(path).read_text(encoding='utf-8',errors='replace').splitlines()
        snapshots={}
        lookups=[]
        for line in lines:
            if '[bb-form-audit] tier=' in line:
                tier=re.search(r'\btier=(\w+)',line).group(1)
                snapshots.setdefault(tier,[]).append((extract_number(line,'total'),parse_top(line)))
            if '[bb-lookup-audit]' in line:
                keys=('native-misses','sampled','empty','collision','same','live','absent','miss-host','collision-live','empty-live')
                lookups.append({k:extract_number(line,k) for k in keys})
        if not lookups and not snapshots:continue
        good=True
        print('\nLOG',path)
        for tier, records in snapshots.items():
            print(' '+tier+':')
            prev_total=0;prev={}
            for i,(total,tops) in enumerate(records,1):
                delta=total-prev_total if total>=prev_total else total
                common={k:v-prev[k] for k,v in tops.items() if k in prev}
                print(f'   report={i} total={total} delta={delta} top='+', '.join(f'{k}:{v}' for k,v in list(tops.items())[:8]))
                if i>1:
                    print('     overlap delta (only forms in both top lists): '+', '.join(f'{k}:{v}' for k,v in sorted(common.items(),key=lambda q:-q[1])[:8]))
                prev_total,prev=total,tops
        prev=None
        for i,cur in enumerate(lookups,1):
            keys=('native-misses','sampled','empty','collision','same','live','absent','miss-host','collision-live','empty-live')
            print(' lookup report='+str(i)+' '+', '.join(f'{k}={cur[k]}' for k in keys))
            if prev:
                print('   interval delta: '+', '.join(f'{k}={cur[k]-prev[k] if cur[k]>=prev[k] else cur[k]}' for k in keys))
            prev=cur
    if not good: raise RuntimeError('No new [bb-form-audit]/[bb-lookup-audit] results in logs; run a fresh build')


def main():
    p=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('action',choices=['probe','apply','verify','restore','analyze'])
    p.add_argument('--blitz86',default=r'C:\blitz86_v2')
    p.add_argument('--log',default=str(ROOT/'logs'/'bb-live-*-console.txt'))
    args=p.parse_args()
    try:
        if args.action=='probe':probe(Path(args.blitz86))
        elif args.action=='apply':install(Path(args.blitz86))
        elif args.action=='verify':verify()
        elif args.action=='restore':restore()
        elif args.action=='analyze':analyze(args.log)
    except Exception as ex:
        print('ERROR:',ex,file=sys.stderr)
        raise SystemExit(1)
if __name__=='__main__':main()
