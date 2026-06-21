$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$iconPath = Join-Path $projectRoot "assets\app_icon.ico"
$versionFile = Join-Path $projectRoot "windows_version_info.txt"

if (-not (Test-Path $python)) {
    throw "Virtual environment Python was not found at .venv\Scripts\python.exe"
}

New-Item -ItemType Directory -Path (Split-Path $iconPath -Parent) -Force | Out-Null

if (-not (Test-Path $iconPath)) {
    Add-Type -AssemblyName System.Drawing
    Add-Type @"
using System;
using System.Runtime.InteropServices;

public static class IconTools {
    [DllImport("user32.dll", CharSet = CharSet.Auto)]
    public static extern bool DestroyIcon(IntPtr handle);
}
"@

    $bitmap = New-Object System.Drawing.Bitmap 64, 64
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $graphics.Clear([System.Drawing.Color]::FromArgb(15, 23, 42))

    $backgroundBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(14, 165, 233))
    $accentBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(34, 197, 94))
    $textBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::White)
    $font = New-Object System.Drawing.Font("Segoe UI", 20, [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Pixel)

    $graphics.FillEllipse($backgroundBrush, 4, 4, 56, 56)
    $graphics.FillEllipse($accentBrush, 40, 8, 16, 16)
    $graphics.DrawString("MM", $font, $textBrush, 7, 18)

    $iconHandle = $bitmap.GetHicon()
    $icon = [System.Drawing.Icon]::FromHandle($iconHandle)
    $stream = [System.IO.File]::Open($iconPath, [System.IO.FileMode]::Create)
    $icon.Save($stream)
    $stream.Close()
    $icon.Dispose()
    [IconTools]::DestroyIcon($iconHandle) | Out-Null
    $font.Dispose()
    $textBrush.Dispose()
    $accentBrush.Dispose()
    $backgroundBrush.Dispose()
    $graphics.Dispose()
    $bitmap.Dispose()
}

& $python -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onedir `
    --name MemoMorf `
    --icon $iconPath `
    --version-file $versionFile `
    --collect-all customtkinter `
    --collect-all faster_whisper `
    --collect-all ctranslate2 `
    --collect-all huggingface_hub `
    --collect-all av `
    --collect-all onnxruntime `
    --collect-all tokenizers `
    --collect-all pyannote.audio `
    --collect-all pyannote.core `
    --collect-all pyannote.database `
    --collect-all pyannote.metrics `
    --collect-all pyannote.pipeline `
    --collect-all torch `
    --collect-all torchaudio `
    --collect-all torchcodec `
    .\local_audio_transcriber.py

Write-Host ""
Write-Host "Build complete. Run the packaged app from:" -ForegroundColor Green
Write-Host "  dist\MemoMorf\MemoMorf.exe" -ForegroundColor Green
Write-Host "Do not run the intermediate executable from the build folder." -ForegroundColor Yellow