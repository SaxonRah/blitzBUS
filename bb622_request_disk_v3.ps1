[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidateSet('A','B')][string]$Drive,
    [Parameter(Mandatory=$true)][ValidateRange(1,9)][int]$Disk,
    [int]$TimeoutSeconds=20
)
$ErrorActionPreference='Stop'
if ($Drive -eq 'B' -and $Disk -gt 5) { throw 'B: has only DESCENT1.IMG through DESCENT5.IMG' }
$root=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$dir=Join-Path $root 'logs'
$sessionPath=Join-Path $dir 'bb622-swap.session.json'
$statusPath=Join-Path $dir 'bb622-swap.status.json'
$target=Join-Path $dir 'bb622-swap.request'
function Get-JsonFile([string]$path) {
    try { return [System.IO.File]::ReadAllText($path) | ConvertFrom-Json } catch { return $null }
}
$session=Get-JsonFile $sessionPath
if (!$session) { throw "No active ACK V3 console. Start bb_live_run_dos622_controls_v3.ps1 before requesting disks." }
$lag=([datetime]::UtcNow-[datetime]::Parse($session.lastUtc).ToUniversalTime()).TotalSeconds
if ($lag -gt 4 -or $lag -lt -2) { throw "Console heartbeat is stale ($([Math]::Round($lag,1)) s). The runner is not accepting requests." }
try { $proc=Get-Process -Id ([int]$session.pid) -ErrorAction Stop } catch { throw "Host PID $($session.pid) is not running. Start the ACK V3 console." }
if ([System.IO.File]::Exists($target)) { throw "An earlier request is still pending: $target" }
$id=[Guid]::NewGuid().ToString('N').ToUpperInvariant()
$diskId=($Drive+$Disk)
$payload="$diskId|$id"
$temp=$target+'.tmp.'+$id
try {
    [System.IO.File]::WriteAllText($temp,$payload,[System.Text.Encoding]::ASCII)
    [System.IO.File]::Move($temp,$target)
} finally { if ([System.IO.File]::Exists($temp)) { [System.IO.File]::Delete($temp) } }
Write-Host "[$diskId] Request queued; waiting for Pico firmware ACK (ID=$id)..."
$until=[datetime]::UtcNow.AddSeconds($TimeoutSeconds)
$seenSent=$false
while ([datetime]::UtcNow -lt $until) {
    Start-Sleep -Milliseconds 150
    $s=Get-JsonFile $statusPath
    if ($s -and $s.session -eq $session.session -and $s.request -eq $id) {
        if ($s.state -eq 'SENT' -and !$seenSent) {
            Write-Host "[$diskId] Sent over COM5, waiting for Pico to mount image..."
            $seenSent=$true
        }
        if ($s.state -eq 'OK') {
            Write-Host "[$diskId] FIRMWARE ACK: OK — $($s.detail)" -ForegroundColor Green
            Write-Host 'You may now press Enter in the DOS installer.'
            exit 0
        }
        if ($s.state -in @('FAIL','REJECTED','HOST_ERROR','NO_ACK')) {
            Write-Host "[$diskId] $($s.state): $($s.detail)" -ForegroundColor Red
            Write-Host 'Do NOT press Enter. Check filenames/images and raw Pico log.'
            exit 2
        }
    }
    $live=Get-JsonFile $sessionPath
    if (!$live -or $live.session -ne $session.session) {
        Write-Error 'Main runner restarted or stopped while the request was pending.'
        exit 3
    }
    if (([datetime]::UtcNow-[datetime]::Parse($live.lastUtc).ToUniversalTime()).TotalSeconds -gt 4) {
        Write-Error 'Main console heartbeat stopped. The request could not be confirmed.'
        exit 3
    }
}
Write-Host "[$diskId] NO CONFIRMATION within $TimeoutSeconds seconds; do NOT press Enter." -ForegroundColor Red
Write-Host "Raw log: $($session.transcript)"
exit 4
