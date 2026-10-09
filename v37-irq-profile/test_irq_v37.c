#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define MD_X86_SP 4
#define MD_X86_ADDRESS_MASK 0xfffff
#define BB_TEST_MEM (1<<20)
typedef struct {uint16_t r[8],cs,ip,ss,flags;uint8_t *memory;} MdX86;
typedef struct {MdX86 cpu;} MdRuntime;
static uint16_t md_x86_flags(MdX86 *c){return c->flags;}
static void md_x86_set_flags(MdX86 *c,uint16_t f){c->flags=f;}
static void md_x86_push(MdX86*c,uint16_t v){c->r[4]-=2;uint32_t a=(((uint32_t)c->ss<<4)+c->r[4])&0xfffff;c->memory[a]=v&255;c->memory[(a+1)&0xfffff]=v>>8;}
static uint64_t bb_test_clock;
uint64_t bb_now_us(void){return bb_test_clock++;}
#include "bb_irq.h"
#define CHECK(x) do{if(!(x)){printf("FAIL line %d: %s\n",__LINE__,#x);return 1;}}while(0)
int main(){static uint8_t ram[BB_TEST_MEM];MdRuntime r={0};r.cpu.memory=ram;r.cpu.cs=0x1111;r.cpu.ip=0x2222;r.cpu.ss=0x3000;r.cpu.r[4]=0x1000;r.cpu.flags=0x3202;
 ram[0x20]=0x45;ram[0x21]=0x23;ram[0x22]=0x67;ram[0x23]=0x45;
 bb_pit_init(0);bb_irq36_init(0);bb_pit_out(0x43,0x34,0,0,0,1);bb_pit_out(0x40,0xa9,0,0,0,1);bb_pit_out(0x40,0x04,0,0,0,1);
 CHECK(bb_irq36_dispatch(&r,2000)==1);CHECK(r.cpu.cs==0x4567&&r.cpu.ip==0x2345);CHECK(r.cpu.r[4]==0xffa);CHECK(!(r.cpu.flags&0x300));
 uint32_t a=0x30000+0xffa;CHECK(ram[a]==0x22&&ram[a+1]==0x22);CHECK(ram[a+2]==0x11&&ram[a+3]==0x11);CHECK(ram[a+4]==0x02&&ram[a+5]==0x32);
 CHECK(bb_irq36_dispatch(&r,3000)==0);bb_irq36_out(0x20,0x20);r.cpu.flags|=0x200;CHECK(bb_irq36_dispatch(&r,4000)==1);
 CHECK(bb_v37_dispatch_polls>=3);CHECK(bb_v37_eoi_samples>=1);
 printf("PASS v37: IRQ stack, EOI timing, sampled polls, and PIC scheduling\n");return 0;}
