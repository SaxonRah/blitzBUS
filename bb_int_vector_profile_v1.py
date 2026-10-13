#!/usr/bin/env python3
"""blitz86: sampled INT imm8 vector/AH/callsite profiler layered on fallback V1.

Run from C:\\blitzBUS, with bb_fallback_opcode_profile_v1.py already installed:

  python bb_int_vector_profile_v1.py probe
  python bb_int_vector_profile_v1.py apply
  python bb_int_vector_profile_v1.py verify
  # Build/flash your usual target; run T2ECPU, 3DBENCH, Ctrl+] reports.
  python bb_int_vector_profile_v1.py analyze
  python bb_int_vector_profile_v1.py restore

Changes only C:\\blitz86_v2\\src\\jit.c and C:\\blitzBUS\\src\\bb_live.c.
No Git patches. Both are backed up byte-for-byte, with SHA-256 verification.

The existing fallback sampling rate (1/64 interpreter-step calls) is retained.
When a sampled opcode is CD, record the INT vector, AH for four familiar
BIOS/DOS vectors, and a small 4-way associative caller table. Everything
lives in the same PSRAM-allocated histogram. Added capacity: 7,172 bytes;
no extra JIT state fields, no new static SRAM buffers. Callsite samples are
approximate (a small lossy table); vector/AH histograms are not lossy.

IMPORTANT: Restore this profiler BEFORE restoring the fallback V1 profiler or
toggling eager unchaining. Other tools will correctly reject files changed
since their manifests were written.
"""
from __future__ import annotations
import argparse, glob, hashlib, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MARK = 'BB_INT_VECTOR_PROFILE_V1'
MANIFEST = ROOT / 'bb_int_vector_profile_v1_manifest.json'
START = 280
VEC = 280
AH21 = 536
AH10 = 792
AH16 = 1048
AH1A = 1304
SITE = 1560
COLL = 2072
CAPACITY = 2073


def sha(b: bytes) -> str: return hashlib.sha256(b).hexdigest()
def read_text_bytes(b: bytes):
    bom = b.startswith(b'\xef\xbb\xbf')
    s = b.decode('utf-8-sig')
    return s, ('\r\n' if '\r\n' in s else '\n'), bom

def reencode(s: str, bom: bool) -> bytes:
    return (b'\xef\xbb\xbf' if bom else b'') + s.encode('utf-8')

def newline(s: str, nl: str) -> str: return s.replace('\n', nl)

def replace_once(s: str, old: str, new: str, name: str) -> str:
    n = s.count(old)
    if n != 1: raise RuntimeError(f'{name}: expected exactly one anchor, found {n}; no edits applied')
    return s.replace(old, new, 1)


def patch_jit(s: str, nl: str) -> str:
    if MARK in s: raise RuntimeError('INT-vector profiler already installed')
    if 'BB_FALLBACK_OPCODE_PROFILE_V1' not in s:
        raise RuntimeError('Fallback opcode profile V1 must already be installed')
    # Extend ONLY the existing PSRAM histogram, preserving the initial 280 counts.
    s = replace_once(s, 'B86_CALLOC(280u, sizeof *j->bb_fb_hist)',
        f'B86_CALLOC({CAPACITY}u, sizeof *j->bb_fb_hist) /* {MARK}: INT vector/AH/site */',
        'JIT PSRAM allocation')
    old = '            ++pj->bb_fb_hist[op];'
    more = '''            /* BB_INT_VECTOR_PROFILE_V1: CD-only sampled breakdown, guest unchanged.
               ip already points just past the opcode (prefixes skipped above). */
            if (op == 0xCD) {
                uint8_t vector = fb(c, cs, ip);
                uint32_t *hist = pj->bb_fb_hist;
                uint32_t ah = (c->r[B86_AX] >> 8) & 0xFFu;
                ++hist[280u + vector];
                if (vector == 0x21) ++hist[536u + ah];
                if (vector == 0x10) ++hist[792u + ah];
                if (vector == 0x16) ++hist[1048u + ah];
                if (vector == 0x1A) ++hist[1304u + ah];
                /* 64 sets x 4 slots: no host heap, no per-sample log I/O.
                   Collision overflows are counted, never overwrite hot keys. */
                uint32_t key = (cs << 16) | (ip_next & 0xFFFFu);
                uint32_t hash = (key ^ (key >> 7) ^ (key >> 16)) & 63u;
                uint32_t *bucket = &hist[1560u + hash * 8u];
                int found = 0;
                for (unsigned slot = 0; slot < 4u; ++slot) {
                    uint32_t *entry = &bucket[slot * 2u];
                    if (entry[1] == 0u || entry[0] == key) {
                        entry[0] = key;
                        ++entry[1];
                        found = 1;
                        break;
                    }
                }
                if (!found) ++hist[2072u];
            }
'''
    s = replace_once(s, old, old + nl + newline(more, nl).rstrip('\r\n'), 'JIT CD sample')
    return s


