[CmdletBinding()]
param(
    [string]$Port='COM5',
    [int]$RunsPerPhase=3,
    [int]$TimeoutSeconds=45,
    [string]$LogDirectory='C:\blitzBUS\logs'
)
$ErrorActionPreference='Stop'
# Run with Pico powered, DOS at A>, and bb_live_run.ps1 closed (Ctrl+X).
# Important: Ctrl+P in blitzBUS only gets processed once VGA mode was entered.
# T2CVGA is run first to establish that state, then tests are done in DOS text mode.
# The LCD presenter may be idle in text mode, so these data cannot settle contention
# during active 3DBENCH VGA rendering.
$serial=[System.IO.Ports.SerialPort]::new($Port,115200,[System.IO.Ports.Parity]::None,8,[System.IO.Ports.StopBits]::One)
$serial.DtrEnable=$true; $serial.RtsEnable=$false; $serial.ReadTimeout=100
$sw=[System.Diagnostics.Stopwatch]::StartNew()
$all=[System.Text.StringBuilder]::new()
$rows=[System.Collections.Generic.List[object]]::new()
$sequence=@('ON','OFF','ON')
function Drain-Bytes([int]$Milliseconds=100){
  $until=$sw.ElapsedMilliseconds+$Milliseconds
  while($sw.ElapsedMilliseconds -lt $until){
    $x=$serial.ReadExisting()
    if($x){[void]$all.Append($x); Write-Host -NoNewline $x}
    Start-Sleep -Milliseconds 3
  }
}
function Wait-For([string]$Marker,[int]$Seconds){
  $buffer=[System.Text.StringBuilder]::new()
  $until=$sw.Elapsed.TotalSeconds+$Seconds
  while($sw.Elapsed.TotalSeconds -lt $until){
    $chunk=$serial.ReadExisting()
    if($chunk){
      [void]$all.Append($chunk); [void]$buffer.Append($chunk)
      Write-Host -NoNewline $chunk
      if($buffer.ToString().Contains($Marker)) {
        return [pscustomobject]@{Text=$buffer.ToString(); ArrivalMs=$sw.Elapsed.TotalMilliseconds}
      }
      if($buffer.Length -gt 500000){throw "Excessive console output while waiting for [$Marker]"}
    }
    Start-Sleep -Milliseconds 2
  }
  throw "TIMEOUT after ${Seconds}s waiting for [$Marker]. No timing claimed."
}
function Run-CPU([string]$Phase,[int]$Run){
  Drain-Bytes 50
  $serial.Write("T2ECPU`r")
  $started=Wait-For 'T2E START' $TimeoutSeconds
  $finished=Wait-For 'T2E END' $TimeoutSeconds
  $value=[regex]::Match($finished.Text,'T2E CHECKSUM=([0-9A-Fa-f]{4})')
  if(-not $value.Success){throw 'Missing benchmark checksum'}
  if($value.Groups[1].Value.ToUpperInvariant() -ne '8642') {
    throw "BAD CHECKSUM: $($value.Groups[1].Value). Abort test."
  }
  $elapsed=$finished.ArrivalMs-$started.ArrivalMs
  if($elapsed -le 0){throw 'Invalid elapsed time'}
  $r=[pscustomobject]@{Phase=$Phase;Run=$Run;ElapsedMs=[math]::Round($elapsed,3);IterationsPerSec=[math]::Round(8388608000.0/$elapsed,0);Checksum='8642'}
  $rows.Add($r)
  Write-Host ("`n[2F] {0} run={1} elapsed={2:N3} ms throughput={3:N0} iter/s" -f $Phase,$Run,$elapsed,$r.IterationsPerSec)
  Drain-Bytes 50
}
try {
  $serial.Open()
  Drain-Bytes 150
  Write-Host "`n[2F] Prime VGA input owner with T2CVGA (must return to A> before timing)"
  $serial.Write("T2CVGA`r")
  $vga=Wait-For 'T2C VGA CHUNKS=' $TimeoutSeconds
  $prompt=Wait-For 'A>' $TimeoutSeconds
  if($prompt.Text -notmatch 'TICKS=[0-9A-Fa-f]{4}'){
    # Tick result might have arrived in first read chunk.
    if(($vga.Text+$prompt.Text) -notmatch 'TICKS=[0-9A-Fa-f]{4}') { throw 'VGA run did not produce complete ticks output' }
  }
  Write-Host "`n[2F] Warmup CPU"
  Run-CPU 'WARMUP' 0
  for($i=0;$i -lt $sequence.Count;$i++){
    $mode=$sequence[$i]
    if($i -gt 0){
      $serial.Write([string][char]0x10)
      $expected= if($mode -eq 'OFF') {'LCD presenter PAUSED'} else {'LCD presenter running'}
      [void](Wait-For $expected $TimeoutSeconds)
      Write-Host "`n[2F] Mode verified: $mode"
      Drain-Bytes 300
    }
    for($j=1;$j -le $RunsPerPhase;$j++){Run-CPU ("{0}{1}" -f $mode,($i+1)) $j}
  }
  Write-Host "`n[2F] Summary (medians of Windows host-side USB arrival times):"
  $medians=@()
  foreach($phase in @('ON1','OFF2','ON3')){
    $vals=@($rows | Where-Object {$_.Phase -eq $phase} | ForEach-Object {$_.ElapsedMs} | Sort-Object)
    if($vals.Count -eq 0){continue}
    $mid=[int][math]::Floor($vals.Count/2)
    $median=if($vals.Count%2 -eq 1){$vals[$mid]}else{($vals[$mid-1]+$vals[$mid])/2.0}
    $medians+= [pscustomobject]@{Phase=$phase;MedianMs=[math]::Round($median,3);MedianIterationsPerSec=[math]::Round(8388608000.0/$median,0)}
  }
  $rows | Format-Table -AutoSize | Out-Host
  $medians | Format-Table -AutoSize | Out-Host
  New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null
  $stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
  $csv=Join-Path $LogDirectory "bb-tier2f-$stamp.csv"
  $txt=Join-Path $LogDirectory "bb-tier2f-$stamp-console.txt"
  $rows | Export-Csv -NoTypeInformation -Encoding UTF8 $csv
  [System.IO.File]::WriteAllText($txt,$all.ToString())
  Write-Host "CSV: $csv"
  Write-Host "LOG: $txt"
  Write-Host 'CAUTION: This uses Windows serial arrival times; not Pico internal time_us_64().'
  Write-Host 'CAUTION: Tests execute at DOS text prompt. LCD core-1 load may differ dramatically from 3DBENCH VGA.'
} finally {
  if($serial.IsOpen){$serial.Close()}; $serial.Dispose()
}
