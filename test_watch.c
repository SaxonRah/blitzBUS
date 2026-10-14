#include <stdint.h>
#include <stdio.h>
#include <stdbool.h>
#include <stddef.h>
#define PICO_ON_DEVICE 1
#define MD_X86_AX 0
#define MD_X86_CX 1
#define MD_X86_DX 2
#define MD_X86_BX 3
#define MD_X86_SP 4
typedef struct MdX86 {uint16_t r[8],cs,ip,ss,es;uint8_t *memory;} MdX86;
typedef struct MdRuntime { MdX86 cpu; uint64_t instructions;} MdRuntime;
static struct {uint64_t retired,slices;} st;
static uint64_t bb_now_us(void) { static uint64_t n=0;return n+=1000000u;}
static unsigned md_x86_flags(MdX86 *m){(void)m;return 0x202;}
static bool bb_sd_dos622_active(void){return true;}
#include "bb_dos622_stall_watch.inc"
int main(void){static uint8_t mem[1024*1024];MdRuntime rt={0};rt.cpu.memory=mem;rt.cpu.cs=0;rt.cpu.ip=0x7c00;rt.cpu.r[MD_X86_AX]=0x0201;rt.instructions=100;bb622_watch_bios(&rt,0x13);bb622_watch_ivt(&rt,0x21);bb622_watch_slice(&rt);return 0;}
