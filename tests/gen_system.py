"""Generate the blitzBUS-patched DOS system loop from microDOS's
src/system/md_dos2_system.c (same transformation install_live.py applies)."""
import sys
from pathlib import Path

ANCHOR = '        left = budget - used;'
FASTPATH = ('#if !MICRODOS_SYSTEM_ENABLE_AOT && !MICRODOS_SYSTEM_ENABLE_CACHE && '
            '!defined(MICRODOS_ENABLE_JIT) && !defined(MICRODOS_ENABLE_NATIVE_V2) && '
            '!defined(MICRODOS_ENABLE_NATIVE3)')

def patch(text):
    if text.count(ANCHOR) != 1 or text.count(FASTPATH) != 1:
        raise SystemExit('md_dos2_system.c anchors changed')
    text = text.replace(FASTPATH, FASTPATH + ' && !defined(BLITZBUS_LIVE_BACKEND)', 1)
    text = '#include "bb_live.h"\n' + text
    return text.replace(ANCHOR, ANCHOR + '\n        if (bb_live_try(rt, left)) continue;', 1)

if __name__ == '__main__':
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    dst.write_text(patch(src.read_text(encoding='utf8')), encoding='utf8')
