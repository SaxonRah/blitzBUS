/* Exact transformed BIOS HDD source linked to a deterministic C11 fake guest and disk. */
#include <assert.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#define BB622_FLASH
#define MD_X86_AX 0
#define MD_X86_CX 1
#define MD_X86_DX 2
#define MD_X86_BX 3
#define MD_X86_FLAG_CF 1u
#define IMG_SECTORS 65520u
struct MdX86 { uint16_t r[8]; uint16_t es,cs,ip,flags; uint8_t mem[65536]; };
typedef struct MdX86 MdX86;
typedef struct MdRuntime { MdX86 cpu; } MdRuntime;
static uint8_t bb622_sector[512];
static uint8_t disk[IMG_SECTORS][2];
static uint32_t last_read, last_write, reads,writes;
static bool have=true, io_fail=false;
bool bb_sd_hdd_available(void){return have;}
bool bb_sd_hdd_read_sector(uint32_t lba,uint8_t *p,size_t n){
 if(n!=512||lba>=IMG_SECTORS||io_fail)return false;
 last_read=lba;reads++;p[0]=disk[lba][0];p[1]=disk[lba][1];memset(p+2,0,510);return true;
}
bool bb_sd_hdd_write_sector(uint32_t lba,const uint8_t *p,size_t n){
 if(n!=512||lba>=IMG_SECTORS||io_fail)return false;
 last_write=lba;writes++;disk[lba][0]=p[0];disk[lba][1]=p[1];return true;
}
uint16_t md_x86_flags(MdX86 *c){return c->flags;}
void md_x86_set_flags(MdX86 *c,uint16_t f){c->flags=f;}
uint8_t md_x86_read8(MdX86*c,uint16_t s,uint16_t o){(void)s;return c->mem[o];}
void md_x86_write_block(MdX86*c,uint16_t s,uint16_t o,const uint8_t*p,size_t n){
 (void)s;assert((unsigned)o+n<=65536);memcpy(c->mem+o,p,n);
}
#include "bb_dos622_hdd_bios_v2_transformed.inc"
static MdRuntime *rt;
static uint16_t call(uint16_t ax,uint16_t bx,uint16_t cx,uint16_t dx){
 MdX86*c=&rt->cpu;
 c->r[MD_X86_AX]=ax;c->r[MD_X86_BX]=bx;c->r[MD_X86_CX]=cx;c->r[MD_X86_DX]=dx;
 c->es=0x1200;c->cs=0x4444;c->ip=0x3333;c->flags=0x203;
 assert(bb622_hd_int13(rt));return c->r[MD_X86_AX];
}
static void success(uint16_t ax){assert(rt->cpu.r[MD_X86_AX]==ax);assert(!(rt->cpu.flags&1));}
static void failure(uint8_t error){assert(rt->cpu.r[MD_X86_AX]>>8==error);assert(rt->cpu.flags&1);}
int main(void){
 rt=calloc(1,sizeof(*rt));assert(rt);
 assert(call(0x0800,0,0,0x80)==0 && rt->cpu.r[MD_X86_CX]==0x403f && rt->cpu.r[MD_X86_DX]==0x0f01);
 assert(call(0x1500,0,0,0x80)==0x300);
 /* Last sector of track 0 + first 2 of head 1 (was rejected by V1). */
 disk[62][0]=0x40;disk[63][0]=0x41;disk[64][0]=0x42;
 assert(call(0x0203,0x1000,0x003f,0x0080)==3);success(3);
 assert(rt->cpu.mem[0x1000]==0x40 && rt->cpu.mem[0x1200]==0x41 && rt->cpu.mem[0x1400]==0x42);
 assert(last_read==64);
 /* Track 15 -> cylinder 1, 63 -> 64 */
 uint32_t lba=(15*63)+62;assert(lba==1007);
 for(uint32_t i=0;i<3;i++) disk[lba+i][0]=(uint8_t)(0x70+i);
 assert(call(0x0203,0x1800,0x003f,0x0f80)==3);success(3);
 assert(rt->cpu.mem[0x1800]==0x70&&rt->cpu.mem[0x1a00]==0x71&&rt->cpu.mem[0x1c00]==0x72);
 /* Multiple writes and reads across a boundary, including verify-only. */
 rt->cpu.mem[0x2000]=0x56;rt->cpu.mem[0x2200]=0x57;
 assert(call(0x0302,0x2000,0x003f,0x0080)==2);success(2);
 assert(disk[62][0]==0x56&&disk[63][0]==0x57);
 rt->cpu.mem[0x2000]=0;rt->cpu.mem[0x2200]=0;
 assert(call(0x0402,0x2000,0x003f,0x0080)==2);success(2);
 assert(rt->cpu.mem[0x2000]==0&&rt->cpu.mem[0x2200]==0);
 assert(call(0x0202,0x2000,0x003f,0x0080)==2);success(2);
 assert(rt->cpu.mem[0x2000]==0x56&&rt->cpu.mem[0x2200]==0x57);
 assert(call(0x0201,0xFF00,0x0001,0x0080)==0x0900);failure(0x09);
 assert(call(0x0200,0x2000,0x0001,0x0080)==0x0400);failure(0x04);
 assert(call(0x0202,0x2000,0x403f,0x0f80)==0x0400);failure(0x04);
 assert(call(0x4100,0x2000,0x0001,0x0080)==0x0100);failure(0x01);
 assert(call(0x0c00,0,0,0x80)==0);success(0);
 assert(call(0x1000,0,0,0x80)==0);success(0);
 assert(call(0x1100,0,0,0x80)==0);success(0);
 io_fail=true;
 assert(call(0x0201,0x2000,0x0001,0x0080)==0x2000);failure(0x20);
 assert(call(0x0301,0x2000,0x0001,0x0080)==0x2000);failure(0x20);
 io_fail=false;
 have=false;assert(call(0x0201,0x2000,0x0001,0x0080)==0x8000);failure(0x80);
 free(rt);
 puts("C11 HDD V2 PASS: cross-track/cylinder read+write, verify, DMA guard, EOF, errors, 0Ch/10h/11h");
}
