# blitzBUS PSRAM metadata arena A/B test. Does not modify the SRAM windows or JIT code cache.
# Usage: .\bb_psram_meta_experiment.ps1 -Mode Apply
#        .\bb_psram_meta_experiment.ps1 -Mode Status
#        .\bb_psram_meta_experiment.ps1 -Mode Restore
[CmdletBinding()]
param(
    [ValidateSet('Apply','Status','Restore')][string]$Mode='Status',
    [string]$BlitzBus='C:\blitzBUS',
    [string]$MicroDOS='C:\microDOS',
    [string]$Toolchain="$HOME\.pico-sdk\toolchain\14_2_Rel1\bin"
)
$ErrorActionPreference='Stop'
$source=Join-Path $BlitzBus 'src\bb_live.c'
$backup=Join-Path $BlitzBus 'src\bb_live.c.psram-meta-1024-baseline.bak'
$elf=Join-Path $MicroDOS 'build-pico\out\blitzbus_pico_b86_dos.elf'
# Match only the arena's actual preprocessor definition. Leave all other code untouched.
$pattern='(?m)^(\s*#define\s+BB_META_BYTES\s+)\((1024|896)u\s*\*\s*1024u\)(.*)$'
function Read-MetaDefine {
    param([string]$Path)
    if (!(Test-Path -LiteralPath $Path)) { throw "Missing source: $Path" }
    $text=[System.IO.File]::ReadAllText($Path)
    $hits=[regex]::Matches($text,$pattern)
    if ($hits.Count -ne 1) { throw "Expected exactly one 1024/896 KiB BB_META_BYTES definition; found $($hits.Count). No changes made." }
    return @{Content=$text; Match=$hits[0]; KiB=[int]$hits[0].Groups[2].Value}
}
if ($Mode -eq 'Apply') {
    $a=Read-MetaDefine $source
    if ($a.KiB -eq 896) { Write-Host 'Already set to 896 KiB.' -ForegroundColor Yellow }
    else {
        if (Test-Path -LiteralPath $backup) { throw "Baseline backup already exists: $backup. Refusing to overwrite it." }
        Copy-Item -LiteralPath $source -Destination $backup
        $new=[regex]::Replace($a.Content,$pattern,{
            param($m)
            $m.Groups[1].Value+'(896u * 1024u)'+$m.Groups[3].Value
        })
        # Retain UTF-8 with no BOM; avoid broad regex/source substitutions.
        [System.IO.File]::WriteAllText($source,$new,[System.Text.UTF8Encoding]::new($false))
        Write-Host 'Changed BB_META_BYTES: 1024 -> 896 KiB (-128 KiB PSRAM).' -ForegroundColor Green
    }
} elseif ($Mode -eq 'Restore') {
    if (!(Test-Path -LiteralPath $backup)) { throw "Missing baseline backup: $backup" }
    $b=Read-MetaDefine $backup
    if ($b.KiB -ne 1024) { throw 'Backup does not contain the expected 1024 KiB arena. Refusing restore.' }
    $current=Read-MetaDefine $source
    if ($current.KiB -ne 896 -and $current.KiB -ne 1024) { throw 'Unexpected live metadata size. Refusing restore.' }
    # Change only the arena size; preserve any unrelated edits made since the backup.
    $new=[regex]::Replace($current.Content,$pattern,{
        param($m)
        $m.Groups[1].Value+'(1024u * 1024u)'+$m.Groups[3].Value
    })
    [System.IO.File]::WriteAllText($source,$new,[System.Text.UTF8Encoding]::new($false))
    Write-Host 'Restored BB_META_BYTES to 1024 KiB.' -ForegroundColor Green
}
$a=Read-MetaDefine $source
Write-Host "BB_META_BYTES=$($a.KiB) KiB, backup=$backup"
if (Test-Path -LiteralPath $elf) {
    $size=Join-Path $Toolchain 'arm-none-eabi-size.exe'
    $nm=Join-Path $Toolchain 'arm-none-eabi-nm.exe'
    if ((Test-Path $size) -and (Test-Path $nm)) {
        Write-Host 'CURRENT ELF (may predate source change):'
        Get-Item $elf | Select-Object LastWriteTime,Length | Format-Table -AutoSize
        & $size -A $elf | Select-String '^\.(data|bss|heap)|^\.uninitialized'
        & $nm -S -t d $elf | Select-String ' bb_meta$| bb_shadow_buf$| bb_code$| bb_bbuf$| bb_vram$| bb_hot$'
    }
}
Write-Host 'Use the existing bb_live_run.ps1 workflow to rebuild, flash, and benchmark.'
