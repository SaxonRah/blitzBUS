#!/usr/bin/env python3
"""Relocate BB_THUMB2_FORM_LOOKUP_AUDIT_V1 runtime sampling out of SRAM.

Designed for an ALREADY INSTALLED bb_thumb2_form_and_lookup_audit_v1.py.
Does NOT reinstall V1 or change the 232-KiB executable code cache.
Preserves V1's original backup and manifest. Full-file SHA256 backups.

Usage (from C:\\blitzBUS):
  python bb_audit_sram_flash_fix_v1.py probe
  python bb_audit_sram_flash_fix_v1.py apply
  python bb_audit_sram_flash_fix_v1.py verify
  # rebuild normally at BB_CODE_KB=232
  python bb_thumb2_form_and_lookup_audit_v1.py analyze
  # restore order: flash-fix restore, then V1 restore
  python bb_audit_sram_flash_fix_v1.py restore
  python bb_thumb2_form_and_lookup_audit_v1.py restore

The cold helpers explicitly use .text.bb_audit_flash and noinline so the
sampling work executes from flash. The hot helper and dispatcher retain only
small counter/gate tests. This is a diagnostic tradeoff, not a benchmark build.
"""
from __future__ import annotations
import argparse,hashlib,json,re,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent
V1MANIFEST=ROOT/'bb_thumb2_form_and_lookup_audit_v1_manifest.json'
FIXMANIFEST=ROOT/'bb_audit_sram_flash_fix_v1_manifest.json'
MARK='BB_AUDIT_SRAM_FLASH_FIX_V1'


def sha(b):return hashlib.sha256(b).hexdigest()
def load_m(path):
    return json.loads(path.read_text(encoding='utf-8'))

def guard_v1():
    if not V1MANIFEST.exists():raise RuntimeError('Original V1 manifest absent: install V1 before using this fix')
    m=load_m(V1MANIFEST)
    if m.get('marker')!='BB_THUMB2_FORM_LOOKUP_AUDIT_V1':
        raise RuntimeError('Unexpected V1 manifest marker; refusing to touch sources')
    files=m.get('files',{})
    if sorted(files)!=['jit','live','public']:
        raise RuntimeError('Unexpected original manifest file set')
    for label,ent in files.items():
        src,bak=Path(ent['source']),Path(ent['backup'])
        if not src.is_file() or not bak.is_file():
            raise RuntimeError(f'{label}: source or original V1 backup missing')
        if sha(bak.read_bytes())!=ent['original_sha']:
            raise RuntimeError(f'{label}: original V1 backup changed; refusing operation')
    return m


def patch_jit(raw):
    bom=b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b''
    try:s=raw[len(bom):].decode('utf-8')
    except UnicodeDecodeError:raise RuntimeError('jit.c is not UTF-8')
    newline='\r\n' if '\r\n' in s else '\n'
    src=s.replace('\r\n','\n')
    if MARK in src:raise RuntimeError('Flash fix already installed')
    if 'BB_THUMB2_FORM_LOOKUP_AUDIT_V1' not in src:
        raise RuntimeError('V1 audit marker not found in jit.c')

    # Replace the entire inlined hot interpreter-helper histogram with a gate.
    step=re.compile(r'    /\* BB_THUMB2_FORM_LOOKUP_AUDIT_V1: 1/32 interpreter-helper samples\..*?\n    }\n(?=#ifdef B86_HELPER_HISTO)',re.S)
    small_step='''    /* BB_AUDIT_SRAM_FLASH_FIX_V1: sampling lives in flash. */
    if (c->jit->bb_audit_hist && !(++c->jit->bb_audit_steps & 31u))
        bb_audit_step_flash(c->jit, c, ip_next);
'''
    src,nstep=step.subn(small_step,src)
    if nstep!=1:raise RuntimeError(f'Interpreter helper anchor expected once, found {nstep}')

    # Replace the inlined hot native-miss classification with a gate.
    miss=re.compile(r'        /\* BB_THUMB2_FORM_LOOKUP_AUDIT_V1: classify every 16th native.*?\n        }\n(?=#ifdef B86_NOW)',re.S)
    small_miss='''        /* BB_AUDIT_SRAM_FLASH_FIX_V1: miss classification lives in flash. */
        if (r == XR_FASTMISS) {
            ++j->bb_audit_native_misses;
            if (j->bb_audit_hist && !(j->bb_audit_native_misses & 15u))
                bb_audit_miss_flash(j, c);
        }
'''
    src,nmiss=miss.subn(small_miss,src)
    if nmiss!=1:raise RuntimeError(f'Native miss anchor expected once, found {nmiss}')

    # Dedicated flash section cannot be collected into .time_critical by B86_HOT.
    # Both functions appear after map_find() and fb() and before b86h_step().
    helper='''/* BB_AUDIT_SRAM_FLASH_FIX_V1: cold opcode-form sampler.
   These explicitly live in XIP flash, not SRAM .time_critical. */
static __attribute__((noinline,section(".text.bb_audit_flash")))
void bb_audit_step_flash(J *j, B86Cpu *c, uint32_t ip_next)
{
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
        ++j->bb_audit_hist[form];
    }
}

/* BB_AUDIT_SRAM_FLASH_FIX_V1: cold native-miss classifier. */
static __attribute__((noinline,section(".text.bb_audit_flash")))
void bb_audit_miss_flash(J *j, B86Cpu *c)
{
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

'''
    needle='B86_HOT uint32_t MPF(b86h_step)(B86Cpu *c, uint32_t ip_next, uint32_t blk)'
    if src.count(needle)!=1:raise RuntimeError('b86h_step helper definition anchor unavailable')
    src=src.replace(needle,helper+needle,1)
    result=src.replace('\n',newline)
    return bom+result.encode('utf-8')


