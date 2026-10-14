[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][ValidateSet('A','B')][string]$Drive,
  [Parameter(Mandatory=$true)][ValidateRange(1,9)][int]$Disk
)
$ErrorActionPreference='Stop'
if ($Drive -eq 'B' -and $Disk -gt 5) { throw 'B: accepts disk numbers 1 through 5' }
$root=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$dir=Join-Path $root 'logs'
[System.IO.Directory]::CreateDirectory($dir) | Out-Null
$target=Join-Path $dir 'bb622-swap.request'
if ([System.IO.File]::Exists($target)) { throw "An earlier disk request is still pending: $target" }
$temp=Join-Path $dir 'bb622-swap-request-writing.tmp'
try {
    if ([System.IO.File]::Exists($temp)) { throw "Another request writer may be active: $temp" }
    [System.IO.File]::WriteAllText($temp,($Drive+$Disk),[System.Text.Encoding]::ASCII)
    [System.IO.File]::Move($temp,$target)
} catch {
    if ([System.IO.File]::Exists($temp)) { [System.IO.File]::Delete($temp) }
    throw
}
Write-Host "Requested $($Drive): disk $Disk. Wait for [bb622-swap] $($Drive):$Disk OK in the runner before pressing Enter in DOS."
