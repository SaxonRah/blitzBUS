[CmdletBinding()]
param(
  [ValidateSet('Run1ms','Run2ms','Compare','Restore')]
  [string]$Mode = 'Compare',
  [string]$Log1ms = '',
  [string]$Log2ms = '',
  [string]$BlitzBUS = 'C:\blitzBUS',
  [string]$MicroDOS = 'C:\microDOS',
  [string]$Blitz86 = 'C:\blitz86_v2',
  [string]$Port = 'COM5',
  [int]$Seconds = 180
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = (Resolve-Path -LiteralPath $BlitzBUS).Path
$logs = Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$source = Join-Path $root 'src\bb_live.c'
$backup = "$source.tier1-original"
$runner = Join-Path $root 'scripts\bb_live_run.ps1'

function Set-Slice([int]$slice, [int]$dispatch) {
  if (!(Test-Path -LiteralPath $backup)) { throw "Missing original Tier 1 backup: $backup" }
  $original = [System.IO.File]::ReadAllText($backup)
  foreach ($definition in @('BB_SLICE_US','BB_SLICE_DISPATCH')) {
    $rx = "(?m)^(#define\s+$definition\s+)(\d+)(u?)(\s*(?://[^\r\n]*)?)$"
    if ([regex]::Matches($original,$rx).Count -ne 1) {
       throw "Expected one $definition in saved original; refusing changes."
    }
  }
  $t = [regex]::Replace($original,'(?m)^(#define\s+BB_SLICE_US\s+)\d+u?',('${1}'+$slice),'None')
  $t = [regex]::Replace($t,'(?m)^(#define\s+BB_SLICE_DISPATCH\s+)\d+u?',('${1}'+$dispatch+'u'),'None')
  [System.IO.File]::WriteAllText($source,$t,[System.Text.UTF8Encoding]::new($false))
  Write-Host "Applied slice=${slice}us and dispatch=$dispatch, based on saved original."
}
function Run-Config([int]$slice, [int]$dispatch) {
  if (!(Test-Path -LiteralPath $runner)) { throw "Missing live runner: $runner" }
  Set-Slice $slice $dispatch
  # Preserve the performance configuration the user actually benchmarked.
  $env:BB_LCD_PERI_HZ='150000000'
  $env:BB_LCD_SPI_HZ='75000000'
  $env:BB_LCD_LACE='1'
  $env:BB_BBUF='0'
  $env:BB_CODE_KB='292'
  $env:BB_HOT_THRESHOLD='32'
  $before=@(Get-ChildItem -LiteralPath $logs -Filter 'bb-live-*-console.txt' -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName)
  Write-Host 'At A> run 3DBENCH. After the measured run, press Ctrl+] twice at least 8 s apart.'
  Write-Host 'Then Ctrl+X to close. Record benchmark FPS manually. Do not compare pre-warmup report intervals.'
  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $runner -MicroDOS $MicroDOS -Blitz86 $Blitz86 -Port $Port -Seconds $Seconds
  if ($LASTEXITCODE -ne 0) { throw "Runner exited with $LASTEXITCODE" }
  $newest=Get-ChildItem -LiteralPath $logs -Filter 'bb-live-*-console.txt' |
    Where-Object { $before -notcontains $_.FullName } | Sort-Object LastWriteTime -Descending | Select-Object -First 1
  if ($null -eq $newest) { throw 'Cannot identify new console log.' }
  $dst=Join-Path $logs "tier1f-${slice}us-console.txt"
  Copy-Item -LiteralPath $newest.FullName -Destination $dst -Force
  Write-Host "Comparison log: $dst"
}
function Parse-Log([string]$path) {
  if (!(Test-Path -LiteralPath $path)) { throw "Missing console log: $path" }
  $s=[System.IO.File]::ReadAllText((Resolve-Path -LiteralPath $path).Path)
  $pattern='(?m)^\[bb-v24\] PROFILE wall-ms=(\d+)[^\r\n]*?jit-insns=(\d+)[^\r\n]*\r?\n(?:(?!\[bb-v24\] PROFILE)[\s\S])*?\[bb-v36-irq-summary\] edges=(\d+) delivered=(\d+) coalesced=(\d+)'
  $matches=[regex]::Matches($s,$pattern)
  if ($matches.Count -lt 2) { throw "$path has fewer than two complete paired performance/IRQ reports. Capture Ctrl+] twice during benchmark." }
  $snap=@()
  foreach ($m in $matches) {
    $snap += [pscustomobject]@{
      WallMs=[double]$m.Groups[1].Value
      Instructions=[double]$m.Groups[2].Value
      Edges=[double]$m.Groups[3].Value
      Delivered=[double]$m.Groups[4].Value
      Coalesced=[double]$m.Groups[5].Value
    }
  }
  $rows=@()
  for ($i=1;$i -lt $snap.Count;$i++) {
    $a=$snap[$i-1];$b=$snap[$i]
    $dt=($b.WallMs-$a.WallMs)/1000.0
    if ($dt -lt 3) { continue }
    $e=$b.Edges-$a.Edges
    $d=$b.Delivered-$a.Delivered
    $c=$b.Coalesced-$a.Coalesced
    $instr=$b.Instructions-$a.Instructions
    if ($e -lt 0 -or $d -lt 0 -or $instr -lt 0) { continue }
    $rows += [pscustomobject]@{
      Log=[IO.Path]::GetFileName($path)
      FromSecond=[math]::Round($a.WallMs/1000,2)
      ToSecond=[math]::Round($b.WallMs/1000,2)
      SpanSec=[math]::Round($dt,3)
      IRQEdgesPerSec=[math]::Round($e/$dt,2)
      IRQDeliveredPerSec=[math]::Round($d/$dt,2)
      IRQCoalescedPct=$(if($e -gt 0){[math]::Round(100*$c/$e,2)}else{0})
      GuestMIPS=[math]::Round($instr/$dt/1e6,3)
    }
  }
  if (!$rows) { throw "No intervals longer than 3 s in $path" }
  return $rows
}
switch($Mode) {
  'Run1ms' { Run-Config 1000 4096 }
  'Run2ms' { Run-Config 2000 4096 }
  'Restore' {
     if (!(Test-Path -LiteralPath $backup)) { throw "Missing $backup" }
     Copy-Item -LiteralPath $backup -Destination $source -Force
     Write-Host "Restored original source only: $source (not built/flashed)"
  }
  'Compare' {
    if (!$Log1ms) { $Log1ms=Join-Path $logs 'tier1f-1000us-console.txt' }
    if (!$Log2ms) { $Log2ms=Join-Path $logs 'tier1f-2000us-console.txt' }
    $rows=@(Parse-Log $Log1ms) + @(Parse-Log $Log2ms)
    $out=Join-Path $logs ("tier1f-compare-"+(Get-Date -Format 'yyyyMMdd-HHmmss')+".csv")
    $rows | Export-Csv -NoTypeInformation -Encoding UTF8 -Path $out
    $rows | Format-Table -AutoSize
    Write-Host "CSV: $out"
    Write-Host 'IMPORTANT: This compares guest throughput/IRQ counts, not FPS correctness. Check benchmark wall-time independently.'
  }
}
