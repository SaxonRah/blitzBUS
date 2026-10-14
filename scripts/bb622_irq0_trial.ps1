[CmdletBinding()]
param([ValidateRange(2,45)][int]$TimeoutSeconds=15)
$ErrorActionPreference='Stop'
$root=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$dir=Join-Path $root 'logs'
$req=Join-Path $dir 'bb622-irqtrial.request'
$log=Get-ChildItem -LiteralPath $dir -Filter 'bb-live-*-console.txt' -File |
 Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
if(!$log){throw 'No live raw console log found'}
$age=([datetime]::UtcNow-$log.LastWriteTimeUtc).TotalSeconds
if($age -gt 14){throw "Latest log is stale ($([int]$age)s); start the irqtrial console before requesting"}
if([System.IO.File]::Exists($req)){throw 'Another IRQ0 trial request is pending'}
$start=[System.IO.FileInfo]::new($log.FullName).Length
$tmp=$req+'.new.'+[guid]::NewGuid().ToString('N')
try {
 [System.IO.File]::WriteAllText($tmp,'ARM',[System.Text.Encoding]::ASCII)
 [System.IO.File]::Move($tmp,$req)
} finally {if([System.IO.File]::Exists($tmp)){[System.IO.File]::Delete($tmp)}}
Write-Host 'Requested one-shot guest IRQ0 (one delivery maximum). Waiting for Pico ARM ACK...'
$deadline=[datetime]::UtcNow.AddSeconds($TimeoutSeconds)
$hostSent=$false
while([datetime]::UtcNow -lt $deadline){
 Start-Sleep -Milliseconds 100
 try {
  $f=[System.IO.File]::Open($log.FullName,[System.IO.FileMode]::Open,[System.IO.FileAccess]::Read,[System.IO.FileShare]::ReadWrite)
  try {
   if($f.Length -gt $start){
    [void]$f.Seek($start,[System.IO.SeekOrigin]::Begin)
    $sr=[System.IO.StreamReader]::new($f,[System.Text.Encoding]::UTF8,$true,4096,$true)
    try {$new=$sr.ReadToEnd()} finally {$sr.Dispose()}
    if($new.Contains('[bb622-irqtrial-host] SENT Ctrl+U')){$hostSent=$true}
    if($hostSent -and $new -match '(?m)^\[bb622-irqtrial\] ARMED[^\r\n]*'){
     Write-Host "PICO ACK: $($Matches[0])" -ForegroundColor Green
     Write-Host "Log: $($log.FullName)"
     exit 0
    }
    if($new -match '\[bb622-irqtrial-host\] (ERROR|REJECT)'){
     throw 'Host rejected IRQ0 request; check raw log'
    }
   }
  } finally {$f.Dispose()}
 } catch {if($_.Exception.Message -like 'Host rejected*'){throw}}
}
if([System.IO.File]::Exists($req)){
 try {if([System.IO.File]::ReadAllText($req).Trim() -eq 'ARM') {[System.IO.File]::Delete($req)}}catch{}
}
if($hostSent){throw 'HOST SENT but no Pico ARM ACK; check firmware flashed/serial path'}
throw 'HOST DID NOT SEND; run bb_live_run_dos622_irqtrial.ps1'
