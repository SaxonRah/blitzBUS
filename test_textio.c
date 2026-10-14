#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef struct { struct { uint8_t *memory; } cpu; } MdRuntime;
static unsigned bb_video_seen;
static int enabled = 1;
static uint64_t test_now;
static bool bb_vga_active(void){return false;}
static bool bb_sd_dos622_active(void){return enabled != 0;}
static uint64_t bb_now_us(void){return test_now;}
#define PICO_ON_DEVICE 1
#define main unused_main
#include "bb_dos622_textio.inc"
#undef main
int main(void){
    MdRuntime rt={0};
    rt.cpu.memory=(uint8_t*)calloc(1,1100000);
    if(!rt.cpu.memory)return 1;
    for(int i=0;i<80;i++) rt.cpu.memory[0xB8000+i*2]=' ';
    const char *s="A:\\>";
    for(unsigned i=0;s[i];i++)rt.cpu.memory[0xB8000+i*2]=s[i];
    test_now=1000000;
    bb622_textio_mirror(&rt);
    if(bb622_textio_row_hash[0]==0 || bb622_textio_row_visible[0]!=1u)return 2;
    uint32_t h=bb622_textio_row_hash[0];
    test_now+=1000;
    rt.cpu.memory[0xB8000]='C';
    bb622_textio_mirror(&rt);
    if(bb622_textio_row_hash[0]!=h)return 3;
    test_now+=250000;
    bb622_textio_mirror(&rt);
    if(bb622_textio_row_hash[0]==h)return 4;
    h=bb622_textio_row_hash[0];
    enabled=0;test_now+=250000;
    rt.cpu.memory[0xB8000]='D';
    bb622_textio_mirror(&rt);
    if(bb622_textio_row_hash[0]!=h)return 5;
    free(rt.cpu.memory);
    puts("TEXTIO C TEST PASS");
    return 0;
}
