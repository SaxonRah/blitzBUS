#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#include <stdio.h>
#include <assert.h>
#define FA_READ 1
#define FR_OK 0
typedef unsigned UINT;
typedef unsigned long FSIZE_t;
typedef int FRESULT;
typedef struct {unsigned long pos,size;} FIL;
static int f_open(FIL*fp,const char*path,int fl){(void)fp;(void)path;(void)fl;return -1;}
static int f_close(FIL*fp){(void)fp;return FR_OK;}
static int f_read(FIL*fp,void*dst,UINT n,UINT*got){(void)fp;memset(dst,0,n);*got=n;return FR_OK;}
static int f_lseek(FIL*fp,FSIZE_t off){fp->pos=off;return FR_OK;}
static FSIZE_t f_size(FIL*fp){return fp->size;}
#include "bb_dos622_sd.inc"
int main(){bb622_mount("0:");assert(!bb_sd_dos622_active());puts("SD MOCK PASS");return 0;}
