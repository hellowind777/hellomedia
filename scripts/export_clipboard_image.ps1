[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Output
)

$ErrorActionPreference = "Stop"

function Get-ImageFormat {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Extension
    )

    switch ($Extension.ToLowerInvariant()) {
        ".png" { return [System.Drawing.Imaging.ImageFormat]::Png }
        ".jpg" { return [System.Drawing.Imaging.ImageFormat]::Jpeg }
        ".jpeg" { return [System.Drawing.Imaging.ImageFormat]::Jpeg }
        ".bmp" { return [System.Drawing.Imaging.ImageFormat]::Bmp }
        ".gif" { return [System.Drawing.Imaging.ImageFormat]::Gif }
        ".tif" { return [System.Drawing.Imaging.ImageFormat]::Tiff }
        ".tiff" { return [System.Drawing.Imaging.ImageFormat]::Tiff }
        default { throw "Unsupported output extension '$Extension'. Use .png, .jpg, .jpeg, .bmp, .gif, .tif, or .tiff." }
    }
}

if ([Threading.Thread]::CurrentThread.ApartmentState -ne [Threading.ApartmentState]::STA) {
    $powershellPath = (Get-Command "powershell" -ErrorAction SilentlyContinue).Source
    if (-not $powershellPath) {
        $powershellPath = (Get-Process -Id $PID).Path
    }

    $arguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-STA",
        "-File", $PSCommandPath,
        "-Output", $Output
    )

    $process = Start-Process -FilePath $powershellPath -ArgumentList $arguments -Wait -PassThru -WindowStyle Hidden
    exit $process.ExitCode
}

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$resolvedOutput = [System.IO.Path]::GetFullPath($Output)
if ([string]::IsNullOrWhiteSpace([System.IO.Path]::GetExtension($resolvedOutput))) {
    $resolvedOutput = "$resolvedOutput.png"
}

$parent = Split-Path -Parent $resolvedOutput
if ($parent) {
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
}

if (-not [System.Windows.Forms.Clipboard]::ContainsImage()) {
    throw "Clipboard does not contain an image."
}

$image = [System.Windows.Forms.Clipboard]::GetImage()
if ($null -eq $image) {
    throw "Failed to read image from clipboard."
}

$format = Get-ImageFormat -Extension ([System.IO.Path]::GetExtension($resolvedOutput))

try {
    $image.Save($resolvedOutput, $format)
    Write-Output $resolvedOutput
}
finally {
    $image.Dispose()
}
