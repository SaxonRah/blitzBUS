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
    if(ah==0x00u||ah==0x09u||ah==0x0Du) {bb622_hd_result(c,0u,0u);return true;}
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
    if(ah!=0x02u&&ah!=0x03u&&ah!=0x04u){bb622_hd_result(c,0x01u,0u);return true;}
    cyl=(uint32_t)(cx>>8)|(((uint32_t)cx&0xC0u)<<2);
    sec=(uint32_t)cx&0x3Fu;
    head=(uint32_t)(dx>>8);
    if(!n||cyl>=65u||head>=16u||!sec||sec>63u||sec+(uint32_t)n-1u>63u){
        bb622_hd_result(c,0x04u,0u);return true;
    }
    lba=(cyl*16u+head)*63u+(sec-1u);
    if(lba+n>65520u){bb622_hd_result(c,0x04u,0u);return true;}
    if((uint32_t)c->r[MD_X86_BX]+(uint32_t)n*512u>65536u){
        bb622_hd_result(c,0x09u,0u);return true;
    }
    for(i=0;i<n;i++){
        uint16_t off=(uint16_t)((uint32_t)c->r[MD_X86_BX]+i*512u);
        if(ah==0x03u){
            for(j=0;j<512u;j++)bb622_sector[j]=md_x86_read8(c,c->es,(uint16_t)(off+j));
            if(!bb_sd_hdd_write_sector(lba+i,bb622_sector,512u)){
                bb622_hd_result(c,0x20u,(uint8_t)i);return true;
            }
            ++bb622_hd_bios_writes;
        }else{
            if(!bb_sd_hdd_read_sector(lba+i,bb622_sector,512u)){
                bb622_hd_result(c,0x20u,(uint8_t)i);return true;
            }
            if(ah==0x02u)md_x86_write_block(c,c->es,off,bb622_sector,512u);
            ++bb622_hd_bios_reads;
        }
    }
    bb622_hd_result(c,0u,n);
    return true;
}
#endif
