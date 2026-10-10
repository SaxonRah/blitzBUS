# Resolve the [bb-v49f-rawpc] samples of a console log to firmware functions.
#   .\scripts\bb_pc_report.ps1                       (newest console log)
#   .\scripts\bb_pc_report.ps1 -Log logs\bb-live-...-console.txt
# Only samples after the benchmark starts are counted (the "[bb-v40-paged] bbuf"
# line); -All counts the whole log. PCs past the last firmware symbol are JIT code.
param(
    [switch]$All,
    [string]$Log = "",
    [string]$Elf = "C:\microDOS\build-pico\out\blitzbus_pico_b86_dos.elf",
    [string]$Addr2line = "C:\Users\Jupiter\.pico-sdk\toolchain\15_2_Rel1\bin\arm-none-eabi-addr2line.exe",
    [int]$Top = 25
)
$ErrorActionPreference = "Stop"
if (-not $Log) {
    $Log = (Get-ChildItem -Path (Join-Path $PSScriptRoot "..\logs") -Filter "bb-live-*-console.txt" |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
}
Write-Host "log: $Log"
$counts = @{}
$v52 = @{}; $jit52 = 0
$on = [bool]$All
foreach ($line in Get-Content $Log) {
    if (-not $on) { if ($line -match '\[bb-v40-paged\] bbuf') { $on = $true }; continue }
    if ($line -match '^\[bb-v52-pcs\](.*)$') {
        foreach ($t in ($Matches[1].Trim() -split '\s+')) { if ($t) { if ($v52.ContainsKey($t)) { $v52[$t] += 1 } else { $v52[$t] = 1 } } }
        continue
    }
    if ($line -match '^\[bb-v52-jit\] samples=(\d+)') { $jit52 += [int]$Matches[1]; continue }
    if ($line -match '\[bb-v49f-rawpc\] pc=([0-9A-Fa-f]{8}) region=\S+ count=(\d+)') {
        $pc = $Matches[1].ToUpper(); $n = [int]$Matches[2]
        if ($counts.ContainsKey($pc)) { $counts[$pc] += $n } else { $counts[$pc] = $n }
    }
}
if ($v52.Count -gt 0 -or $jit52 -gt 0) { $counts = $v52 }    # v52: every sample (preferred)
if ($counts.Count -eq 0 -and $jit52 -eq 0) { Write-Host "no PC samples in the log"; exit 1 }
$pcs = @($counts.Keys)
$byFunc = @{}; $total = 0
if ($jit52 -gt 0) { $byFunc["(JIT code)"] = $jit52; $total = $jit52 }
$out = @()
if ($pcs.Count -gt 0) { $out = @(& $Addr2line -f -e $Elf ($pcs | ForEach-Object { "0x$_" })) }
for ($i = 0; $i -lt $pcs.Count; $i++) {
    $fn = $out[2 * $i]
    if ($fn -eq "??" -or $fn -eq "__tbss_end" -or $fn -eq "end" -or $fn -eq "__end__" -or $fn -eq "__bss_end__") { $fn = "(JIT code)" }
    $n = $counts[$pcs[$i]]; $total += $n
    if ($byFunc.ContainsKey($fn)) { $byFunc[$fn] += $n } else { $byFunc[$fn] = $n }
}
Write-Host ("samples: {0}  distinct PCs: {1}" -f $total, $pcs.Count)
$byFunc.GetEnumerator() | Sort-Object Value -Descending | Select-Object -First $Top |
    ForEach-Object { "{0,-34} {1,6} {2,6:N1}%" -f $_.Key, $_.Value, (100.0 * $_.Value / $total) }