def get_entries():
    v=guard_v1()
    entries=v['files']
    for label,item in entries.items():
        src=Path(item['source'])
        if sha(src.read_bytes())!=item['installed_sha']:
            raise RuntimeError(f'{label}: source differs from original V1 install; check other modifications before applying')
    return entries


def probe():
    e=get_entries();p=Path(e['jit']['source']);raw=p.read_bytes();modified=patch_jit(raw)
    print(f'READY: {p}\n  before={len(raw)} bytes after={len(modified)} bytes')
    print('V1 original backups intact; this fix modifies jit.c only and does not reduce BB_CODE_KB.')


def apply():
    if FIXMANIFEST.exists():raise RuntimeError('Flash fix already has a manifest; verify or restore instead')
    entries=get_entries();p=Path(entries['jit']['source']);before=p.read_bytes()
    after=patch_jit(before)
    backup=p.with_name(p.name+'.bb-audit-sram-flash-fix-v1.bak')
    if backup.exists():raise RuntimeError(f'Refusing to overwrite backup {backup}')
    try:
        backup.write_bytes(before)
        p.write_bytes(after)
        mf={'marker':MARK,'source':str(p),'backup':str(backup),'before_sha':sha(before),'after_sha':sha(after)}
        FIXMANIFEST.write_text(json.dumps(mf,indent=2),encoding='utf-8')
        verify()
    except BaseException:
        p.write_bytes(before)
        backup.unlink(missing_ok=True)
        FIXMANIFEST.unlink(missing_ok=True)
        raise
    print('Flash sampler fix installed. Rebuild with BB_CODE_KB=232 (diagnostic only).')


def verify():
    if not FIXMANIFEST.exists():raise RuntimeError('Flash fix manifest missing; run apply first')
    v=guard_v1();m=load_m(FIXMANIFEST)
    if m.get('marker')!=MARK:raise RuntimeError('Unexpected flash-fix manifest')
    p,b=Path(m['source']),Path(m['backup'])
    if not p.is_file() or sha(p.read_bytes())!=m['after_sha']:
        raise RuntimeError('Modified jit.c changed; refusing unsafe restore')
    if not b.is_file() or sha(b.read_bytes())!=m['before_sha']:
        raise RuntimeError('Flash-fix backup changed; refusing unsafe restore')
    if sha(b.read_bytes())!=v['files']['jit']['installed_sha']:
        raise RuntimeError('Flash fix backup does not match initial V1 installation')
    print('VERIFIED: cold flash diagnostic installed; original V1 source and backups preserved')


def restore():
    verify()
    m=load_m(FIXMANIFEST);p,b=Path(m['source']),Path(m['backup'])
    p.write_bytes(b.read_bytes());b.unlink();FIXMANIFEST.unlink()
    print('Flash fix restored to original V1 audit installation. Now run V1 restore if finished profiling.')


def main():
    pa=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    pa.add_argument('action',choices=['probe','apply','verify','restore'])
    a=pa.parse_args()
    try:{'probe':probe,'apply':apply,'verify':verify,'restore':restore}[a.action]()
    except Exception as ex:print('ERROR:',ex,file=sys.stderr);sys.exit(1)
if __name__=='__main__':main()
