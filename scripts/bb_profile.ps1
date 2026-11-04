# blitzBUS build profiles: one command instead of a block of $env:BB_* lines.
#
#   .\scripts\bb_profile.ps1 pm boot     # DOS/4GW and DJGPP programs (Descent, Doom, Quake)
#   .\scripts\bb_profile.ps1 rm boot     # real-mode programs (3DBench, real-mode games)
#
# Both share the same SRAM: 'pm' gives it to the protected-mode hot tier,
# 'rm' to the real-mode JIT's code cache. Everything after the profile name is
# passed to bb.bat (for example: boot -NoBuild). bb.config.psd1 still supplies
# every other setting; this script only clears the window's BB_* variables,
# sets the profile's values and builds with -AllowOverride.
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('pm', 'rm')]
    [string]$Profile,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Rest
)

$profiles = @{
    pm = [ordered]@{ BB_DPMI = '1'; BB_DPMI_DIRECT = '2'; BB_PJ_HOT_KB = '91'; BB_CODE_KB = '128'; BB_PM_RAM = '1' }
    rm = [ordered]@{ BB_DPMI = '1'; BB_DPMI_DIRECT = '2'; BB_PJ_HOT_KB = '0';  BB_CODE_KB = '240'; BB_PM_RAM = '0' }
}

Get-ChildItem Env:BB_* -ErrorAction SilentlyContinue | Remove-Item
$values = $profiles[$Profile]
foreach ($name in $values.Keys) {
    Set-Item -Path ("Env:" + $name) -Value $values[$name]
}
Write-Host ("[bb-profile] " + $Profile + ": " + (($values.Keys | ForEach-Object { $_ + "=" + $values[$_] }) -join "  "))

if (-not $Rest -or $Rest.Count -eq 0) { $Rest = @('boot') }
$root = Split-Path -Parent $PSScriptRoot
& (Join-Path $root 'bb.bat') @Rest -AllowOverride
exit $LASTEXITCODE
