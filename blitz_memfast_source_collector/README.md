# blitzBUS / blitz86 memory fast-path source collector

This script is READ ONLY. It gathers your actual emitter, runtime mapping headers, integration code, and hashes into a ZIP. It does not alter your build, JIT, LCD, or backups. It includes local source files; review ZIP contents before sharing if there is proprietary code.

In PowerShell:

```powershell
cd C:\blitzBUS
Expand-Archive "$HOME\Downloads\blitz_memfast_source_collector.zip" C:\blitzBUS -Force
.\blitz_memfast_source_collector\collect_memfast_sources.ps1
```

Upload `C:\blitzBUS\logs\memfast_source_snapshot.zip` for generation of a full, revision-matched guarded fast-path implementation. The follow-up must preserve guest 20-bit and segment-offset wrapping, page mapping, writes to A000/BBUF/VRAM, dirty-code tracking, and invalidation on self-modifying code. Baseline and fast-path must be benchmarked A/B with a feature toggle.
