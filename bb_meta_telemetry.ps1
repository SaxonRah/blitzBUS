[CmdletBinding()]
param(
  [ValidateSet('Apply','Restore','Status')]
  [string]$Mode='Apply',
  [string]$Root='C:\blitzBUS'
)
$ErrorActionPreference='Stop'
$path=Join-Path $Root 'src\bb_live.c'
$backup="$path.meta-telemetry-baseline.bak"
if (!(Test-Path -LiteralPath $path)) { throw "Missing $path" }
if ($Mode -eq 'Restore') {
  if (!(Test-Path -LiteralPath $backup)) { throw "Missing backup $backup" }
  Copy-Item -LiteralPath $backup -Destination $path -Force
  Write-Host "Restored original: $path"
  exit 0
}
$s=[IO.File]::ReadAllText($path)
$marker='/* BB_META_TELEMETRY_V1 */'
if ($Mode -eq 'Status') {
  Write-Host "Telemetry installed: $($s.Contains($marker))"
  Select-String -LiteralPath $path -Pattern 'BB_META_BYTES|BB_META_TELEMETRY_V1|bb-meta-usage' | Select-Object LineNumber,Line
  exit 0
}
if ($s.Contains($marker)) { Write-Host 'Already installed.'; exit 0 }
$nl=if($s.Contains("`r`n")){"`r`n"}else{"`n"}
$anchor1='static size_t bb_meta_used;'
$anchor2='    if (bb_meta_used + b > BB_META_BYTES) return NULL;'
$anchor3='void bb_meta_free(void *p) { (void)p; }'
$anchor4='    *s = st;'
foreach($a in @($anchor1,$anchor2,$anchor3,$anchor4)) {
  if ($s.Split(@($a),[StringSplitOptions]::None).Count -ne 2) { throw "Expected exactly one anchor: $a" }
}
# Instrument exact allocator failure paths, without altering successful allocation behavior.
$s=$s.Replace($anchor1,$anchor1+$nl+$marker+$nl+'static size_t bb_meta_max_failed_request;'+$nl+'static unsigned bb_meta_failures;')
$s=$s.Replace($anchor2,'    if (b > BB_META_BYTES - bb_meta_used) {'+$nl+'        ++bb_meta_failures;'+$nl+'        if (b > bb_meta_max_failed_request) bb_meta_max_failed_request = b;'+$nl+'        return NULL;'+$nl+'    }')
# Print during existing stats calls; guard for Pico only.
$insert=@'
#if defined(PICO_ON_DEVICE) && PICO_ON_DEVICE
    printf("[bb-meta-usage] used=%lu capacity=%lu free=%lu failures=%u max-failed-request=%lu\n",
           (unsigned long)bb_meta_used, (unsigned long)BB_META_BYTES,
           (unsigned long)(BB_META_BYTES - bb_meta_used),
           bb_meta_failures, (unsigned long)bb_meta_max_failed_request);
#endif
'@
$insert=$insert.TrimEnd() -replace "`r?`n",$nl
$s=$s.Replace($anchor4,$anchor4+$nl+$insert)
if (Test-Path -LiteralPath $backup) { throw "Backup already exists; will not overwrite: $backup" }
Copy-Item -LiteralPath $path -Destination $backup
[IO.File]::WriteAllText($path,$s)
Write-Host "Installed diagnostic-only metadata counters: $path"
Write-Host "Backup: $backup"
Write-Host 'Use Ctrl+] while running 3DBench to report [bb-meta-usage].'
