# blitzBUS command dispatcher. Started by bb.bat; Windows PowerShell 5.1 compatible.
#
#   bb boot     DOS 6.22: install, build, flash, console        (was: bb dos boot)
#   bb build    DOS 6.22: install + build firmware only
#   bb run      DOS 2 firmware (original runner; -BuildOnly builds only)
#   bb install  add the LCD console overlay to microDOS (reversible)
#   bb restore  remove that overlay
#   bb disk     request a floppy swap in the running DOS 6.22 console
#   bb irq0     arm the IRQ0 one-shot trial in the running console
#   bb pic      toggle the PIC probe in the running console
#   bb report   PC-sample report for a console log
#   bb log      latest console log and its key counters
#   bb config   effective settings and where each value comes from
#
# Settings come from bb.config.psd1; a variable already set in this window wins.
$ErrorActionPreference = 'Stop'
$Root    = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Scripts = $PSScriptRoot

function Read-BBConfig {
    $file = Join-Path $Root 'bb.config.psd1'
    if (-not (Test-Path -LiteralPath $file)) { throw "Missing settings file: $file" }
    return Import-PowerShellDataFile -LiteralPath $file
}

# Apply bb.config.psd1 to this process: only variables not already set.
# Returns rows of (name, value, source) for display.
function Use-BBConfig {
    $cfg = Read-BBConfig
    $rows = @()
    foreach ($name in ($cfg.Keys | Sort-Object)) {
        $current = [Environment]::GetEnvironmentVariable($name, 'Process')
        if ([string]::IsNullOrEmpty($current)) {
            [Environment]::SetEnvironmentVariable($name, [string]$cfg[$name], 'Process')
            $rows += [pscustomobject]@{ Name = $name; Value = [string]$cfg[$name]; Source = 'bb.config.psd1' }
        } else {
            $src = if ($current -eq [string]$cfg[$name]) { 'window (same as config)' } else { 'WINDOW OVERRIDE' }
            $rows += [pscustomobject]@{ Name = $name; Value = $current; Source = $src }
        }
    }
    # BB_* variables set in the window that the config file does not list
    foreach ($item in (Get-ChildItem Env: | Where-Object { $_.Name -like 'BB_*' } | Sort-Object Name)) {
        if (-not $cfg.Contains($item.Name)) {
            $rows += [pscustomobject]@{ Name = $item.Name; Value = $item.Value; Source = 'WINDOW (not in config)' }
        }
    }
    return $rows
}

function Show-BBConfig($rows, [switch]$OverridesOnly) {
    $show = if ($OverridesOnly) { @($rows | Where-Object { $_.Source -like 'WINDOW*' }) } else { @($rows) }
    if ($OverridesOnly -and $show.Count -eq 0) { Write-Host '[bb] settings: bb.config.psd1 (no window overrides)'; return }
    if ($OverridesOnly) { Write-Host '[bb] settings: bb.config.psd1 plus these window values:' }
    foreach ($r in $show) { Write-Host ('       {0,-17} = {1,-12} {2}' -f $r.Name, $r.Value, $r.Source) }
}

# '-Name value' / '-Switch' / positional -> splattable hashtable + array
function Split-BBArgs([object[]]$list) {
    $named = @{}; $pos = @(); $i = 0
    while ($i -lt $list.Count) {
        $a = [string]$list[$i]
        if ($a -match '^-([A-Za-z][A-Za-z0-9]*)$') {
            $n = $Matches[1]
            if ($i + 1 -lt $list.Count -and -not ([string]$list[$i + 1] -match '^-[A-Za-z]')) {
                $named[$n] = $list[$i + 1]; $i += 2
            } else { $named[$n] = $true; $i += 1 }
        } else { $pos += $a; $i += 1 }
    }
    return @{ Named = $named; Positional = $pos }
}

function Invoke-BBScript([string]$name, [hashtable]$named, [object[]]$pos) {
    $path = Join-Path $Scripts $name
    if (-not (Test-Path -LiteralPath $path)) { throw "Missing script: $path" }
    if ($null -eq $pos) { $pos = @() }
    $global:LASTEXITCODE = 0
    & $path @named @pos | Out-Host
    return [int]$global:LASTEXITCODE
}

function Invoke-BBPython([string]$path, [string[]]$argv) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Missing script: $path" }
    & python $path @argv | Out-Host
    return [int]$LASTEXITCODE
}

function Add-Default([hashtable]$named, [string]$key, [string]$value) {
    if (-not $named.ContainsKey($key)) { $named[$key] = $value }
}

function Show-Help {
@'
blitzBUS

  bb boot   [-NoBuild] [-NoFlash] [-NoInput] [-Seconds N] [-ConsoleView Screen|Events|Raw] [-Port COMx]
            DOS 6.22: install the live target, build, flash, open the console.
  bb build  DOS 6.22: install the live target and build the firmware only (no flash, no COM port).
  bb run    [-BuildOnly] [-Seconds N] [-Port COMx]     DOS 2 firmware (original runner).
  bb install | bb restore                              LCD console overlay in microDOS (reversible).

  While 'bb boot' is running, from a second window:
  bb disk A|B N     request floppy swap (waits for the firmware ACK)
  bb irq0           arm the IRQ0 one-shot trial
  bb pic            toggle the PIC probe

  bb report [-Log FILE]    PC-sample report (needs the firmware ELF)
  bb log    [-Tail N]      latest console log: path and key counters
  bb config                effective settings and where each comes from
  bb help

Settings: bb.config.psd1. A variable already set in the window wins, e.g.
  $env:BB_PJ_HOT_KB = '128'; .\bb.bat boot
'@ | Write-Host
}

