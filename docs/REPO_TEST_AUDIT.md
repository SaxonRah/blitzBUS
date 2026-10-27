# Host test and smoke-file reference audit

A **literal-reference scan** of tracked text files. A file with zero found references is NOT proven unused; CMake, wildcards, command-line arguments or manual build scripts may load it indirectly.

| Test source | Files referring to its exact filename |
| --- | --- |
| `RCXTEST.asm` | `RCX_MEM1_README.txt`, `build_rcxtest.py` |
| `bb_386_pm0_smoke.c` | `BLITZ86_386_PM0_README.md`, `bb_386_pm0_v1.py`, `milestones/RM3_62_5/bb_386_pm0_v1.py` |
| `bb_386_rm0_smoke.c` | `BLITZ86_386_RM0_README.md`, `BLITZ86_386_RM1_README.md`, `BLITZ86_386_RM2_README.md`, `bb_386_rm0_v1.py`, `bb_386_rm1_v1.py`, `milestones/RM3_62_5/bb_386_rm0_v1.py` |
| `bb_386_rm1_smoke.c` | `BLITZ86_386_RM1_README.md`, `BLITZ86_386_RM2_README.md`, `bb_386_rm1_v1.py`, `milestones/RM3_62_5/bb_386_rm1_v1.py`, `milestones/RM3_62_5/blitz86_sources/tests/bb_386_rm1_smoke.c` |
| `bb_386_rm2_smoke.c` | `BLITZ86_386_RM2_README.md`, `bb_386_rm2_v1.py`, `milestones/RM3_62_5/bb_386_rm2_v1.py` |
| `bb_386_rm3_smoke.c` | `BLITZ86_386_RM3_README.md`, `bb_386_rm3_v1.py`, `milestones/RM3_62_5/bb_386_rm3_v1.py`, `milestones/RM3_62_5/blitz86_sources/tests/bb_386_rm3_smoke.c` |
| `bb_hdd_host_test.c` | No literal references found (not proof of disuse) |
| `test_hdd_v2.c` | `bb_dos622_hdd_v2.py` |
| `test_host_bios.c` | No literal references found (not proof of disuse) |
| `test_host_sd.c` | No literal references found (not proof of disuse) |
| `test_irq0_ab.c` | No literal references found (not proof of disuse) |
| `test_printer17.c` | No literal references found (not proof of disuse) |
| `test_psram.c` | No literal references found (not proof of disuse) |
| `test_rtc1a.c` | No literal references found (not proof of disuse) |
| `test_sd_clockfix.c` | No literal references found (not proof of disuse) |
| `test_serial14.c` | No literal references found (not proof of disuse) |
| `test_textio.c` | No literal references found (not proof of disuse) |
| `test_watch.c` | No literal references found (not proof of disuse) |
| `trpool_test.c` | No literal references found (not proof of disuse) |

Do not delete these tests without compiling their hosts and checking the build/test commands. All test source files remain in place in phase 2.

