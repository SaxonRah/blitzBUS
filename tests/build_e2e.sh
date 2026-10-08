#!/bin/sh
# Host/qemu end-to-end build of the blitzBUS live backend.
#   tests/build_e2e.sh MICRODOS BLITZ86 OUTDIR
# Produces OUTDIR/bb_dos_e2e_{t2,a64}; run under qemu-arm / qemu-aarch64.
set -e
MD=$1; B=$2; OUT=${3:-build-e2e}
HERE=$(cd "$(dirname "$0")/.." && pwd)
mkdir -p "$OUT"
python3 "$HERE/tests/gen_system.py" "$MD/src/system/md_dos2_system.c" "$OUT/bb_md_dos2_system.c"
SRC="$OUT/bb_md_dos2_system.c $MD/src/host/msdos2_boot.c \
     $MD/src/runtime/runtime.c $MD/src/runtime/x86_interp.c $MD/src/runtime/x86_block_cache.c \
     $MD/src/runtime/region.c $MD/src/runtime/exec_router.c $MD/src/runtime/translate.c \
     $MD/src/decode/x86_decode.c \
     $HERE/src/bb_live.c $HERE/tests/bb_dos_e2e.c $B/src/interp.c $B/src/jit.c"
INC="-I$HERE/src -I$B/include -I$MD/include -I$MD/src/runtime -I$MD/src/system -I$MD/src/host"
DEF="-DBLITZBUS_LIVE_BACKEND=1 -DMD_THREADED_DISPATCH=1 -DMICRODOS_SYSTEM_ENABLE_AOT=0 -DMICRODOS_SYSTEM_ENABLE_CACHE=0"
FL="-O2 -static -std=gnu11 -w"
arm-linux-gnueabihf-gcc $FL -mthumb -march=armv7-a+fp $DEF -DB86_MAXB=2048 -DB86_MAP_BITS=12 -DB86_FAST_BITS=10 \
    $INC $SRC $B/src/be_t2.c -o "$OUT/bb_dos_e2e_t2"
aarch64-linux-gnu-gcc $FL $DEF $INC $SRC $B/src/be_a64.c -o "$OUT/bb_dos_e2e_a64"
echo "built $OUT/bb_dos_e2e_t2 $OUT/bb_dos_e2e_a64"