# ---------------------------------------------------------------------------
$argv = @($args)
if ($argv.Count -ge 2 -and [string]$argv[0] -eq 'dos' -and [string]$argv[1] -eq 'boot') {
    $argv = @('boot') + @(if ($argv.Count -gt 2) { $argv[2..($argv.Count - 1)] })   # old 'bb dos boot'
}
$command = if ($argv.Count) { ([string]$argv[0]).ToLowerInvariant() } else { 'help' }
$rest    = @(if ($argv.Count -gt 1) { $argv[1..($argv.Count - 1)] })
$parsed  = Split-BBArgs $rest
$named   = $parsed.Named
$pos     = $parsed.Positional
$rc = 0

switch ($command) {
    'boot' {
        $rows = Use-BBConfig
        Show-BBConfig $rows -OverridesOnly
        Add-Default $named 'MicroDOS' $env:BB_MICRODOS
        Add-Default $named 'Blitz86'  $env:BB_BLITZ86
        Add-Default $named 'Port'     $env:BB_PORT
        $rc = Invoke-BBScript 'bb_live_run.ps1' $named $pos
    }
    'build' {
        $rows = Use-BBConfig
        Show-BBConfig $rows -OverridesOnly
        $rc = Invoke-BBPython (Join-Path $Scripts 'install_live.py') @('--microdos', $env:BB_MICRODOS, '--blitz86', $env:BB_BLITZ86)
        if ($rc -eq 0) {
            & cmake --build ([IO.Path]::Combine($env:BB_MICRODOS, 'build-pico', 'out')) --target blitzbus_pico_b86_dos
            $rc = $LASTEXITCODE
            if ($rc -eq 0) { Write-Host ('[bb] built ' + [IO.Path]::Combine($env:BB_MICRODOS, 'build-pico', 'out', 'blitzbus_pico_b86_dos.uf2')) }
        }
    }
    'run' {
        $rows = Use-BBConfig
        Add-Default $named 'MicroDos' $env:BB_MICRODOS
        Add-Default $named 'Port'     $env:BB_PORT
        $rc = Invoke-BBScript 'bb_run.ps1' $named $pos
    }
    'install' {
        $rows = Use-BBConfig
        $rc = Invoke-BBPython (Join-Path $Scripts 'install_overlay.py') @($rest)
    }
    'restore' {
        $rows = Use-BBConfig
        $rc = Invoke-BBPython (Join-Path $Scripts 'install_overlay.py') (@('--restore') + @($rest))
    }
    'disk' {
        if ($pos.Count -lt 2) { throw 'Usage: bb disk A|B N   (e.g. bb disk B 3)' }
        $named['Drive'] = $pos[0]; $named['Disk'] = [int]$pos[1]
        $rc = Invoke-BBScript 'bb622_request_media.ps1' $named @()
    }
    'irq0'   { $rc = Invoke-BBScript 'bb622_irq0_trial.ps1' $named $pos }
    'pic'    { $rc = Invoke-BBScript 'bb622_pic_toggle.ps1' $named $pos }
    'report' {
        $rows = Use-BBConfig
        Add-Default $named 'Elf' ([IO.Path]::Combine($env:BB_MICRODOS, 'build-pico', 'out', 'blitzbus_pico_b86_dos.elf'))
        $rc = Invoke-BBScript 'bb_pc_report.ps1' $named $pos
    }
    'log' {
        $logs = Join-Path $Root 'logs'
        $latest = Get-ChildItem -LiteralPath $logs -Filter 'bb-live-*-console.txt' -File -ErrorAction SilentlyContinue |
                  Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
        if (-not $latest) { throw "No console logs in $logs" }
        $tail = if ($named.ContainsKey('Tail')) { [int]$named['Tail'] } else { 40 }
        Write-Host "[bb] latest log: $($latest.FullName)"
        $pattern = 'timed run|HARDFAULT|\[bb386-coverage\]|\[bb386-hot\]|\[bb386-v85-tier\]|\[bb386-v31-lazy\]|\[bb386-pj\] |SRAM hot tier|RESULT'
        Select-String -LiteralPath $latest.FullName -Pattern $pattern | Select-Object -Last $tail | ForEach-Object { $_.Line }
    }
    'config' {
        $rows = Use-BBConfig
        Write-Host "[bb] settings file: $(Join-Path $Root 'bb.config.psd1')"
        Show-BBConfig $rows
    }
    { $_ -in @('help', '-h', '--help', '/?') } { Show-Help }
    default { Write-Host "Unknown command: $command"; Show-Help; $rc = 2 }
}
exit $rc
