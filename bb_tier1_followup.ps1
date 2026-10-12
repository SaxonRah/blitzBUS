[CmdletBinding()]
param(
    [ValidateSet('status','baseline','slice15','slice2','slice4','slice2defaultbudget','baselinebigbudget','restore')][string]$Mode='status',
    [switch]$Run,
    [string]$Root='C:\blitzBUS',
    [string]$MicroDOS='C:\microDOS',
    [string]$Blitz86='C:\blitz86_v2',
    [string]$Port='COM5',
    [int]$Seconds=180
)
$ErrorActionPreference='Stop'
$src=Join-Path $Root 'src\bb_live.c'
$bak=Join-Path $Root 'src\bb_live.c.tier1-original'
$state=Join-Path $Root 'logs\tier1-history.csv'
if (!(Test-Path -LiteralPath $src)) { throw "Missing $src" }
$enc=New-Object System.Text.UTF8Encoding($false)
function Read-Source([string]$p) { return [System.IO.File]::ReadAllText($p) }
function Write-Source([string]$p,[string]$s) { [System.IO.File]::WriteAllText($p,$s,$enc) }
function Get-Val([string]$s,[string]$name) {
    $rx='(?m)^#define\s+'+[regex]::Escape($name)+'\s+(\d+)(u?)\s*$'
    $m=[regex]::Matches($s,$rx)
    if($m.Count -ne 1) { throw "Expected exactly one $name definition; found $($m.Count). Not modifying source." }
    return [int]$m[0].Groups[1].Value
}
function Print-Status([string]$s) {
    Write-Host "Source: $src"
    Write-Host "BB_SLICE_US:       $(Get-Val $s 'BB_SLICE_US')"
    Write-Host "BB_SLICE_DISPATCH: $(Get-Val $s 'BB_SLICE_DISPATCH')"
    Write-Host "Backup exists:     $(Test-Path -LiteralPath $bak)"
    Write-Host 'Build/flash occurs only with -Run.'
}
$current=Read-Source $src
if ($Mode -eq 'status') { Print-Status $current; exit 0 }
if ($Mode -eq 'restore') {
    if(!(Test-Path -LiteralPath $bak)) { throw 'Tier 1 original backup not found; no changes made.' }
    $original=Read-Source $bak
    if ((Get-Val $original 'BB_SLICE_US') -ne 1000 -or (Get-Val $original 'BB_SLICE_DISPATCH') -ne 4096) {
        throw 'Original backup does not match expected Tier 0 defaults; refusing restore.'
    }
    Write-Source $src $original
    Write-Host 'Restored original bb_live.c from Tier 1 backup.'
} else {
    # Require a known starting point to avoid silently overwriting unrelated local customizations.
    $oldUs=Get-Val $current 'BB_SLICE_US'
    $oldDispatch=Get-Val $current 'BB_SLICE_DISPATCH'
    if (!(Test-Path -LiteralPath $bak)) {
        if ($oldUs -ne 1000 -or $oldDispatch -ne 4096) {
            throw 'Starting values are not the known Tier 0 defaults. Review the file before using Tier 1.'
        }
        [System.IO.File]::Copy($src,$bak)
        Write-Host "Saved byte-for-byte original: $bak"
    }
    $original=Read-Source $bak
    if ((Get-Val $original 'BB_SLICE_US') -ne 1000 -or (Get-Val $original 'BB_SLICE_DISPATCH') -ne 4096) {
        throw 'Backup is not the expected Tier 0 baseline. No change made.'
    }
    switch ($Mode) {
        'baseline' { $us=1000; $dispatch=4096 }
        'slice15' { $us=1500; $dispatch=6144 }
        'slice2'   { $us=2000; $dispatch=8192 }
        'slice2defaultbudget' { $us=2000; $dispatch=4096 }
        'baselinebigbudget'  { $us=1000; $dispatch=8192 }
        'slice4'   { $us=4000; $dispatch=16384 }
    }
    $changed=[regex]::Replace($original,'(?m)^(#define\s+BB_SLICE_US\s+)1000(\s*)$',"`${1}$us`${2}")
    $changed=[regex]::Replace($changed,'(?m)^(#define\s+BB_SLICE_DISPATCH\s+)4096u(\s*)$',"`${1}${dispatch}u`${2}")
    if ((Get-Val $changed 'BB_SLICE_US') -ne $us -or (Get-Val $changed 'BB_SLICE_DISPATCH') -ne $dispatch) { throw 'Replacement validation failed. No changes made.' }
    Write-Source $src $changed
    Write-Host "Applied $Mode ($us us, $dispatch dispatch)"
}
Print-Status (Read-Source $src)
New-Item -ItemType Directory -Force (Split-Path $state) | Out-Null
$entry=[pscustomobject]@{ timestamp=(Get-Date -Format 's'); mode=$Mode; slice_us=(Get-Val (Read-Source $src) 'BB_SLICE_US'); dispatch=(Get-Val (Read-Source $src) 'BB_SLICE_DISPATCH'); run=$Run.IsPresent }
if (Test-Path $state) {$entry | Export-Csv $state -NoTypeInformation -Append} else {$entry | Export-Csv $state -NoTypeInformation}
if ($Run) {
    $runner=Join-Path $Root 'scripts\bb_live_run.ps1'
    if(!(Test-Path $runner)) {throw "Runner missing: $runner"}
    # Explicitly retain the user's known-good benchmark parameters.
    $env:BB_LCD_PERI_HZ='150000000'
    $env:BB_LCD_SPI_HZ='75000000'
    $env:BB_LCD_LACE='1'
    $env:BB_BBUF='0'
    $env:BB_CODE_KB='292'
    $env:BB_HOT_THRESHOLD='32'
    Write-Host 'Building/flashing the blitz86-enabled target and opening the interactive DOS console.'
    Write-Host 'Type 3DBENCH at A>, record the benchmark score, and use Ctrl+X to exit.'
    & $runner -MicroDOS $MicroDOS -Blitz86 $Blitz86 -Port $Port -Seconds $Seconds
    if ($LASTEXITCODE -ne 0) { throw "Live runner exited with code $LASTEXITCODE" }
} else {
    Write-Host "Run experiment with: .\bb_tier1.ps1 -Mode $Mode -Run"
}
