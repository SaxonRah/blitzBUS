[CmdletBinding()]
param(
 [Parameter(Mandatory=$true)][ValidateSet('A','B')][string]$Drive,
 [Parameter(Mandatory=$true)][ValidateRange(0,9)][int]$Disk,
 [ValidateRange(1,120)][int]$TimeoutSeconds=20
)
$ErrorActionPreference='Stop'
if($Drive -eq 'B' -and $Disk -gt 5){throw 'B disks are 0 (eject) or 1..5'}
$root=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$logDir=Join-Path $root 'logs'
$target=Join-Path $logDir 'bb622-swap.request'
if(Test-Path -LiteralPath $target){throw "Previous request pending: $target"}
$log=Get-ChildItem -LiteralPath $logDir -Filter 'bb-live-*-console.txt' -File |
     Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
if(!$log){throw 'No live Pico capture log. Start the new DOS622 boot/eject console first.'}
if(([datetime]::UtcNow-$log.LastWriteTimeUtc).TotalSeconds -gt 20){
 Write-Warning "Console log has no recent output; cannot confirm runner is still active until an ACK arrives."
}
$initial=[System.IO.FileInfo]::new($log.FullName).Length
$command=$Drive+[string]$Disk
$temp=$target+'.new.'+[guid]::NewGuid().ToString('N')
try{
 [System.IO.File]::WriteAllText($temp,$command,[System.Text.Encoding]::ASCII)
 [System.IO.File]::Move($temp,$target)
}finally{if(Test-Path -LiteralPath $temp){Remove-Item -LiteralPath $temp -Force}}
Write-Host "Submitted $command; waiting for Pico's [bb622-swap] response..."
$deadline=[datetime]::UtcNow.AddSeconds($TimeoutSeconds)
$escaped=[regex]::Escape($Drive+':'+[string]$Disk)
while([datetime]::UtcNow -lt $deadline){
 Start-Sleep -Milliseconds 200
 try {
  $file=[System.IO.File]::Open($log.FullName,[System.IO.FileMode]::Open,[System.IO.FileAccess]::Read,[System.IO.FileShare]::ReadWrite)
  try {
   if($file.Length -gt $initial){
    [void]$file.Seek($initial,[System.IO.SeekOrigin]::Begin)
    $reader=[System.IO.StreamReader]::new($file,[System.Text.Encoding]::UTF8,$true,4096,$true)
    try {$newLog=$reader.ReadToEnd()} finally {$reader.Dispose()}
    if($newLog -match "(?m)^\[bb622-swap\] $escaped OK\b") {
      Write-Host "PICO CONFIRMED OK: $command" -ForegroundColor Green
      exit 0
    }
    if($newLog -match "(?m)^\[bb622-swap\] $escaped FAIL\b") {
      Write-Host "PICO REJECTED: $command (see raw log)" -ForegroundColor Red
      exit 2
    }
   }
  } finally {$file.Dispose()}
 } catch {[void]0} # A writer may briefly lock the log; retry without losing the request.
}
Write-Host "NO FIRMWARE ACK after $TimeoutSeconds seconds. Do not continue DOS Setup." -ForegroundColor Red
if(Test-Path -LiteralPath $target){
 try {
  if([System.IO.File]::ReadAllText($target).Trim() -eq $command){
   Remove-Item -LiteralPath $target -Force
   Write-Host 'Unconsumed request cleaned up to prevent a stale swap later.'
  }
 } catch {Write-Warning "Could not clean request: $_"}
}
Write-Host "Raw log: $($log.FullName)"
exit 3