def patch_live(s: str, nl: str) -> str:
    if MARK in s: raise RuntimeError('INT-vector reporter already installed')
    if 'BB_FALLBACK_OPCODE_PROFILE_V1' not in s:
        raise RuntimeError('Fallback opcode profile V1 reporter required')
    old = '    printf("[bb-jit] native-ms='
    more = r'''    /* BB_INT_VECTOR_PROFILE_V1: report-only PSRAM histogram traversal. */
    {
        uint32_t calls = 0;
        const uint32_t *h = b86_jit_fallback_counts(J, &calls);
        if (h) {
            uint32_t cd_samples = 0;
            for (unsigned i = 0; i < 256u; ++i) cd_samples += h[280u + i];
            printf("[bb-int-vector] calls=%lu cd-samples=%lu collisions=%lu top=",
                   (unsigned long)calls, (unsigned long)cd_samples,
                   (unsigned long)h[2072u]);
            unsigned used[12];
            for (unsigned k = 0; k < 12u; ++k) {
                uint32_t best = 0; unsigned idx = 256u;
                for (unsigned v = 0; v < 256u; ++v) {
                    if (h[280u + v] <= best) continue;
                    int seen = 0;
                    for (unsigned p = 0; p < k; ++p) if (used[p] == v) { seen = 1; break; }
                    if (!seen) { best = h[280u + v]; idx = v; }
                }
                used[k] = idx;
                if (!best) break;
                printf("%s%02X:%lu", k ? "," : "", idx, (unsigned long)best);
            }
            printf("\n");
            const unsigned vectors[4] = {0x21u,0x10u,0x16u,0x1Au};
            const unsigned bases[4] = {536u,792u,1048u,1304u};
            for (unsigned t = 0; t < 4u; ++t) {
                if (!h[280u+vectors[t]]) continue;
                printf("[bb-int-ah] vector=%02X top=", vectors[t]);
                unsigned seen_ah[6];
                for (unsigned k = 0; k < 6u; ++k) {
                    uint32_t best = 0; unsigned idx = 256u;
                    for (unsigned v = 0; v < 256u; ++v) {
                        if (h[bases[t]+v] <= best) continue;
                        int seen = 0;
                        for (unsigned p = 0; p < k; ++p) if (seen_ah[p] == v) { seen = 1; break; }
                        if (!seen) { best = h[bases[t]+v]; idx = v; }
                    }
                    seen_ah[k] = idx;
                    if (!best) break;
                    printf("%s%02X:%lu", k ? "," : "", idx, (unsigned long)best);
                }
                printf("\n");
            }
            printf("[bb-int-site] top=");
            unsigned used_slot[8];
            for (unsigned k = 0; k < 8u; ++k) {
                uint32_t best = 0; unsigned idx = 256u;
                for (unsigned p = 0; p < 256u; ++p) {
                    uint32_t v = h[1560u + p*2u + 1u];
                    if (v <= best) continue;
                    int seen = 0;
                    for (unsigned q = 0; q < k; ++q) if (used_slot[q] == p) { seen = 1; break; }
                    if (!seen) { best = v; idx = p; }
                }
                used_slot[k] = idx;
                if (!best) break;
                uint32_t addr = h[1560u + idx*2u];
                printf("%s%04lX:%04lX:%lu", k ? "," : "",
                       (unsigned long)(addr >> 16),
                       (unsigned long)(addr & 0xFFFFu), (unsigned long)best);
            }
            printf("\n");
        }
    }
'''
    return replace_once(s, old, newline(more, nl) + old, 'live reporter output')


def paths(blitz86: Path):
    return {'jit': blitz86 / 'src' / 'jit.c', 'live': ROOT / 'src' / 'bb_live.c'}


def plan(blitz86: Path):
    ret = {}
    for name, path in paths(blitz86).items():
        if not path.is_file(): raise RuntimeError('Source not found: ' + str(path))
        old = path.read_bytes(); s, nl, bom = read_text_bytes(old)
        newstr = (patch_jit if name == 'jit' else patch_live)(s, nl)
        back = path.with_name(path.name + '.bb-int-vector-profile-v1.bak')
        if back.exists(): raise RuntimeError('Backup exists, refusing overwrite: ' + str(back))
        ret[name] = {'file': path, 'backup': back, 'old': old, 'new': reencode(newstr, bom)}
    return ret


def probe(blitz86: Path):
    failed = 0
    for name, path in paths(blitz86).items():
        try:
            s, nl, bom = read_text_bytes(path.read_bytes())
            out = (patch_jit if name == 'jit' else patch_live)(s, nl)
            print(f'{name:5s} READY {path} (+{len(out)-len(s)} chars)')
        except Exception as e:
            failed += 1; print(f'{name:5s} STOP {e}')
    if failed: raise RuntimeError('Probe failed; no files modified')


