# blitzBUS DOS Dual Console V1
# A DISPLAY-ONLY mirror of the existing raw DOS console capture.
# Only bb_live_run_dos622_irqtrial.ps1 owns COM5 and sends keyboard commands.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Log,
    [int]$ParentPid=0,
    [ValidateRange(20,1000)][int]$PollMilliseconds=80,
    [switch]$Replay
)
$ErrorActionPreference='Stop'
$colorModule=Join-Path $PSScriptRoot 'bb622_descent_color_host.ps1'
if(!(Test-Path -LiteralPath $colorModule -PathType Leaf)) {
    throw "Missing original CP437 color renderer: $colorModule"
}
# This dot-source only loads the pre-existing host display functions.
. $colorModule
$logPath=[System.IO.Path]::GetFullPath($Log)
$position=[long]0
$buffer=New-Object 'byte[]' 65536
$decoder=[System.Text.Encoding]::UTF8
$parentExitedAt=$null
$started=[datetime]::UtcNow
try { [Console]::Title='blitzBUS DOS 6.22 - VGA color mirror (read-only, COM5 in other window)' } catch {}

function Test-BbParentAlive([int]$Id) {
    if($Id -le 0) { return $true }
    return ($null -ne (Get-Process -Id $Id -ErrorAction SilentlyContinue))
}
function Test-BbMirrorExitKey {
    try {
        if([Console]::KeyAvailable) {
            $key=[Console]::ReadKey($true)
            return ([int][char]$key.KeyChar -eq 24 -or $key.Key -eq [ConsoleKey]::Escape)
        }
    } catch {}
    return $false
}

# The log may not exist yet: firmware startup can precede the first append.
# All bytes are read from the start, so no screen rows are lost if this window
# is launched after DOS has already rendered several frames.
while($true) {
    if(Test-BbMirrorExitKey) { break }
    $changed=$false
    if(Test-Path -LiteralPath $logPath -PathType Leaf) {
        try {
            $file=[System.IO.File]::Open($logPath,
                [System.IO.FileMode]::Open,
                [System.IO.FileAccess]::Read,
                ([System.IO.FileShare]::ReadWrite -bor [System.IO.FileShare]::Delete))
            try {
                if($file.Length -lt $position) {
                    # New/truncated log: start over, rather than seeking past EOF.
                    $position=0
                }
                # Bound processing per iteration to keep Ctrl+X responsive.
                $budget=1048576
                while($file.Length -gt $position -and $budget -gt 0) {
                    [void]$file.Seek($position,[System.IO.SeekOrigin]::Begin)
                    $take=[int][Math]::Min([long]$buffer.Length,
                         [Math]::Min($file.Length-$position,[long]$budget))
                    $got=$file.Read($buffer,0,$take)
                    if($got -le 0) { break }
                    $position+=$got
                    $budget-=$got
                    $changed=$true
                    Write-BbDos622ColorConsoleChunk ($decoder.GetString($buffer,0,$got)) 'Screen'
                }
            } finally { $file.Dispose() }
        } catch [System.IO.IOException] {
            # A brief open/rename race is harmless; resume from last offset.
        }
    }
    if($Replay) {
        # Once all existing data is consumed, return without waiting for COM5.
        if(!$changed) { break }
    }
    if($ParentPid -gt 0 -and !(Test-BbParentAlive $ParentPid)) {
        if($null -eq $parentExitedAt) { $parentExitedAt=[datetime]::UtcNow }
        if(([datetime]::UtcNow-$parentExitedAt).TotalSeconds -ge 3) { break }
    }
    if(!$changed -and $ParentPid -eq 0 -and
       !(Test-Path -LiteralPath $logPath -PathType Leaf) -and
       ([datetime]::UtcNow-$started).TotalSeconds -ge 20) {
        throw "No console capture appeared within 20 seconds: $logPath"
    }
    Start-Sleep -Milliseconds $PollMilliseconds
}
