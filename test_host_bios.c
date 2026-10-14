#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <assert.h>
#define PICO_ON_DEVICE 1
#define __uninitialized_psram(x) __attribute__((section(".bss.mock")))
enum { MD_X86_AX,MD_X86_CX,MD_X86_DX,MD_X86_BX,MD_X86_SP,MD_X86_BP,MD_X86_SI,MD_X86_DI };
enum { MD_X86_FLAG_CF=1,MD_X86_FLAG_IF=0x200,MD_X86_FLAG_ALWAYS1=2 };
typedef struct { uint16_t r[8],es,cs,ss,ds,ip, flags; uint8_t *memory; } MdX86;
typedef struct { MdX86 cpu; } MdRuntime;
static uint16_t md_x86_flags(MdX86*c){return c->flags;}
static void md_x86_set_flags(MdX86*c,uint16_t f){c->flags=f;}
static uint16_t md_x86_read16(MdX86*c,uint16_t s,uint16_t off){unsigned a=s*16u+off;return c->memory[a]|c->memory[a+1]<<8;}
static void md_x86_write16(MdX86*c,uint16_t s,uint16_t off,uint16_t val){unsigned a=s*16u+off;c->memory[a]=val;c->memory[a+1]=val>>8;}
static void md_x86_write8(MdX86*c,uint16_t s,uint16_t off,uint8_t val){c->memory[s*16u+off]=val;}
static void md_x86_write_block(MdX86*c,uint16_t s,uint16_t off,const uint8_t*d,size_t n){memcpy(c->memory+s*16u+off,d,n);}
static void md_runtime_load_raw(MdRuntime*r,const uint8_t*d,size_t n,uint16_t s,uint16_t off){memcpy(r->cpu.memory+s*16u+off,d,n);}
static void md_runtime_mark_code_range(MdRuntime*r,uint16_t s,uint16_t off,size_t n){(void)r;(void)s;(void)off;(void)n;}
static bool md_msdos2_boot_interrupt(MdRuntime*r,uint8_t vec,void*user){(void)r;(void)vec;(void)user;return false;}
static bool bb_sd_dos622_active(void){return true;}
static bool bb_sd_dos622_read_sector(uint32_t lba,uint8_t*dst,size_t n){assert(n==512);memset(dst,(int)(lba&255),n);if(lba==0){dst[0]=0xeb;dst[510]=0x55;dst[511]=0xaa;}return true;}
#define printf(...) ((void)0)
#include "bb_dos622_bios.inc"
#undef printf
int main(){
 static uint8_t ram[0x110000];MdRuntime r={0};r.cpu.memory=ram;r.cpu.r[MD_X86_BX]=0x200;r.cpu.es=0x2000;
 assert(bb622_boot_floppy(&r));assert(r.cpu.ip==0x7c00);assert(r.cpu.memory[0x7c00]==0xeb);
 r.cpu.r[MD_X86_AX]=0x0201; r.cpu.r[MD_X86_CX]=0x0002; r.cpu.r[MD_X86_DX]=0; r.cpu.es=0x2000; r.cpu.r[MD_X86_BX]=0x200;
 assert(bb622_int13(&r)); assert(!(md_x86_flags(&r.cpu)&MD_X86_FLAG_CF));assert(r.cpu.memory[0x20200]==1);assert(r.cpu.r[0]==1);
 r.cpu.r[MD_X86_AX]=0x0301;assert(bb622_int13(&r));assert(md_x86_flags(&r.cpu)&MD_X86_FLAG_CF); assert((r.cpu.r[0]>>8)==3);
 r.cpu.r[MD_X86_AX]=0x0800;assert(bb622_int13(&r));assert(r.cpu.r[MD_X86_CX]==0x4f12);
 puts("BOOT BIOS MOCK PASS");return 0;
}
