[CmdletBinding()]
param(
    [string]$Root = 'C:\blitzBUS',
    [ValidateSet('events','screen','raw')][string]$Mode = 'events',
    [int]$Tail = 20
)
$ErrorActionPreference = 'Stop'
$viewer = Join-Path $PSScriptRoot 'bb622_logview.py'
if (!(Test-Path -LiteralPath $viewer -PathType Leaf)) {
    throw "Missing viewer: $viewer"
}
& python $viewer --root $Root --follow --mode $Mode --tail $Tail
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
