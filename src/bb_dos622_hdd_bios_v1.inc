/* BB_DOS622_HDD_V1 -- BIOS INT13h hard disk DL=80h.
 * CHS model fixed to 65 cylinders x 16 heads x 63 sectors.
 * Separate SD file DOS622_HDD.IMG with MBR + FAT16 partition.
 * Only invoked by the DOS622 BIOS interrupt; DOS2 remains unchanged.
 */
#ifndef BB_DOS622_HDD_BIOS_V1
#define BB_DOS622_HDD_BIOS_V1
extern bool bb_sd_hdd_available(void);
extern bool bb_sd_hdd_read_sector(uint32_t lba,uint8_t *dst,size_t size);
extern bool bb_sd_hdd_write_sector(uint32_t lba,const uint8_t *src,size_t size);
static uint8_t bb622_hd_last_error;
static uint32_t bb622_hd_bios_reads,bb622_hd_bios_writes;
static void BB622_FLASH bb622_hd_result(MdX86 *c,uint8_t error,uint8_t transferred)
{
    uint16_t fl=md_x86_flags(c);
    c->r[MD_X86_AX]=(uint16_t)(((uint16_t)error<<8)|transferred);
    if(error)fl|=MD_X86_FLAG_CF;
    else fl&=(uint16_t)~MD_X86_FLAG_CF;
    md_x86_set_flags(c,fl);
    bb622_hd_last_error=error;
}
/* BB_DOS622_HDD_V2: unambiguous INT13 failure diagnostics.
 * BIOS CHS calls are naturally bounded by disk size and the guest ES:BX
 * transfer window; an emulated disk does not require physical head seeks.
 * Keep diagnostic counters tiny (RP2350 SRAM is nearly full). */
static unsigned bb622_hd_v2_fault_count, bb622_hd_v2_span_count;
static void BB622_FLASH bb622_hd_v2_fail(MdRuntime *rt, const char *why,
                                         uint8_t op, uint8_t n,
                                         uint16_t cx, uint16_t dx,
                                         uint32_t lba, uint8_t code,
                                         uint8_t transferred)
{
    if (++bb622_hd_v2_fault_count <= 48u) {
        printf("[bb622-hddv2] FAIL reason=%s AH=%02X AL=%u CX=%04X DX=%04X "
               "ES:BX=%04X:%04X lba=%lu err=%02X done=%u caller=%04X:%04X\n",
               why, (unsigned)op, (unsigned)n, (unsigned)cx, (unsigned)dx,
               (unsigned)rt->cpu.es, (unsigned)rt->cpu.r[MD_X86_BX],
               (unsigned long)lba, (unsigned)code, (unsigned)transferred,
               (unsigned)rt->cpu.cs, (unsigned)rt->cpu.ip);
        fflush(stdout);
    }
    bb622_hd_result(&rt->cpu,code,transferred);
}
static bool BB622_FLASH bb622_hd_int13(MdRuntime *rt)
{
    MdX86 *c=&rt->cpu;
    uint16_t ax=c->r[MD_X86_AX],cx=c->r[MD_X86_CX],dx=c->r[MD_X86_DX];
    uint8_t ah=(uint8_t)(ax>>8),n=(uint8_t)ax;
    uint32_t cyl,head,sec,lba,i;
    unsigned j;
    if(!bb_sd_hdd_available()) {
        bb622_hd_result(c,0x80u,0u);
        return true;
    }
    if(ah==0x00u||ah==0x09u||ah==0x0Cu||ah==0x0Du||ah==0x10u||ah==0x11u) {bb622_hd_result(c,0u,0u);return true;}
    if(ah==0x01u) {bb622_hd_result(c,bb622_hd_last_error,0u);return true;}
    if(ah==0x08u) {
        /* Max CHS 64/15/63, DL=1 fixed disk. */
        c->r[MD_X86_CX]=0x403Fu;
        c->r[MD_X86_DX]=0x0F01u;
        bb622_hd_result(c,0u,0u);
        return true;
    }
    if(ah==0x15u){
        /* Fixed disk type 03h; total 65520 sectors as CX:DX. */
        uint16_t fl=md_x86_flags(c);
        c->r[MD_X86_AX]=0x0300u;
        c->r[MD_X86_CX]=0u;
        c->r[MD_X86_DX]=0xFFF0u;
        md_x86_set_flags(c,(uint16_t)(fl&~MD_X86_FLAG_CF));
        return true;
    }
    /* No EDD packet interface or unimplemented functions advertised. */
    if(ah!=0x02u&&ah!=0x03u&&ah!=0x04u){bb622_hd_v2_fail(rt,"unsupported",ah,n,cx,dx,0u,0x01u,0u);return true;}
    cyl=(uint32_t)(cx>>8)|(((uint32_t)cx&0xC0u)<<2);
    sec=(uint32_t)cx&0x3Fu;
    head=(uint32_t)(dx>>8);
    if(!n||cyl>=65u||head>=16u||!sec||sec>63u){
        bb622_hd_v2_fail(rt,"invalid-chs",ah,n,cx,dx,0u,0x04u,0u);return true;
    }
    lba=(cyl*16u+head)*63u+(sec-1u);
    if(lba+n>65520u){bb622_hd_v2_fail(rt,"end-of-image",ah,n,cx,dx,lba,0x04u,0u);return true;}
    if((uint32_t)c->r[MD_X86_BX]+(uint32_t)n*512u>65536u){
        bb622_hd_v2_fail(rt,"64k-dma-boundary",ah,n,cx,dx,lba,0x09u,0u);return true;
    }
    /* Linear carry over head/track/cylinder is safe for our SD image.
       HDD V1 rejected valid multi-sector requests solely at sector 63. */
    if (sec + (uint32_t)n - 1u > 63u && ++bb622_hd_v2_span_count <= 12u) {
        printf("[bb622-hddv2] CHS-SPAN AH=%02X AL=%u C/H/S=%lu/%lu/%lu "
               "LBA=%lu..%lu (linear carry)\n",
               (unsigned)ah,(unsigned)n,(unsigned long)cyl,(unsigned long)head,
               (unsigned long)sec,(unsigned long)lba,(unsigned long)(lba+n-1u));
        fflush(stdout);
    }
    for(i=0;i<n;i++){
        uint16_t off=(uint16_t)((uint32_t)c->r[MD_X86_BX]+i*512u);
        if(ah==0x03u){
            for(j=0;j<512u;j++)bb622_sector[j]=md_x86_read8(c,c->es,(uint16_t)(off+j));
            if(!bb_sd_hdd_write_sector(lba+i,bb622_sector,512u)){
                bb622_hd_v2_fail(rt,"sd-write",ah,n,cx,dx,lba+i,0x20u,(uint8_t)i);return true;
            }
            ++bb622_hd_bios_writes;
        }else{
            if(!bb_sd_hdd_read_sector(lba+i,bb622_sector,512u)){
                bb622_hd_v2_fail(rt,"sd-read",ah,n,cx,dx,lba+i,0x20u,(uint8_t)i);return true;
            }
            if(ah==0x02u)md_x86_write_block(c,c->es,off,bb622_sector,512u);
            ++bb622_hd_bios_reads;
        }
    }
    bb622_hd_result(c,0u,n);
    return true;
}
#endif
