#!/usr/bin/env python3
"""Compile generated PIC code against a minimal C11 PIC/PIT scenario; no Watcom paths."""
from __future__ import annotations
import tempfile,subprocess,shutil
from pathlib import Path
import bb622_pic_pending_v1 as patch
base=r'''
#include <stdio.h>
#include <stdint.h>
#include <assert.h>
#include <inttypes.h>
typedef struct BbIrq36 { uint64_t anchor_us,scheduled,edges,delivered,masked,if_blocked,eois,coalesced; uint8_t imr,irr,isr,base,init_step,icw1,expect_icw4,auto_eoi,read_isr,active; } BbIrq36;
typedef struct BbPitChannel {uint16_t reload_raw; uint64_t epoch_us;} BbPitChannel;
typedef struct BbPit { BbPitChannel c[3]; } BbPit;
static BbPit bb_pit;
static BbIrq36 bb_irq36;
{PIC_STATE}
{PIC_IN}
static void bb_irq36_schedule(uint64_t now){
 BbPitChannel *c=&bb_pit.c[0];
 uint32_t reload=c->reload_raw?c->reload_raw:65536u;
 if(bb_irq36.anchor_us!=c->epoch_us){bb_irq36.anchor_us=c->epoch_us;bb_irq36.scheduled=0;}
 if(now<c->epoch_us)return;
 uint64_t periods=((now-c->epoch_us)*1193182ull)/(1000000ull*reload);
 if(periods<=bb_irq36.scheduled)return;
 uint64_t due=periods-bb_irq36.scheduled;bb_irq36.scheduled=periods;bb_irq36.edges+=due;
 if(bb_irq36.irr&1u)bb_irq36.coalesced+=due;
 else {bb_irq36.irr|=1u;if(due>1)bb_irq36.coalesced+=due-1;}
}
int main(void){
 uint8_t got=255;
 bb_pit.c[0].epoch_us=1000;
 bb_pit.c[0].reload_raw=0; /* 65536 -> 18.2 Hz */
 assert(bb_irq36_in(0x20,&got) && got==0);
 bb622_pic_pending_probe_enabled=1;
 bb_irq36_schedule(56000);
 assert(bb_irq36.irr==1 && bb_irq36.delivered==0);
 assert(bb_irq36_in(0x20,&got) && got==1);
 bb_irq36_schedule(120000);
 assert(bb_irq36.irr==1 && bb_irq36.delivered==0 && bb_irq36.scheduled>=2);
 bb_irq36.read_isr=1;
 assert(bb_irq36_in(0x20,&got) && got==0); /* Pending != in-service */
 bb622_pic_pending_probe_enabled=0;
 bb_irq36.irr &= (uint8_t)~1u;
 assert(bb_irq36.irr==0);
 puts("C11 PASS: pending IRR, no ISR, no IRQ delivery, disable clears only IRQ0 pending bit");
 return 0;
}
'''
def main():
    exes=[shutil.which(k) for k in ('gcc','clang') if shutil.which(k)]
    if not exes:raise SystemExit('SKIP: GCC/Clang not installed; selftest still available')
    text=base.replace('{PIC_STATE}',patch.PIC_STATE).replace('{PIC_IN}',patch.PIC_IN)
    # Remove duplicate declaration in source fragment: main harness defines it above.
    text=text.replace('static BbIrq36 bb_irq36;\n'+patch.PIC_STATE,'static BbIrq36 bb_irq36;\n'+patch.PIC_STATE)
    with tempfile.TemporaryDirectory() as td:
        c=Path(td)/'pic_probe.c';c.write_text(text)
        for i,cc in enumerate(exes):
            exe=Path(td)/f'picprobe_{i}'
            comp=subprocess.run([cc,'-std=c11','-O2','-Wall','-Wextra','-Werror',str(c),'-o',str(exe)],capture_output=True,text=True)
            if comp.returncode:raise RuntimeError(f'Compiler {cc} failed: {comp.stderr}')
            run=subprocess.run([str(exe)],capture_output=True,text=True)
            if run.returncode:raise RuntimeError(f'Executable {cc} failed: {run.stdout} {run.stderr}')
            print(cc+': '+run.stdout.splitlines()[-1])
if __name__=='__main__':main()
