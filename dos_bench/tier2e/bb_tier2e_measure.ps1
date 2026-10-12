[CmdletBinding()]
param([string]$Port='COM5',[int]$TimeoutSeconds=120)
$ErrorActionPreference='Stop'
# Run AFTER exiting bb_live_run.ps1 with Ctrl+X, while DOS is still at A>.
$serial=[System.IO.Ports.SerialPort]::new($Port,115200,[System.IO.Ports.Parity]::None,8,[System.IO.Ports.StopBits]::One)
$serial.DtrEnable=$true
$serial.RtsEnable=$false
$serial.ReadTimeout=100
$watch=[System.Diagnostics.Stopwatch]::StartNew()
$all='';$start=$null;$end=$null
try {
    $serial.Open()
    Start-Sleep -Milliseconds 150
    [void]$serial.ReadExisting()
    $serial.Write("T2ECPU`r")
    $deadline=(Get-Date).AddSeconds($TimeoutSeconds)
    while((Get-Date) -lt $deadline) {
        $chunk=$serial.ReadExisting()
        if($chunk) {
            $all+=$chunk
            Write-Host -NoNewline $chunk
            # Arrival time of first complete marker (host-side; CDC latency included)
            if($null -eq $start -and $all.Contains('T2E START')){$start=$watch.Elapsed.TotalMilliseconds}
            if($null -eq $end -and $all.Contains('T2E END')){$end=$watch.Elapsed.TotalMilliseconds;break}
            if($all.Length -gt 200000){throw 'Too much console output; no END marker'}
        }
        Start-Sleep -Milliseconds 2
    }
    Write-Host ''
    if($null -eq $start -or $null -eq $end){throw 'Benchmark did not complete before timeout; check serial capture. No timing claimed.'}
    $match=[regex]::Match($all,'T2E CHECKSUM=([0-9A-Fa-f]{4})')
    if(!$match.Success){throw 'Missing checksum; no timing claimed.'}
    $actual=$match.Groups[1].Value.ToUpperInvariant()
    if($actual -ne '8642'){throw "CHECKSUM FAILURE expected=8642 actual=$actual. Do not trust performance."}
    $ms=$end-$start
    Write-Host ("PASS: checksum={0}  iterations=8388608  host_elapsed_ms={1:N3}  iterations_per_s={2:N0}" -f $actual,$ms,(8388608.0/($ms/1000.0)))
    Write-Host 'NOTE: This is Windows host USB-serial marker timing, not RP2350 time_us_64().'
} finally {
    if($serial.IsOpen){$serial.Close()}
    $serial.Dispose()
}
