#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <assert.h>
#define BB622_FLASH
#define MD_X86_AX 0
#define MD_X86_BX 3
#define MD_X86_CX 1
#define MD_X86_DX 2
#define MD_X86_FLAG_CF 1u
typedef struct MdX86 {
  uint16_t r[8];
  uint16_t es;
  uint16_t flags;
  uint8_t mem[0x10000];
} MdX86;
typedef struct MdRuntime{MdX86 cpu;}MdRuntime;
static uint8_t bb622_sector[512];
static uint8_t disk[2*65520];
static bool have=true;
bool bb_sd_hdd_available(void){return have;}
bool bb_sd_hdd_read_sector(uint32_t lba,uint8_t *p,size_t n){if(lba>=65520||n!=512)return false;memcpy(p,disk+lba*2,2);memset(p+2,0,510);return true;}
bool bb_sd_hdd_write_sector(uint32_t lba,const uint8_t *p,size_t n){if(lba>=65520||n!=512)return false;memcpy(disk+lba*2,p,2);return true;}
static uint16_t md_x86_flags(MdX86*c){return c->flags;}
static void md_x86_set_flags(MdX86*c,uint16_t f){c->flags=f;}
static uint8_t md_x86_read8(MdX86*c,uint16_t s,uint16_t o){(void)s;return c->mem[o];}
static void md_x86_write_block(MdX86*c,uint16_t s,uint16_t o,const uint8_t*src,size_t n){(void)s;memcpy(c->mem+o,src,n);}
#include "bb_dos622_hdd_bios_v1.inc"
static uint16_t call(MdRuntime*rt,uint16_t ax,uint16_t bx,uint16_t cx,uint16_t dx){
 memset(&rt->cpu,0,sizeof(rt->cpu));rt->cpu.r[MD_X86_AX]=ax;rt->cpu.r[MD_X86_BX]=bx;rt->cpu.r[MD_X86_CX]=cx;rt->cpu.r[MD_X86_DX]=dx;rt->cpu.flags=0x203;
 assert(bb622_hd_int13(rt));return rt->cpu.r[MD_X86_AX];}
int main(void){
 MdRuntime *r=calloc(1,sizeof(*r));assert(r);
 assert(call(r,0x0800,0,0,0x0080)==0);
 assert(r->cpu.r[MD_X86_CX]==0x403f);
 assert(r->cpu.r[MD_X86_DX]==0x0f01);
 assert(!(r->cpu.flags&1));
 assert(call(r,0x1500,0,0,0x0080)==0x300);
 assert(r->cpu.r[MD_X86_DX]==0xfff0);
 assert(call(r,0x4100,0,0,0x0080)==0x0100);
 assert(r->cpu.flags&1);
 /* LBA 63 -> CHS c=0 h=1 s=1 */
 disk[63*2]='A';disk[63*2+1]='B';
 assert(call(r,0x0201,0x100,0x0001,0x0180)==0x0001);
 assert(r->cpu.mem[0x100]=='A'&&r->cpu.mem[0x101]=='B');
 assert(!(r->cpu.flags&1));
 assert(call(r,0x0202,0xFF00,0x0001,0x0180)==0x0900);
 assert(r->cpu.flags&1);
 assert(call(r,0x0201,0x100,0x0040,0x0180)==0x0400);
 assert(r->cpu.flags&1);
 assert(call(r,0x0800,0,0,0x0080)==0);
 have=false;assert(call(r,0x0800,0,0,0x0080)==0x8000);
 assert(r->cpu.flags&1);
 free(r);
 puts("C11 BIOS INT13 HDD contract PASS");return 0;
}
