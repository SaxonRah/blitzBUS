#!/bin/sh
# Host/qemu build of the 3DBENCH profile harness (Thumb-2, Pico table sizes).
#   tests/build_3dbench.sh MICRODOS BLITZ86 OUTDIR [extra -D flags]
# Disk image: mkfat12 --command COMMAND.COM --add .../3DBENCH.EXE 3DBENCH.EXE
#   (plus .HED .PAL .PC1 .PC2 .SHP .WLD from dos_bench/MARKS/3DBENCH)
set -e
MD=$1; B=$2; OUT=${3:-build-3db}; shift 3 || true
HERE=$(cd "$(dirname "$0")/.." && pwd)
mkdir -p "$OUT"
SRC="$HERE/generated/bb_md_dos2_system.c $MD/src/host/msdos2_boot.c \
     $MD/src/runtime/runtime.c $MD/src/runtime/x86_interp.c $MD/src/runtime/x86_block_cache.c \
     $MD/src/runtime/region.c $MD/src/runtime/exec_router.c $MD/src/runtime/translate.c \
     $MD/src/decode/x86_decode.c \
     $HERE/src/bb_live.c $HERE/tests/bb_3dbench.c $B/src/interp.c $B/src/jit.c $B/src/be_t2.c"
INC="-I$HERE/src -I$B/include -I$MD/include -I$MD/src/runtime -I$MD/src/system -I$MD/src/host"
DEF="-DB86_RAM_FUNCS=1 -DB86_NOW=bb_now_us -DBLITZBUS_LIVE_BACKEND=1 -DMD_THREADED_DISPATCH=1 \
     -DMICRODOS_SYSTEM_ENABLE_AOT=0 -DMICRODOS_SYSTEM_ENABLE_CACHE=0 \
     -DB86_MAXB=2048 -DB86_MAP_BITS=12 -DB86_FAST_BITS=10 -DBB_CODE_BYTES=196608u -DBB_HOT_BYTES=32768u"
arm-linux-gnueabihf-gcc -O2 -static -std=gnu11 -w -mthumb -march=armv7-a+fp $DEF "$@" $INC $SRC -o "$OUT/bb_3dbench"
echo "built $OUT/bb_3dbench"
