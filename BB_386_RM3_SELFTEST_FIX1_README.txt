blitz86 RM3 — FIX1: Windows selftest line-ending regression
=========================================================

SYMPTOM
  RM3 selftest finishes its probe/apply/verify/restore sequence, then ends
  with AssertionError in its read_bytes() == src.encode('utf8') comparison.
  Production RM3 probe/apply/verify succeeds.

CAUSE
  In the selftest fixture setup, Path.write_text(src) on Windows converts
  LF to CRLF by default. The final assertion compared bytes to the original
  LF-encoded Python string. The production installer uses raw read_bytes()
  and write_bytes() and was not the source of this error.

FIX
  The full bb_386_rm3_v1.py file in this ZIP is identical in behavior
  except for correcting the selftest to use raw bytes and testing both
  LF and CRLF fixtures through full install/verify/restore cycles.
  No installed source files or RM3 backups are changed by this script fix.

INSTALL
  Extract bb_386_rm3_v1.py into C:\blitzBUS and overwrite the previous
  script only. Leave src/ and include/ files untouched.

VERIFY
  cd C:\blitzBUS
  python .\bb_386_rm3_v1.py selftest
  python .\bb_386_rm3_v1.py verify

Expected final lines:
  SELFTEST PASS: anchors, LF/CRLF byte-exact install/verify/restore
  VERIFIED RM3: FS/GS, 32-bit near flow; pre-RM3 byte backups intact

Since your actual RM3 apply and verify already succeeded, do not run apply
again; it is already installed. Next run the RM3 host smoke test and Pico
build in your usual 286/232 KiB configuration.
