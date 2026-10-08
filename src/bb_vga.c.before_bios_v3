/* First VGA compatibility layer for blitzBUS DOS, unbanked mode 13h.
 * CPU memory writes remain in the single shared 1 MiB guest memory array.
 * This is intentionally not a full VGA CRTC/EGA planar emulator.
 */
#include "bb_vga.h"
#include <string.h>
static uint8_t *mem;
static uint8_t mode;
static uint8_t dac[256][3], rd_index, wr_index, rd_comp, wr_comp;
static uint8_t pel_mask, dac_read_mode;
static uint8_t attr_flip;
static uint16_t palette[256];
static uint32_t palette_gen;
static uint64_t joy_start;
static uint8_t joy_started;
static uint8_t cga_index, seq_index, gfx_index, crtc_index;
static uint8_t seq[8], gfx[16], crtc[32];
static uint16_t pack565(uint8_t r, uint8_t g, uint8_t b) {
    return (uint16_t)(((r * 31u / 63u) << 11) | ((g * 63u / 63u) << 5) | (b * 31u / 63u));
}
static void palette_set(unsigned i) {
    palette[i] = pack565(dac[i][0], dac[i][1], dac[i][2]);
    ++palette_gen;
}
static void default_palette(void) {
    static const uint8_t ega[16][3] = {
        {0,0,0},{0,0,42},{0,42,0},{0,42,42},{42,0,0},{42,0,42},{42,21,0},{42,42,42},
        {21,21,21},{21,21,63},{21,63,21},{21,63,63},{63,21,21},{63,21,63},{63,63,21},{63,63,63}
    };
    unsigned i;
    memset(dac,0,sizeof dac);
    for (i=0;i<16;i++) memcpy(dac[i],ega[i],3);
    for (i=16;i<232;i++) {
        unsigned v=i-16;
        dac[i][0]=(uint8_t)(((v/36)%6)*63/5);
        dac[i][1]=(uint8_t)(((v/6)%6)*63/5);
        dac[i][2]=(uint8_t)((v%6)*63/5);
    }
    for (i=232;i<256;i++) dac[i][0]=dac[i][1]=dac[i][2]=(uint8_t)((i-232)*63/23);
    for (i=0;i<256;i++) palette_set(i);
}
void bb_vga_init(uint8_t *memory) {
    mem=memory; mode=3; wr_index=rd_index=wr_comp=rd_comp=0;
    pel_mask=255; dac_read_mode=0; palette_gen=0; joy_start=0; joy_started=0;
    attr_flip=0; cga_index=seq_index=gfx_index=crtc_index=0;
    memset(seq,0,sizeof seq);memset(gfx,0,sizeof gfx);memset(crtc,0,sizeof crtc);
    default_palette();
}
static void set_mode(uint8_t m, bool preserve) {
    mode=m;
    if (mem) {
        mem[0x449]=m;  /* BIOS Data Area current video mode */
        mem[0x44A]=(m==0x13)?40:80; mem[0x44B]=0;
        if (!preserve && m==0x13) memset(mem+0xA0000,0,64000);
        if (!preserve && m==0x03) memset(mem+0xB8000,0,4000);
    }
    if(m==0x13) default_palette();
}
bool bb_vga_int10(uint16_t *ax,uint16_t *bx,uint16_t *cx,uint16_t *dx,uint16_t *flags) {
    uint8_t ah=(uint8_t)(*ax>>8), al=(uint8_t)*ax;
    (void)cx; (void)dx; (void)flags;
    switch(ah) {
    case 0x00:
        if((al&0x7Fu)!=0x13 && (al&0x7Fu)!=0x03) return false;
        set_mode((uint8_t)(al&0x7Fu),(al&0x80)!=0);return true;
    case 0x0F: /* get mode */
        *ax=(uint16_t)(((mode==0x13?40u:80u)<<8)|mode);
        *bx=(uint16_t)(*bx & 0x00FFu);return true;
    default: return false;
    }
}
static uint8_t io_status(uint64_t us) {
    /* Approx VGA frame (60 Hz): display-en=1 during display, retrace bit3=1 ~1.4ms. */
    uint32_t frame=(uint32_t)(us%16667u);
    uint8_t vs=(frame>=15000u)?8u:0;
    uint8_t de=(frame>=13500u)?0u:1u;
    attr_flip=0;
    return (uint8_t)(vs|de);
}
bool bb_vga_port_in(uint16_t p,uint8_t *out,uint64_t now_us) {
    switch(p) {
    case 0x3DA: *out=io_status(now_us);return true;
    case 0x3C6: *out=pel_mask;return true;
    case 0x3C7: *out=dac_read_mode?3u:0u;return true;
    case 0x3C8: *out=wr_index;return true;
    case 0x3C9:
        *out=dac[rd_index][rd_comp++];
        if(rd_comp==3) {rd_comp=0;rd_index++;}return true;
    case 0x3C5: *out=seq[seq_index&7];return true;
    case 0x3CF: *out=gfx[gfx_index&15];return true;
    case 0x3D5: *out=crtc[crtc_index&31];return true;
    case 0x201:
        /* No joystick present: axes discharge to zero after a brief interval,
           buttons (bits 4-7) remain high, i.e. not pressed. */
        *out=(uint8_t)(0xF0u | ((joy_started && now_us-joy_start<1500u)?0x0Fu:0u));return true;
    default:return false;
    }
}
bool bb_vga_port_out(uint16_t p,uint8_t value,uint64_t now_us) {
    switch(p) {
    case 0x3C6: pel_mask=value;return true;
    case 0x3C7: rd_index=value;rd_comp=0;dac_read_mode=1;return true;
    case 0x3C8: wr_index=value;wr_comp=0;dac_read_mode=0;return true;
    case 0x3C9:
        dac[wr_index][wr_comp++]=(uint8_t)(value&63u);
        if(wr_comp==3) {palette_set(wr_index);wr_comp=0;wr_index++;}return true;
    case 0x3C4: seq_index=value;return true;
    case 0x3C5: seq[seq_index&7]=value;return true;
    case 0x3CE: gfx_index=value;return true;
    case 0x3CF: gfx[gfx_index&15]=value;return true;
    case 0x3D4: crtc_index=value;return true;
    case 0x3D5: crtc[crtc_index&31]=value;return true;
    case 0x3C0: attr_flip^=1u;return true;
    case 0x3D8: cga_index=value;return true;
    case 0x201: joy_start=now_us;joy_started=1;return true;
    default:return false;
    }
}
bool bb_vga_active(void){return mode==0x13;}
const uint8_t *bb_vga_framebuffer(void){return mem?mem+0xA0000:0;}
const uint16_t *bb_vga_palette565(void){return palette;}
uint32_t bb_vga_palette_generation(void){return palette_gen;}
