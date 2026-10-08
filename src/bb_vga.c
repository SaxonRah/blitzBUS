/* blitzBUS INT 10h VGA BIOS compatibility, mode 03h and 13h.
 * All addresses refer to real guest memory (not RP2350 physical addresses).
 * Non-emulated VGA planar modes are intentionally NOT claimed supported.
 */
#include "bb_vga.h"
#include <string.h>
#define VMEM_SIZE 0x110000u
static uint8_t *mem;
static uint8_t mode, page, cols;
static uint8_t dac[256][3], dac_read, dac_write, rc, wc, pel_mask, dac_read_mode;
static uint8_t attr[32], attr_index, attr_flip, attr_enable=0x20, border;
static uint8_t cga_index, seq_index, gfx_index, crtc_index, seq[8], gfx[16], crtc[32];
static uint8_t pal_reg[16], dac_page, dac_page_mode, blink_enabled;
static uint16_t cursor[8], cursor_shape=0x0607;
static uint16_t palette[256];
static uint32_t palette_gen;
static uint64_t joy_start;
static uint8_t joy_started;
static uint16_t rgb565(unsigned r,unsigned g,unsigned b) {
    return (uint16_t)(((r*31u/63u)<<11)|((g*63u/63u)<<5)|(b*31u/63u));
}
static void set_dac(unsigned i,uint8_t r,uint8_t g,uint8_t b) {
    i&=255u; dac[i][0]=r&63u; dac[i][1]=g&63u; dac[i][2]=b&63u;
    palette[i]=rgb565(dac[i][0],dac[i][1],dac[i][2]); ++palette_gen;
}
static void defaults(void) {
    static const uint8_t ega[16][3]={{0,0,0},{0,0,42},{0,42,0},{0,42,42},
       {42,0,0},{42,0,42},{42,21,0},{42,42,42},{21,21,21},{21,21,63},
       {21,63,21},{21,63,63},{63,21,21},{63,21,63},{63,63,21},{63,63,63}};
    unsigned i;
    for(i=0;i<256;i++){
        unsigned r=0,g=0,b=0;
        if(i<16){r=ega[i][0];g=ega[i][1];b=ega[i][2];}
        else if(i<232){unsigned v=i-16;r=((v/36)%6)*63/5;g=((v/6)%6)*63/5;b=(v%6)*63/5;}
        else r=g=b=(i-232)*63/23;
        set_dac(i,(uint8_t)r,(uint8_t)g,(uint8_t)b);
    }
    for(i=0;i<16;i++)pal_reg[i]=(uint8_t)i;
}
static uint32_t linear(uint16_t seg,uint16_t off){return (((uint32_t)seg<<4)+off)&0xFFFFFu;}
static uint8_t mread(uint16_t s,uint16_t o){return mem[linear(s,o)];}
static void mwrite(uint16_t s,uint16_t o,uint8_t v){mem[linear(s,o)]=v;}
static void video_bda(void){
    mem[0x449]=mode;mem[0x44A]=cols;mem[0x44B]=0;
    mem[0x44C]=(uint8_t)((mode==0x13?64000u:4000u)&255u);
    mem[0x44D]=(uint8_t)((mode==0x13?64000u:4000u)>>8);
    mem[0x462]=page;
    mem[0x484]=(uint8_t)(mode==0x13?24:24);
    for(unsigned i=0;i<8;i++){
        mem[0x450+i*2]=(uint8_t)cursor[i];mem[0x451+i*2]=(uint8_t)(cursor[i]>>8);
    }
}
static void set_mode(uint8_t m,bool preserve){
    mode=m;page=0;cols=(m==0x13?40:80);
    if(!preserve)memset(mem+(m==0x13?0xA0000:0xB8000),0,(m==0x13?64000:4000));
    if(m==0x13)defaults();
    memset(cursor,0,sizeof cursor);video_bda();
}
void bb_vga_init(uint8_t *memory){
    mem=memory; mode=3;page=0;cols=80;pel_mask=255;
    dac_read=dac_write=rc=wc=dac_read_mode=0;
    attr_flip=0;attr_index=0;dac_page=0;dac_page_mode=0;blink_enabled=1;
    memset(attr,0,sizeof attr);memset(seq,0,sizeof seq);
    memset(gfx,0,sizeof gfx);memset(crtc,0,sizeof crtc);
    memset(cursor,0,sizeof cursor);defaults();video_bda();
}
static void scroll_text(unsigned top,unsigned left,unsigned bottom,unsigned right,unsigned n,uint8_t fill,int down){
    if(top>24||left>79)return;
    if(bottom>24)bottom=24;if(right>79)right=79;
    if(bottom<top||right<left)return;
    unsigned width=right-left+1,height=bottom-top+1;
    if(n>height)n=height;
    if(n&&n<height){
        if(down){for(int r=(int)bottom;r>=(int)(top+n);r--)memmove(mem+0xB8000+(r*80+left)*2,mem+0xB8000+((r-n)*80+left)*2,width*2);}
        else {for(unsigned r=top;r+n<=bottom;r++)memmove(mem+0xB8000+(r*80+left)*2,mem+0xB8000+((r+n)*80+left)*2,width*2);}
    }
    for(unsigned r=down?top:bottom-n+1;r<=(down?top+n-1:bottom);r++){
        for(unsigned c=left;c<=right;c++) {unsigned o=0xB8000+(r*80+c)*2;mem[o]=' ';mem[o+1]=fill;}
        if(!n)break;
    }
}
static void put_char(uint8_t c,uint8_t attribute,unsigned p,int advance){
    p&=7;unsigned x=cursor[p]&255u,y=cursor[p]>>8;
    if(mode==3){
        if(c==13){x=0;}
        else if(c==10){y++;}
        else if(c==8){if(x)x--;}
        else if(c==7){}
        else {if(x>=80)x=0;if(y>=25)y=24;unsigned o=0xB8000+(y*80+x)*2;mem[o]=c;mem[o+1]=attribute;x++;}
        if(x>=80){x=0;y++;}
        if(y>=25){scroll_text(0,0,24,79,1,7,0);y=24;}
        if(advance)cursor[p]=(uint16_t)((y<<8)|x);
        video_bda();
    }
}
static bool bios_palette(uint8_t al,uint16_t *bx,uint16_t *cx,uint16_t *dx,uint16_t es){
    unsigned i,n=(*cx),start=*bx&255u;
    switch(al){
    case 0x00: pal_reg[*bx&15u]=(uint8_t)(*bx>>8);return true;
    case 0x01: border=(uint8_t)(*bx>>8);return true;
    case 0x02:
        for(i=0;i<16;i++)pal_reg[i]=mread(es,(uint16_t)(*dx+i));
        border=mread(es,(uint16_t)(*dx+16));return true;
    case 0x03: blink_enabled=(uint8_t)(*bx&1u);return true;
    case 0x07:*bx=(uint16_t)((*bx&0xFF00u)|pal_reg[*bx&15u]);return true;
    case 0x08:*bx=(uint16_t)((*bx&0xFF00u)|border);return true;
    case 0x09:
        for(i=0;i<16;i++)mwrite(es,(uint16_t)(*dx+i),pal_reg[i]);
        mwrite(es,(uint16_t)(*dx+16),border);return true;
    case 0x10:set_dac(start,(uint8_t)(*dx>>8),(uint8_t)(*cx>>8),(uint8_t)*cx);return true;
    case 0x12:
        if(n>256u)n=256u; if(n>256u-start)n=256u-start;
        for(i=0;i<n;i++){
            uint16_t o=(uint16_t)(*dx+i*3u);
            set_dac(start+i,mread(es,o),mread(es,(uint16_t)(o+1)),mread(es,(uint16_t)(o+2)));
        }return true;
    case 0x13:dac_page_mode=(uint8_t)(*bx>>8);dac_page=(uint8_t)*bx;return true;
    case 0x15:
        *dx=(uint16_t)((dac[start][0]<<8)|(*dx&0x00FFu));
        *cx=(uint16_t)((dac[start][1]<<8)|dac[start][2]);return true;
    case 0x17:
        if(n>256u)n=256u;if(n>256u-start)n=256u-start;
        for(i=0;i<n;i++){
            uint16_t o=(uint16_t)(*dx+i*3u);
            mwrite(es,o,dac[start+i][0]);mwrite(es,(uint16_t)(o+1),dac[start+i][1]);mwrite(es,(uint16_t)(o+2),dac[start+i][2]);
        }return true;
    case 0x18:pel_mask=(uint8_t)*bx;return true;
    case 0x19:*bx=(uint16_t)((*bx&0xFF00u)|pel_mask);return true;
    case 0x1A:*bx=(uint16_t)((dac_page_mode<<8)|dac_page);return true;
    case 0x1B: /* VGA grayscale summing: BX=start, CX=count */
        if(n>256u)n=256u;if(n>256u-start)n=256u-start;
        for(i=0;i<n;i++){unsigned v=(dac[start+i][0]*30u+dac[start+i][1]*59u+dac[start+i][2]*11u)/100u;set_dac(start+i,(uint8_t)v,(uint8_t)v,(uint8_t)v);}return true;
    default:return false;
    }
}
bool bb_vga_int10(uint16_t *ax,uint16_t *bx,uint16_t *cx,uint16_t *dx,
                  uint16_t *es,uint16_t *bp,uint16_t *flags){
    uint8_t ah=(uint8_t)(*ax>>8),al=(uint8_t)*ax;
    (void)bp;(void)flags;
    if(!mem)return false;
    switch(ah){
    case 0x00:if((al&127)!=3&&(al&127)!=0x13)return false;set_mode(al&127,(al&128)!=0);return true;
    case 0x01:cursor_shape=*cx;mem[0x460]=(uint8_t)*cx;mem[0x461]=(uint8_t)(*cx>>8);return true;
    case 0x02:cursor[*bx>>8&7]=(uint16_t)((*dx>>8)*256u+(*dx&255u));video_bda();return true;
    case 0x03:*cx=cursor_shape;*dx=cursor[*bx>>8&7];return true;
    case 0x05:page=(uint8_t)(al&7u);video_bda();return true;
    case 0x06:if(mode==3)scroll_text(*cx>>8,*cx&255u,*dx>>8,*dx&255u,al,(uint8_t)(*bx>>8),0);return true;
    case 0x07:if(mode==3)scroll_text(*cx>>8,*cx&255u,*dx>>8,*dx&255u,al,(uint8_t)(*bx>>8),1);return true;
    case 0x08:
        if(mode==3){unsigned cur=cursor[*bx>>8&7],o=0xB8000+((cur>>8)*80u+(cur&255u))*2u;*ax=(uint16_t)((mem[o+1]<<8)|mem[o]);return true;}
        return false;
    case 0x09:case 0x0A:
        if(mode==3){unsigned p=*bx>>8&7u,cur=cursor[p],x=cur&255u,y=cur>>8;
            for(unsigned i=0;i<*cx;i++){unsigned xx=x+i,yy=y+xx/80u;xx%=80u;if(yy>=25)break;unsigned o=0xB8000+(yy*80+xx)*2;mem[o]=al;if(ah==9)mem[o+1]=(uint8_t)*bx;}return true;}
        return false;
    case 0x0C:
        if(mode==0x13&&*cx<320u&&*dx<200u){unsigned o=0xA0000+*dx*320u+*cx;
            if(al&128)mem[o]^=al&127;else mem[o]=al;return true;}return false;
    case 0x0D:
        if(mode==0x13&&*cx<320u&&*dx<200u){*ax=(uint16_t)((*ax&0xFF00u)|mem[0xA0000+*dx*320u+*cx]);return true;}return false;
    case 0x0E:put_char(al,(uint8_t)*bx,*bx>>8,1);return true;
    case 0x0F:*ax=(uint16_t)((cols<<8)|mode);*bx=(uint16_t)((page<<8)|(*bx&255u));return true;
    case 0x10:return bios_palette(al,bx,cx,dx,*es);
    case 0x1A:if(al==0){*ax=0x001A;*bx=0x0008;return true;}return false;
    default:return false;
    }
}
static uint8_t io_status(uint64_t us){uint32_t t=(uint32_t)(us%16667u);attr_flip=0;return (uint8_t)((t>=15000u?8u:0u)|(t<13500u?1u:0u));}
bool bb_vga_port_in(uint16_t p,uint8_t *out,uint64_t us){
    switch(p){
    case 0x3DA:*out=io_status(us);return true;
    case 0x3C6:*out=pel_mask;return true;
    case 0x3C7:*out=dac_read_mode?3u:0u;return true;
    case 0x3C8:*out=dac_write;return true;
    case 0x3C9:*out=dac[dac_read][rc++];if(rc==3){rc=0;dac_read++;}return true;
    case 0x3C1:*out=attr[attr_index&31];return true;
    case 0x3C5:*out=seq[seq_index&7];return true;
    case 0x3CF:*out=gfx[gfx_index&15];return true;
    case 0x3D5:*out=crtc[crtc_index&31];return true;
    case 0x201:*out=(uint8_t)(0xF0u|((joy_started&&us-joy_start<1500u)?15u:0u));return true;
    default:return false;
    }
}
bool bb_vga_port_out(uint16_t p,uint8_t v,uint64_t us){
    switch(p){
    case 0x3C6:pel_mask=v;return true;
    case 0x3C7:dac_read=v;rc=0;dac_read_mode=1;return true;
    case 0x3C8:dac_write=v;wc=0;dac_read_mode=0;return true;
    case 0x3C9:dac[dac_write][wc++]=v&63u;if(wc==3){wc=0;set_dac(dac_write,dac[dac_write][0],dac[dac_write][1],dac[dac_write][2]);dac_write++;}return true;
    case 0x3C0:if(!attr_flip){attr_index=v&31;attr_enable=v&0x20;}else attr[attr_index&31]=v;attr_flip^=1u;return true;
    case 0x3C2:return true;
    case 0x3C4:seq_index=v;return true;
    case 0x3C5:seq[seq_index&7]=v;return true;
    case 0x3CE:gfx_index=v;return true;
    case 0x3CF:gfx[gfx_index&15]=v;return true;
    case 0x3D4:crtc_index=v;return true;
    case 0x3D5:crtc[crtc_index&31]=v;return true;
    case 0x3D8:cga_index=v;return true;
    case 0x201:joy_start=us;joy_started=1;return true;
    default:return false;
    }
}
bool bb_vga_active(void){return mode==0x13;}
const uint8_t *bb_vga_framebuffer(void){return mem?mem+0xA0000:0;}
const uint16_t *bb_vga_palette565(void){return palette;}
uint32_t bb_vga_palette_generation(void){return palette_gen;}
