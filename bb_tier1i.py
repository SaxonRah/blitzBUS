#!/usr/bin/env python3
"""blitzBUS Tier 1I exact IRET timing, reversible, no Git patches."""
from pathlib import Path
import argparse, shutil, re, subprocess, os, sys

MARK='TIER1I_EXACT_IRET'

def once(s,old,new,label):
    if s.count(old)!=1: raise RuntimeError(f'{label}: expected one occurrence; found {s.count(old)}')
    return s.replace(old,new,1)

def run_action(action, root, blitz, port, seconds):
    live=root/'src'/'bb_live.c'; interp=blitz/'src'/'interp.c'
    backup=root/'tier1i-backups'
    targets=[(live,backup/'bb_live.c'),(interp,backup/'blitz86-interp.c')]
    if action=='restore':
        if not all(y.exists() for x,y in targets): raise RuntimeError('Missing Tier 1I backup(s); refusing partial restore')
        for x,y in targets: shutil.copy2(y,x)
        shutil.rmtree(backup)
        print('Restored blitzBUS and blitz86 originals.')
        return
    if action=='install':
        if backup.exists(): raise RuntimeError('Tier 1I backup directory already exists. Restore first.')
        a=live.read_text(encoding='utf-8'); b=interp.read_text(encoding='utf-8')
        if MARK in a or MARK in b: raise RuntimeError('Tier 1I already present')
        if 'bb-t1h' in a or 'bb1h_' in a: raise RuntimeError('Tier 1H is still installed. Run: python bb_tier1h.py restore')
        if not re.search(r'(?m)^#define\s+BB_SLICE_US\s+1000u?\s*$',a):
            raise RuntimeError('Expected 1ms configuration. Restore 1ms baseline first.')
        # Exact callback immediately following x86 IRET semantics (including FLAGS restoration).
        old='case 0xCF: s->ip = pop(c); b86_set_seg(c, B86_CS, pop(c)); FL = (pop(c) & 0x0FD5u) | 0xF002u; break;'
        new='''case 0xCF: {
        s->ip = pop(c); b86_set_seg(c, B86_CS, pop(c)); FL = (pop(c) & 0x0FD5u) | 0xF002u;
#if defined(__GNUC__)
        /* TIER1I_EXACT_IRET: optional callback, disabled for other consumers. */
        extern void b86_t1i_iret_done(B86Cpu *, uint16_t) __attribute__((weak));
        if (b86_t1i_iret_done) b86_t1i_iret_done(c, (uint16_t)s->ip);
#endif
        break;
    }'''
        b=once(b,old,new,'blitz86 IRET opcode')
        block='''
/* TIER1I_EXACT_IRET -- opt-in IRQ0 latency probe; no guest state writes. */
static uint64_t bb1i_entry_us,bb1i_entry_count,bb1i_iret_count;
static uint64_t bb1i_irq0_return_count,bb1i_irq0_us_sum,bb1i_irq0_us_max;
static uint64_t bb1i_overlap_count,bb1i_other_iret,bb1i_jit_calls_at_entry;
static uint64_t bb1i_jit_calls_to_return;
static uint16_t bb1i_saved_cs,bb1i_saved_ip;
static int bb1i_active;
void b86_t1i_iret_done(B86Cpu *cpu, uint16_t final_ip) {
    ++bb1i_iret_count;
    if(bb1i_active && (uint16_t)cpu->seg[B86_CS]==bb1i_saved_cs &&
       final_ip==bb1i_saved_ip) {
        uint64_t dt=bb_now_us()-bb1i_entry_us;
        bb1i_irq0_us_sum+=dt;
        if(dt>bb1i_irq0_us_max)bb1i_irq0_us_max=dt;
        ++bb1i_irq0_return_count;
        bb1i_jit_calls_to_return+=bb_v24_jit_calls-bb1i_jit_calls_at_entry;
        bb1i_active=0;
    } else ++bb1i_other_iret;
}
static void bb1i_report(void) {
    printf("[bb-t1i] irq0-entries=%llu all-iret=%llu matched-irq0-iret=%llu "
           "overlap=%llu other-iret=%llu irq0-us-sum=%llu irq0-us-max=%llu "
           "jit-calls-until-iret=%llu pending=%d\\n",
           (unsigned long long)bb1i_entry_count,(unsigned long long)bb1i_iret_count,
           (unsigned long long)bb1i_irq0_return_count,(unsigned long long)bb1i_overlap_count,
           (unsigned long long)bb1i_other_iret,(unsigned long long)bb1i_irq0_us_sum,
           (unsigned long long)bb1i_irq0_us_max,
           (unsigned long long)bb1i_jit_calls_to_return,bb1i_active);
}
/* END TIER1I_EXACT_IRET */
'''
        # Globals bb_v24_jit_calls are declared below #include area: insert after declaration.
        anchor='static uint64_t bb_v24_jit_calls'
        k=a.find(anchor)
        if k<0: raise RuntimeError('Could not find global JIT counter declaration')
        e=a.find(';',k)
        if e<0: raise RuntimeError('Malformed JIT counter declaration')
        a=a[:e+1]+ '\n'+block+a[e+1:]
        a=once(a,'    if(rt==R)bb_irq36_dispatch(rt,bb_now_us());','''    if(rt==R) {
        uint64_t bb1i_previous=bb_irq36.delivered;
        uint16_t bb1i_cs=rt->cpu.cs,bb1i_ip=rt->cpu.ip;
        uint64_t bb1i_now=bb_now_us();
        bb_irq36_dispatch(rt,bb1i_now);
        if(bb_irq36.delivered!=bb1i_previous) {
            if(bb1i_active)++bb1i_overlap_count;
            ++bb1i_entry_count;
            bb1i_active=1; bb1i_entry_us=bb1i_now;
            bb1i_saved_cs=bb1i_cs;bb1i_saved_ip=bb1i_ip;
            bb1i_jit_calls_at_entry=bb_v24_jit_calls;
        }
    }''','IRQ entry')
        a=once(a,'    bb_irq36_report();\n#ifdef BB_V49_PC_PROFILE','    bb_irq36_report();\n    bb1i_report();\n#ifdef BB_V49_PC_PROFILE','stats')
        backup.mkdir(parents=True)
        try:
            for x,y in targets: shutil.copy2(x,y)
            live.write_text(a,encoding='utf-8'); interp.write_text(b,encoding='utf-8')
        except Exception:
            for x,y in targets:
                if y.exists():shutil.copy2(y,x)
            shutil.rmtree(backup)
            raise
        print('Tier 1I exact-IRET probe installed in both projects. Original files saved.')
        print('No PIC/PIT or IRET semantics changed; callback only observes completed IRET.')
        return
    if action=='run':
        if MARK not in live.read_text(encoding='utf-8') or MARK not in interp.read_text(encoding='utf-8'):
            raise RuntimeError('Tier 1I is not installed in BOTH projects; refusing to run uninstrumented build.')
        env=os.environ.copy()
        env.update(BB_LCD_PERI_HZ='150000000',BB_LCD_SPI_HZ='75000000',BB_LCD_LACE='1',BB_BBUF='0',BB_CODE_KB='292',BB_HOT_THRESHOLD='32')
        cmd=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(root/'scripts'/'bb_live_run.ps1'),'-MicroDOS',r'C:\microDOS','-Blitz86',str(blitz),'-Port',port,'-Seconds',str(seconds)]
        subprocess.run(cmd,env=env,check=True)
        return

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action',choices=['install','run','restore'])
    ap.add_argument('--root',type=Path,default=Path(r'C:\blitzBUS'))
    ap.add_argument('--blitz86',type=Path,default=Path(r'C:\blitz86_v2'))
    ap.add_argument('--port',default='COM5'); ap.add_argument('--seconds',type=int,default=180)
    args=ap.parse_args()
    try:run_action(args.action,args.root,args.blitz86,args.port,args.seconds)
    except Exception as exc:print('ERROR:',exc,file=sys.stderr);sys.exit(1)
