[CmdletBinding()]
param(
 [ValidateSet('irqprofile','xip','ring','all','restore','status')]
 [string]$Mode='status',
 [switch]$Run,
 [string]$Root='C:\blitzBUS',
 [string]$MicroDOS='C:\microDOS',
 [string]$Blitz86='C:\blitz86_v2',
 [string]$Port='COM5',
 [int]$Seconds=180
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$src=Join-Path $Root 'src\bb_live.c'
$irq=Join-Path $Root 'src\bb_irq.h'
$runner=Join-Path $Root 'scripts\bb_live_run.ps1'
$backupDir=Join-Path $Root 'tier1g-originals'
$utf8=New-Object System.Text.UTF8Encoding($false)
function Read-Text([string]$p) { return [IO.File]::ReadAllText($p) }
function Write-Text([string]$p,[string]$v) { [IO.File]::WriteAllText($p,$v,$utf8) }
function Replace-Once([string]$s,[string]$before,[string]$after,[string]$why) {
 $i=$s.IndexOf($before,[StringComparison]::Ordinal)
 if($i -lt 0 -or $s.IndexOf($before,$i+$before.Length,[StringComparison]::Ordinal) -ge 0) {
  throw "[$why] expected exactly one source anchor; no source files changed"
 }
 return $s.Substring(0,$i)+$after+$s.Substring($i+$before.Length)
}
function Extract-Function([string]$s,[string]$signature) {
 $start=$s.IndexOf($signature,[StringComparison]::Ordinal)
 if($start -lt 0 -or $s.IndexOf($signature,$start+$signature.Length,[StringComparison]::Ordinal) -ge 0){throw "Function signature missing/ambiguous: $signature"}
 $opening=$s.IndexOf('{',$start);if($opening -lt 0){throw "No brace: $signature"}
 $depth=0
 for($i=$opening;$i -lt $s.Length;$i++){
  if($s[$i] -eq '{'){$depth++}elseif($s[$i] -eq '}'){$depth--;if(!$depth){return $s.Substring($start,$i-$start+1)}}
 }
 throw "Unbalanced function: $signature"
}
if($Mode -ne 'status' -and $Mode -ne 'restore' -and !(Test-Path $irq)){throw "Missing $irq"}
if(!(Test-Path $src)){throw "Missing $src"}
if($Mode -eq 'status'){
 Write-Host "Tier1G status: $Root"
 foreach($p in @($src,$irq)) {if(Test-Path $p){Write-Host "$p SHA256 $((Get-FileHash $p -Algorithm SHA256).Hash)"}}
 Write-Host "Backup directory: $backupDir"
 if(Test-Path $backupDir){Get-ChildItem $backupDir | Select-Object Name,Length | Format-Table}
 return
}
if($Mode -eq 'restore') {
 foreach($name in @('bb_live.c','bb_irq.h')){
  $saved=Join-Path $backupDir $name
  if(!(Test-Path $saved)){throw "Missing saved source: $saved"}
 }
 Copy-Item (Join-Path $backupDir 'bb_live.c') $src -Force
 Copy-Item (Join-Path $backupDir 'bb_irq.h') $irq -Force
 Write-Host 'Original pre-Tier1G source restored. No build/flash unless -Run.'
} else {
 New-Item -Path $backupDir -ItemType Directory -Force | Out-Null
 $originalLive=Join-Path $backupDir 'bb_live.c'
 $originalIrq=Join-Path $backupDir 'bb_irq.h'
 if(!(Test-Path $originalLive)){Copy-Item $src $originalLive}
 if(!(Test-Path $originalIrq)){Copy-Item $irq $originalIrq}
 $live=Read-Text $originalLive
 $irqText=Read-Text $originalIrq
 # Use the 1 ms, 4096 budget reference irrespective of prior experiment.
 foreach($spec in @(@('BB_SLICE_US','1000'),@('BB_SLICE_DISPATCH','4096u'))){
  $pattern='(?m)^(#define[ \t]+'+$spec[0]+'[ \t]+)[0-9]+u?'
  if([regex]::Matches($live,$pattern).Count -ne 1){throw "Expected one definition $($spec[0]); no source changes"}
  $live=[regex]::Replace($live,$pattern,('${1}'+$spec[1]))
 }
 if($Mode -eq 'irqprofile' -or $Mode -eq 'all') {
  # Leave PIC/PIT scheduling and guest-visible state unchanged. Remove only diagnostic timings.
  $sig1='static void bb_v37_poll_begin(void)'
  $sig2='static void bb_v37_poll_end(void)'
  $sig3='static void bb_v37_record_eoi(void)'
  $f1=Extract-Function $irqText $sig1
  $f2=Extract-Function $irqText $sig2
  $f3=Extract-Function $irqText $sig3
  $irqText=Replace-Once $irqText $f1 'static void bb_v37_poll_begin(void) {}' 'IRQ poll begin'
  $irqText=Replace-Once $irqText $f2 'static void bb_v37_poll_end(void) {}' 'IRQ poll end'
  $irqText=Replace-Once $irqText $f3 'static void bb_v37_record_eoi(void) {}' 'IRQ EOI profiler'
 }
 if($Mode -eq 'xip' -or $Mode -eq 'all'){
  $live=Replace-Once $live 'uint64_t m1 = bb_xip_misses();' 'uint64_t m1 = 0; /* Tier1G: hot-path XIP diagnostic disabled */' 'XIP baseline'
  $live=Replace-Once $live 'st.native_misses += bb_xip_misses() - m1;' '/* Tier1G: native-miss diagnostic suspended; totals not meaningful */' 'XIP delta'
 }
 if($Mode -eq 'ring' -or $Mode -eq 'all'){
  # Record only on abnormal exits; preserve checks and watchdog fault information.
  $before='if(bb_video_seen)bb_v7_record(2,'
  $after='if(bb_video_seen && (failed || bb_v17_stopped))bb_v7_record(2,'
  $live=Replace-Once $live $before $after 'ring enter'
  $before='if(bb_video_seen)bb_v7_record(3,'
  $after='if(bb_video_seen && (failed || bb_v17_stopped))bb_v7_record(3,'
  $live=Replace-Once $live $before $after 'ring leave'
  # Hook-side recordings are intentionally untouched: they may be needed for fault diagnosis.
 }
 # Only write when all validation has succeeded; create exact candidates and then replace.
 $tmpLive=Join-Path $backupDir 'candidate_bb_live.c'
 $tmpIrq=Join-Path $backupDir 'candidate_bb_irq.h'
 Write-Text $tmpLive $live
 Write-Text $tmpIrq $irqText
 Copy-Item $tmpLive $src -Force
 Copy-Item $tmpIrq $irq -Force
 Write-Host "Applied Tier1G mode $Mode (1 ms / 4096 dispatch)."
}
if($Run){
 if(!(Test-Path $runner)){throw "Missing runner: $runner"}
 $env:BB_LCD_PERI_HZ='150000000';$env:BB_LCD_SPI_HZ='75000000';$env:BB_LCD_LACE='1'
 $env:BB_BBUF='0';$env:BB_CODE_KB='292';$env:BB_HOT_THRESHOLD='32'
 Write-Host 'Starting live build/flash/console. Run 3DBENCH and record FPS. Press Ctrl+] for counters, Ctrl+X to exit.'
 & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $runner -MicroDOS $MicroDOS -Blitz86 $Blitz86 -Port $Port -Seconds $Seconds
 if($LASTEXITCODE -ne 0){throw "Live runner failed ($LASTEXITCODE)"}
}
