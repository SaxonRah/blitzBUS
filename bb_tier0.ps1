# blitzBUS Tier 0: read-only build/firmware inspection + optional serial capture.
[CmdletBinding()]
param(
 [string]$BlitzBus='C:\blitzBUS',
 [string]$MicroDos='C:\microDOS',
 [string]$Blitz86='C:\blitz86',
 [string]$Port='COM5',
 [int]$Seconds=90,
 [switch]$Capture,
 [string]$Log=''
)
$ErrorActionPreference='Stop'
$target='blitzbus_pico_b86_dos'
$build=Join-Path $MicroDos 'build-pico\out'
$logs=Join-Path $BlitzBus 'logs'
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$report=Join-Path $logs "tier0-$stamp-report.txt"
$lines=[System.Collections.Generic.List[string]]::new()
function Note([string]$key,[string]$value){$s=('{0,-28} {1}' -f $key,$value);Write-Host $s; $lines.Add($s)}
function Read-Text([string]$p) {if(Test-Path -LiteralPath $p){return [IO.File]::ReadAllText($p)};return ''}
function Hits([string]$s,[string]$pattern){return [regex]::Matches($s,$pattern,'IgnoreCase').Count}
Note 'TIER 0' 'No build, flash, code changes or firmware reboot performed'
foreach($pair in @(@('blitzBUS',$BlitzBus),@('microDOS',$MicroDos),@('blitz86',$Blitz86))){Note $pair[0] ($(if(Test-Path $pair[1]){$pair[1]}else{'NOT FOUND: '+$pair[1]}))}
$uf2=Join-Path $build "$target.uf2"
$elf=Join-Path $build "$target.elf"
$other=Join-Path $build 'microdos_pico.uf2'
Note 'Benchmark UF2' ($(if(Test-Path $uf2){(Get-Item $uf2).FullName+' ('+(Get-Item $uf2).LastWriteTime.ToString('s')+')'}else{'NOT FOUND; do not substitute microdos_pico.uf2'}))
Note 'Benchmark ELF' ($(if(Test-Path $elf){$elf}else{'NOT FOUND'}))
Note 'Ordinary microDOS UF2' ($(if(Test-Path $other){'Present (NOT the blitzBUS benchmark target)'}else{'Not present'}))
$installer=Read-Text (Join-Path $BlitzBus 'scripts\install_live.py')
$src=Read-Text (Join-Path $BlitzBus 'src\bb_live.c')
$generated=Read-Text (Join-Path $BlitzBus 'generated\bb_microdos_pico.c')
$cmake=Read-Text (Join-Path $MicroDos 'pico\CMakeLists.txt')
$targetStart=$cmake.IndexOf('# === blitzBUS v0.7 LIVE DOS BEGIN ===')
$targetEnd=$cmake.IndexOf('# === blitzBUS v0.7 LIVE DOS END ===')
$block=''
if($targetStart -ge 0 -and $targetEnd -gt $targetStart){$block=$cmake.Substring($targetStart,$targetEnd-$targetStart)}
Note 'Installed live CMake target' ($(if($block -match [regex]::Escape($target)){'YES'}else{'NOT DETECTED'}))
$clockMatch=[regex]::Match($block,'md_pico_dos\(blitzbus_pico_b86_dos\s+0\s+0\s+(\d+)')
Note 'Requested system clock' ($(if($clockMatch.Success){$clockMatch.Groups[1].Value+' kHz (compile setting; not measured hardware clock)'}else{'UNKNOWN'}))
$vregMatch=[regex]::Match($generated,'#define\s+BB_VREG_MV\s+(\d+)')
Note 'Generated voltage setting' ($(if($vregMatch.Success){$vregMatch.Groups[1].Value+' mV'}else{'UNKNOWN / generated file missing'}))
Note 'Boot clock validation' 'Confirm clock and vcore from actual boot banner; clock setting alone is not a measurement'
$sampleSource=($src -match 'BB_V49_PC_PROFILE')
$sampleFlag=Hits $block 'BB_V49_PC_PROFILE\s*(?:=\s*1)?\b'
Note 'PC sampler in source' ($(if($sampleSource){'Available, build flag must be checked'}else{'NOT FOUND'}))
Note 'Sampler target definition' ($(if($sampleFlag -gt 0){'PRESENT: verify whether enabled'}else{'Not in installed CMake overlay'}))
$searchFiles=@()
foreach($candidate in @('build.ninja','compile_commands.json','CMakeFiles\blitzbus_pico_b86_dos.dir\flags.make')){ $p=Join-Path $build $candidate; if(Test-Path $p){$searchFiles+=,$p} }
$flags=''
foreach($f in $searchFiles){$flags += (Read-Text $f)+"`n"}
# Exact -D flags from generated build metadata, if available.
$defs=[regex]::Matches($flags,'-D(?:BB_V49_PC_PROFILE|BB49_SAMPLE_HZ|MD_N3_PROFILE|MD_JIT_PROFILE|MICRODOS_PICO_SYS_KHZ|B86_OPT_PAGE_ZERO|B86_OPT_CS_CONST|B86_EA_IMM12_FAST)(?:=\S+)?') | ForEach-Object {$_.Value} | Sort-Object -Unique
Note 'Generated build definitions' ($(if($defs){$defs -join ', '}else{'None detected (build metadata may be absent)'}))
$badSampler=[regex]::IsMatch($flags,'-DBB_V49_PC_PROFILE(?:=1)?(?:\s|$)')
Note 'Sampler evaluation' ($(if($badSampler){'WARNING: PC profile enabled in generated build'}elseif($searchFiles.Count){'No enabled PC-profile definition detected; inspect any custom flags'}else{'UNVERIFIED: build metadata unavailable'}))
$jitMatch=[regex]::Match($block,'BB_CODE_BYTES=(\d+)\*1024')
Note 'JIT code allocation' ($(if($jitMatch.Success){$jitMatch.Groups[1].Value+' KiB requested'}else{'Check installed CMake definition BB_CODE_BYTES'}))
Note 'Runtime JIT health' 'Needs [bb-jit] lines from running 3DBENCH (flushes / cold-insns / translate-ms)'
if($Capture){
 if($Seconds -lt 10){throw 'Seconds must be >= 10'}
 $Log=Join-Path $logs "tier0-$stamp-console.txt"
 Note 'Serial capture' "$Port for $Seconds seconds -> $Log"
 Note 'User action' 'Start 3DBENCH before or during capture. Script sends Ctrl+] ~1/3 and ~2/3 into capture.'
 $ser=[System.IO.Ports.SerialPort]::new($Port,115200,[System.IO.Ports.Parity]::None,8,[System.IO.Ports.StopBits]::One)
 $ser.DtrEnable=$true;$ser.ReadTimeout=150
 try {
  $ser.Open()
  $sw=[Diagnostics.Stopwatch]::StartNew();$sent1=$false;$sent2=$false
  while($sw.Elapsed.TotalSeconds -lt $Seconds){
   $chunk=$ser.ReadExisting()
   if($chunk){[IO.File]::AppendAllText($Log,$chunk);Write-Host -NoNewline $chunk}
   if(-not $sent1 -and $sw.Elapsed.TotalSeconds -ge $Seconds/3){$ser.Write([string][char]29);$sent1=$true;Write-Host "`n[tier0] requested diagnostic report #1`n"}
   if(-not $sent2 -and $sw.Elapsed.TotalSeconds -ge 2*$Seconds/3){$ser.Write([string][char]29);$sent2=$true;Write-Host "`n[tier0] requested diagnostic report #2`n"}
   Start-Sleep -Milliseconds 30
  }
 }finally {if($ser.IsOpen){$ser.Close()};$ser.Dispose()}
}
if($Log){
 if(-not(Test-Path -LiteralPath $Log)){throw "Missing log: $Log"}
 $data=Read-Text $Log
 Note 'Analyzed console log' $Log
 $js=[regex]::Matches($data,'(?m)^\[bb-jit\][^\r\n]*')
 Note 'JIT interval lines' ([string]$js.Count)
 $idx=0
 foreach($m in $js){
  $idx++; $line=$m.Value
  $get={param($k) $x=[regex]::Match($line,'\b'+[regex]::Escape($k)+'=(\d+)');if($x.Success){return $x.Groups[1].Value};return '?'}
  Note "[bb-jit] interval $idx" ('flushes='+(& $get 'flushes')+' cold-insns='+(& $get 'cold-insns')+' translate-ms='+(& $get 'translate-ms')+' native-ms='+(& $get 'native-ms')+' xip-miss='+(& $get 'xip-miss'))
 }
 $fps=[regex]::Matches($data,'(?im)^.*(?:\bfps\b|\bscore\b).*$') | Select-Object -Last 8
 foreach($f in $fps){Note 'FPS / score candidate' ($f.Value.Trim())}
 $faults=[regex]::Matches($data,'(?im)^.*(?:HARDFAULT|PREVIOUS RUN HUNG|\[bb-v51-fault\]|fail=jit-create).*$') | Select-Object -Last 8
 foreach($f in $faults){Note 'FAULT / FAILURE' ($f.Value.Trim())}
 foreach($pattern in @('vcore:','psram:','[bb-v40-paged]','[bb-v51-stack]','[bb-v49]')){
  $matched=($data -split '[\r\n]+' | Where-Object { $_.Contains($pattern) } | Select-Object -Last 2)
  foreach($l in $matched){Note $pattern $l.Trim()}
 }
 if($js.Count -eq 0){Note 'Missing JIT stats' 'Press Ctrl+] during the VGA benchmark; verify correct blitzBUS firmware'}
}
$lines | Set-Content -LiteralPath $report -Encoding UTF8
Write-Host "`nTier 0 report: $report"
Write-Host 'No firmware was built or flashed. Share the report and optional console log for interpretation.'
