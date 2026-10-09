#ifndef BB_V35_PIT_H
#define BB_V35_PIT_H
/* IBM PC 8253/8254 PIT subset. Shared by native blitz86 and microDOS interpreter.
 * Channel 0: mode 2/3, reload and latch sequencing. Channels 1/2: programmable
 * counter state (no DRAM refresh/speaker wiring yet). Reads are host-time based.
 * Caller supplies a monotonic microsecond clock. Port traces are bounded.
 */
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define BB_PIT_HZ 1193182ull
#define BB_PIT_TRACE_LIMIT 32u
typedef struct BbPitChannel {
    uint16_t reload_raw, write_latch, read_latch;
    uint64_t epoch_us;
    uint8_t access, mode, bcd, write_phase, read_phase;
    uint8_t latched, latch_phase, null_count, status_latched, status_byte;
} BbPitChannel;
typedef struct BbPit {
    BbPitChannel c[3];
    uint32_t reads[4], writes[4], interp_reads, interp_writes, native_reads, native_writes;
    uint32_t latch_count, status_latches, unsupported, trace_count;
} BbPit;
static BbPit bb_pit;
static void bb_pit_init(uint64_t now) {
    memset(&bb_pit,0,sizeof bb_pit);
    for (unsigned i=0;i<3;i++) {
        BbPitChannel *c=&bb_pit.c[i];
        c->access=3; c->mode=3; c->epoch_us=now;
        c->reload_raw=0; c->null_count=0;
    }
}
static uint16_t bb_pit_count(unsigned channel,uint64_t now) {
    BbPitChannel *c=&bb_pit.c[channel];
    const uint32_t reload=c->reload_raw?c->reload_raw:65536u;
    const uint64_t cycles=now>=c->epoch_us?((now-c->epoch_us)*BB_PIT_HZ)/1000000ull:0ull;
    const uint32_t phase=(uint32_t)(cycles%reload);
    if (c->mode==3) {
        /* Square wave: counter decreases in steps of two, odd divisors
           retain the high half for one extra input clock. */
        const uint32_t high=(reload+1u)/2u;
        uint32_t value=(phase<high)?reload-2u*phase:2u*(reload-phase);
        if (value==65536u) return 0;
        return (uint16_t)value;
    }
    if (c->mode==2) return (uint16_t)(reload-phase);
    return (uint16_t)(reload-phase);
}
static uint8_t bb_pit_status(unsigned ch) {
    BbPitChannel *c=&bb_pit.c[ch];
    return (uint8_t)((c->null_count?0x40u:0u)|((c->access&3u)<<4)|((c->mode&7u)<<1)|(c->bcd&1u));
}
static void bb_pit_trace(char io,uint16_t port,uint8_t value,uint16_t cs,uint16_t ip,int native) {
    if (bb_pit.trace_count++<BB_PIT_TRACE_LIMIT)
        printf("[bb-v35-pit] %c port=%04X value=%02X cs:ip=%04X:%04X tier=%s\n",io,port,value,cs,ip,native?"native":"interpreter");
}
static int bb_pit_in(uint16_t port,uint8_t *out,uint64_t now,uint16_t cs,uint16_t ip,int native) {
    if(port<0x40u||port>0x42u)return 0;
    const unsigned ch=port-0x40u;
    BbPitChannel *c=&bb_pit.c[ch];
    uint16_t count;
    if(c->status_latched){*out=c->status_byte;c->status_latched=0;}
    else {
        count=c->latched?c->read_latch:bb_pit_count(ch,now);
        if(c->access==2) {*out=(uint8_t)(count>>8);c->latched=0;}
        else if(c->access==1){*out=(uint8_t)count;c->latched=0;}
        else if(!c->read_phase){*out=(uint8_t)count;c->read_phase=1;}
        else {*out=(uint8_t)(count>>8);c->read_phase=0;c->latched=0;}
    }
    bb_pit.reads[ch]++;
    if(native)bb_pit.native_reads++;else bb_pit.interp_reads++;
    bb_pit_trace('I',port,*out,cs,ip,native);
    return 1;
}
static int bb_pit_out(uint16_t port,uint8_t value,uint64_t now,uint16_t cs,uint16_t ip,int native) {
    if(port<0x40u||port>0x43u)return 0;
    bb_pit.writes[port-0x40u]++;
    if(native)bb_pit.native_writes++;else bb_pit.interp_writes++;
    bb_pit_trace('O',port,value,cs,ip,native);
    if(port==0x43u){
        unsigned ch=(value>>6)&3u;
        if(ch==3u){
            /* 8254 read-back command: counter latch (bit5=0), status latch
               (bit4=0), channel selected by active-low bits 1..3. */
            for(unsigned i=0;i<3;i++)if(!(value&(1u<<(i+1u)))){
                BbPitChannel *c=&bb_pit.c[i];
                if(!(value&0x20u)&&!c->latched){c->read_latch=bb_pit_count(i,now);c->latched=1;c->read_phase=0;bb_pit.latch_count++;}
                if(!(value&0x10u)&&!c->status_latched){c->status_byte=bb_pit_status(i);c->status_latched=1;bb_pit.status_latches++;}
            }
            return 1;
        }
        BbPitChannel *c=&bb_pit.c[ch];
        unsigned rw=(value>>4)&3u;
        if(!rw){if(!c->latched){c->read_latch=bb_pit_count(ch,now);c->latched=1;c->read_phase=0;bb_pit.latch_count++;}return 1;}
        c->access=(uint8_t)rw;c->mode=(uint8_t)((value>>1)&7u);
        if(c->mode>=6)c->mode-=4;
        c->bcd=value&1u;c->write_phase=0;c->read_phase=0;c->latched=0;c->null_count=1;
        if(c->bcd)bb_pit.unsupported++;
        return 1;
    }
    BbPitChannel *c=&bb_pit.c[port-0x40u];
    if(c->access==3){
        if(!c->write_phase){c->write_latch=value;c->write_phase=1;return 1;}
        c->reload_raw=(uint16_t)(c->write_latch|((uint16_t)value<<8));c->write_phase=0;
    }else if(c->access==2)c->reload_raw=(uint16_t)value<<8;
    else c->reload_raw=value;
    c->epoch_us=now;c->null_count=0;c->latched=0;c->read_phase=0;
    return 1;
}
static void bb_pit_report(void) {
    printf("[bb-v35-pit-summary] native-in=%lu native-out=%lu interp-in=%lu interp-out=%lu port40-in=%lu port43-out=%lu latch=%lu status=%lu unsupported-bcd=%lu reload0=%u mode0=%u\n",
        (unsigned long)bb_pit.native_reads,(unsigned long)bb_pit.native_writes,
        (unsigned long)bb_pit.interp_reads,(unsigned long)bb_pit.interp_writes,
        (unsigned long)bb_pit.reads[0],(unsigned long)bb_pit.writes[3],
        (unsigned long)bb_pit.latch_count,(unsigned long)bb_pit.status_latches,
        (unsigned long)bb_pit.unsupported,(unsigned)bb_pit.c[0].reload_raw,(unsigned)bb_pit.c[0].mode);
}
#endif
