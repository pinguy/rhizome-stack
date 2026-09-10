param(
    [Parameter(Mandatory = $false)]
    [string]$Distro,

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$InstallerArgs
)

$ErrorActionPreference = "Stop"
$wslArgs = @()
if ($Distro) {
    $wslArgs += @("-d", $Distro)
}

$linuxPath = (& wsl.exe @wslArgs -- wslpath -a -u $PSScriptRoot).Trim()
if (-not $linuxPath) {
    throw "Could not translate the package path into WSL."
}

& wsl.exe @wslArgs --cd $linuxPath -- bash ./install-wsl.sh @InstallerArgs
if ($LASTEXITCODE -ne 0) {
    throw "WSL installer exited with code $LASTEXITCODE."
}

