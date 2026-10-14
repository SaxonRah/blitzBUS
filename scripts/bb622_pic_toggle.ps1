[CmdletBinding()]
param([ValidateRange(2,60)][int]$TimeoutSeconds=15)
$ErrorActionPreference='Stop'
$root=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$dir=Join-Path $root 'logs'
$req=Join-Path $dir 'bb622-picprobe.request'
if ([System.IO.File]::Exists($req)) {throw "PIC control request already pending: $req"}
$source=Join-Path $root 'src\bb_live.c'
if(!(Test-Path -LiteralPath $source)) {throw 'Missing firmware source'}
if(-not ([System.IO.File]::ReadAllText($source).Contains('BB622_PIC_PENDING_V1'))) {
    throw 'PIC pending firmware patch is NOT installed in source. Install and flash it first.'
}
$log=Get-ChildItem -LiteralPath $dir -Filter 'bb-live-*-console.txt' -File |
 Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
if(!$log) {throw 'No raw console capture found; run the PIC-control console first'}
$start=[System.IO.FileInfo]::new($log.FullName).Length
$age=([datetime]::UtcNow-$log.LastWriteTimeUtc).TotalSeconds
if($age -gt 12) {Write-Warning "Newest raw log was last updated $([int]$age)s ago. Confirm the PIC-control runner is open."}
$tmp=$req+'.new.'+[guid]::NewGuid().ToString('N')
try {
 [System.IO.File]::WriteAllText($tmp,'Y',[System.Text.Encoding]::ASCII)
 [System.IO.File]::Move($tmp,$req)
} finally { if([System.IO.File]::Exists($tmp)){[System.IO.File]::Delete($tmp)} }
Write-Host 'Requested PIC Ctrl+Y toggle. Waiting for host SENT and Pico ACK...'
$deadline=[datetime]::UtcNow.AddSeconds($TimeoutSeconds)
$hostSent=$false
while([datetime]::UtcNow -lt $deadline) {
 Start-Sleep -Milliseconds 120
 try {
  $f=[System.IO.File]::Open($log.FullName,[System.IO.FileMode]::Open,[System.IO.FileAccess]::Read,[System.IO.FileShare]::ReadWrite)
  try {
   if($f.Length -gt $start){
    [void]$f.Seek($start,[System.IO.SeekOrigin]::Begin)
    $r=[System.IO.StreamReader]::new($f,[System.Text.Encoding]::UTF8,$true,4096,$true)
    try { $new=$r.ReadToEnd() } finally { $r.Dispose() }
    if($new.Contains('[bb622-piccontrol] SENT Ctrl+Y')){$hostSent=$true}
    if($new -match '(?m)^\[bb622-picprobe\] Ctrl\+Y (ON|OFF) pending-only[^\r\n]*') {
     Write-Host "PICO ACK: $($Matches[0])" -ForegroundColor Green
     exit 0
    }
    if($new.Contains('[bb622-piccontrol] REJECT') -or $new.Contains('[bb622-piccontrol] ERROR')) {
     Write-Host 'HOST ERROR processing request; check raw log' -ForegroundColor Red
     exit 2
    }
   }
  } finally {$f.Dispose()}
 } catch { }
}
# Prevent stale future toggles if main runner wasn't alive.
if([System.IO.File]::Exists($req)){
 try { if([System.IO.File]::ReadAllText($req).Trim() -eq 'Y') {[System.IO.File]::Delete($req)} } catch {}
}
if($hostSent) {Write-Host 'HOST SENT but PICO NO ACK. Firmware may be old, Ctrl+Y unhandled, or serial output missing.' -ForegroundColor Red}
else {Write-Host 'HOST DID NOT SEND. Wrong runner/no live runner/request polling not active.' -ForegroundColor Red}
Write-Host "Raw log: $($log.FullName)"
exit 3
