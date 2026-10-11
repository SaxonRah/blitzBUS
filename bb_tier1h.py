#!/usr/bin/env python3
"""Install reversible IRQ0 observation probes into the local blitzBUS source."""
from pathlib import Path
import argparse, re, shutil, sys, subprocess, os

PROBE = r'''/* TIER1H BEGIN: observation only (not a precise IRET detector) */
static uint64_t t1h_inject_us, t1h_entrances, t1h_observed_returns;
static uint64_t t1h_entry_calls, t1h_entry_insns, t1h_sum_calls, t1h_sum_insns;
static uint64_t t1h_sum_return_us, t1h_max_return_us, t1h_overwritten;
static uint16_t t1h_saved_cs, t1h_saved_ip;
static int t1h_active;
static void t1h_enter(uint16_t cs,uint16_t ip,uint64_t now){
    if(t1h_active)++t1h_overwritten;
    ++t1h_entrances;t1h_active=1;
    t1h_saved_cs=cs;t1h_saved_ip=ip;t1h_inject_us=now;
    t1h_entry_calls=bb_v24_jit_calls;t1h_entry_insns=bb_v24_jit_insns;
}
static void t1h_observe(uint16_t cs,uint16_t ip,uint64_t now){
    /* JIT can run beyond IRET before returning. This necessarily undercounts. */
    if(!t1h_active || cs!=t1h_saved_cs || ip!=t1h_saved_ip)return;
    uint64_t dt=now-t1h_inject_us;
    t1h_sum_return_us+=dt;
    if(dt>t1h_max_return_us)t1h_max_return_us=dt;
    t1h_sum_calls+=bb_v24_jit_calls-t1h_entry_calls;
    t1h_sum_insns+=bb_v24_jit_insns-t1h_entry_insns;
    ++t1h_observed_returns;t1h_active=0;
}
static void t1h_report(void){
    printf("[bb-t1h] irq-entries=%llu return-pc-observed=%llu overwritten=%llu "
           "return-us-sum=%llu return-us-max=%llu return-jit-calls=%llu "
           "return-guest-insns=%llu pending=%d\\n",
           (unsigned long long)t1h_entrances,
           (unsigned long long)t1h_observed_returns,
           (unsigned long long)t1h_overwritten,
           (unsigned long long)t1h_sum_return_us,
           (unsigned long long)t1h_max_return_us,
           (unsigned long long)t1h_sum_calls,
           (unsigned long long)t1h_sum_insns,t1h_active);
}
/* TIER1H END */
'''
# The printf string is C source, and must contain C's actual escaped newline, not two slashes.
PROBE=PROBE.replace('pending=%d\\\\n', 'pending=%d\\n')

def exactly(s, old, new, label):
    n=s.count(old)
    if n!=1: raise ValueError('%s: expected one anchor, got %d (no files changed)'%(label,n))
    return s.replace(old,new,1)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('mode',choices=('install','restore','run'))
    ap.add_argument('--root',default=r'C:\blitzBUS')
    ap.add_argument('--port',default='COM5')
    ap.add_argument('--seconds',type=int,default=180)
    args=ap.parse_args()
    root=Path(args.root); source=root/'src'/'bb_live.c'; backup=root/'tier1h-original-bb_live.c'
    if args.mode=='restore':
        if not backup.is_file(): raise RuntimeError('Backup missing: '+str(backup))
        shutil.copy2(backup,source);backup.unlink()
        print('Original source restored. Rebuild/flash separately.')
        return
    if args.mode=='run':
        env=os.environ.copy()
        env.update(BB_LCD_PERI_HZ='150000000',BB_LCD_SPI_HZ='75000000',BB_LCD_LACE='1',BB_BBUF='0',BB_CODE_KB='292',BB_HOT_THRESHOLD='32')
        cmd=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(root/'scripts'/'bb_live_run.ps1'),'-MicroDOS',r'C:\microDOS','-Blitz86',r'C:\blitz86_v2','-Port',args.port,'-Seconds',str(args.seconds)]
        subprocess.run(cmd,check=True,env=env)
        return
    if backup.exists(): raise RuntimeError('Backup already exists. Restore before reinstalling.')
    orig=source.read_text(encoding='utf-8')
    if 'TIER1H BEGIN' in orig:raise RuntimeError('Already installed')
    if 'Tier1G' in orig:raise RuntimeError('Tier1G source detected. Restore it before installing.')
    if not re.search(r'(?m)^#define BB_SLICE_US 1000\s*$',orig):raise RuntimeError('Expected 1ms baseline source')
    s=orig
    # Counters are declared before the report function and after global JIT counters.
    anchor='static void bb_v24_report(void) {'
    s=exactly(s,anchor,PROBE+'\n'+anchor,'diagnostic declaration')
    s=exactly(s,'    bb_irq36_report();\n#ifdef BB_V49_PC_PROFILE','    bb_irq36_report();\n    t1h_report();\n#ifdef BB_V49_PC_PROFILE','report invocation')
    anchor='    if(rt==R)bb_irq36_dispatch(rt,bb_now_us());'
    replacement='''    if(rt==R) {
        uint64_t t1h_before=bb_irq36.delivered;
        uint16_t t1h_cs=rt->cpu.cs, t1h_ip=rt->cpu.ip;
        uint64_t t1h_now=bb_now_us();
        bb_irq36_dispatch(rt,t1h_now);
        if(bb_irq36.delivered!=t1h_before)t1h_enter(t1h_cs,t1h_ip,t1h_now);
    }'''
    s=exactly(s,anchor,replacement,'IRQ entry observation')
    s=exactly(s,'    to_md();\n    /* Record the FIRST post-mode-13 visit',
        '    to_md();\n    t1h_observe(rt->cpu.cs,rt->cpu.ip,bb_now_us());\n    /* Record the FIRST post-mode-13 visit',
        'return PC observation')
    # No changes to PIT/PIC, JIT CPU, IRET, timer or dispatch budget.
    shutil.copy2(source,backup)
    try:source.write_text(s,encoding='utf-8')
    except Exception:
        shutil.copy2(backup,source);backup.unlink();raise
    print('Tier 1H installed, original saved as '+str(backup))
    print('Run python bb_tier1h.py run and launch 3DBENCH. Ctrl+] yields v37 and t1h counters.')

if __name__=='__main__':
    try:main()
    except Exception as e: print('ERROR:',e,file=sys.stderr);sys.exit(1)