def apply(blitz86: Path):
    if MANIFEST.exists(): raise RuntimeError('Already applied; use verify or restore')
    changes = plan(blitz86)
    backed, written = [], []
    try:
        for v in changes.values():
            v['backup'].write_bytes(v['old']); backed.append(v)
        for v in changes.values():
            v['file'].write_bytes(v['new']); written.append(v)
        manifest = {'marker': MARK, 'files': {k: {'path': str(v['file']),
               'backup': str(v['backup']), 'original_sha': sha(v['old']),
               'installed_sha': sha(v['new'])} for k,v in changes.items()}}
        MANIFEST.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    except BaseException:
        for v in written: v['file'].write_bytes(v['old'])
        for v in backed: v['backup'].unlink(missing_ok=True)
        MANIFEST.unlink(missing_ok=True)
        raise
    print('Installed INT vector/AH/caller profiler (CD samples only); prior diagnostics retained')
    verify()


def load_manifest():
    if not MANIFEST.exists(): raise RuntimeError('Manifest absent; run apply first')
    m = json.loads(MANIFEST.read_text(encoding='utf-8'))
    if m.get('marker') != MARK: raise RuntimeError('Manifest marker mismatch')
    return m


def verify():
    m = load_manifest()
    for name, rec in m['files'].items():
        path, backup = Path(rec['path']), Path(rec['backup'])
        if not path.is_file() or sha(path.read_bytes()) != rec['installed_sha']:
            raise RuntimeError(name + ': source changed after apply; refusing overwrite')
        if not backup.is_file() or sha(backup.read_bytes()) != rec['original_sha']:
            raise RuntimeError(name + ': backup changed or missing')
        print(f'{name:5s} OK {path}')
    print('Checksums verified; firmware build and Pico behavior still require hardware testing')


def restore():
    verify()
    m = load_manifest()
    for rec in m['files'].values(): Path(rec['path']).write_bytes(Path(rec['backup']).read_bytes())
    for rec in m['files'].values(): Path(rec['backup']).unlink()
    MANIFEST.unlink()
    print('Restored prior fallback profiler sources byte-for-byte')


def parse_top(line: str):
    m = re.search(r'\btop=([^\s]*)', line)
    if not m: return {}
    return {k: int(v) for k,v in re.findall(r'([0-9A-Fa-f]{2}):(\d+)', m.group(1))}


def analyze(pattern: str):
    logs = glob.glob(pattern)
    if not logs: raise RuntimeError('No logs matched: '+pattern)
    any_found = False
    for logfile in sorted(logs, key=lambda p: Path(p).stat().st_mtime)[-8:]:
        lines = Path(logfile).read_text(encoding='utf-8', errors='replace').splitlines()
        records = [x for x in lines if '[bb-int-vector]' in x]
        if not records: continue
        any_found = True
        print('\nLOG', logfile)
        previous, prev_calls = {}, 0
        for n,line in enumerate(records, 1):
            cur = parse_top(line)
            calls_m = re.search(r'\bcalls=(\d+)', line)
            total_m = re.search(r'\bcd-samples=(\d+)', line)
            calls = int(calls_m.group(1)) if calls_m else 0
            total = int(total_m.group(1)) if total_m else 0
            delta = {k: cur[k] - previous.get(k,0) for k in cur if (k in previous or n == 1)}
            print(f'report={n} calls={calls} delta-calls={calls-prev_calls} cd-samples={total} '
                  f'top={", ".join(f"{k}:{v}" for k,v in cur.items())}')
            print('  sampled vector delta (top overlap only):',
                  ', '.join(f'{k}:{v}' for k,v in sorted(delta.items(), key=lambda kv:-kv[1])[:8]))
            previous, prev_calls = cur, calls
        for line in lines:
            if '[bb-int-ah]' in line or '[bb-int-site]' in line:
                print(' ', line.strip())
    if not any_found: raise RuntimeError('No [bb-int-vector] reports; rebuild and capture a new log')


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('action', choices=['probe','apply','verify','restore','analyze'])
    p.add_argument('--blitz86', default=r'C:\blitz86_v2')
    p.add_argument('--log', default=str(ROOT / 'logs' / 'bb-live-*-console.txt'))
    a = p.parse_args()
    try:
        if a.action == 'probe': probe(Path(a.blitz86))
        elif a.action == 'apply': apply(Path(a.blitz86))
        elif a.action == 'verify': verify()
        elif a.action == 'restore': restore()
        else: analyze(a.log)
    except Exception as e:
        print('ERROR:', e, file=sys.stderr)
        raise SystemExit(1)

if __name__ == '__main__': main()
