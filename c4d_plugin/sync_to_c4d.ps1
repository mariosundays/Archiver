# Install the Archiver asset-export plugin into Cinema 4D.
#
# WHY Program Files and not the custom prefs folder:
#   C4D 2026 on this machine does NOT reliably scan the custom prefs plugins
#   dir (E:\_DCC_Prefs_\_C4DPREFS_\PREFS2026\plugins) for newly-ADDED plugins.
#   Its existing residents load fine, but freshly-dropped .pyp files are
#   silently skipped -- proven with disk-breadcrumb probes while building the
#   Iris bridge. The application's own plugins dir is always scanned, so that
#   is the install target. Writing there needs admin, hence the self-elevation.
#
#   Two more C4D 2026 loader rules, both confirmed the hard way:
#     - an LF-only .pyp is IGNORED, so line endings are forced to CRLF below
#     - a folder plugin without res\c4d_symbols.h is silently skipped
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File sync_to_c4d.ps1
#
# Then RESTART Cinema 4D. The command appears under Extensions.

$ErrorActionPreference = "Stop"

$dstDir = "C:\Program Files\Maxon Cinema 4D 2026\plugins"

function Test-Writable {
    param([string]$Dir)
    try {
        $probe = Join-Path $Dir "_archiver_write_probe.tmp"
        [System.IO.File]::WriteAllText($probe, "x")
        Remove-Item $probe -Force
        return $true
    } catch { return $false }
}

if (-not (Test-Path $dstDir)) {
    Write-Error "C4D plugins folder not found: $dstDir"
    exit 1
}

if (-not (Test-Writable $dstDir)) {
    Write-Host "Need admin to write the plugins folder - relaunching elevated..."
    Start-Process powershell -Verb RunAs -Wait -ArgumentList `
        "-NoProfile","-ExecutionPolicy","Bypass","-File","`"$PSCommandPath`""
    exit $LASTEXITCODE
}

$utf8NoBom = New-Object System.Text.UTF8Encoding $false

function Copy-WithCRLF {
    param([string]$Src, [string]$Dst)
    if (-not (Test-Path $Src)) {
        Write-Warning "Source not found: $Src"
        return
    }
    $content = Get-Content -Raw -Path $Src -Encoding UTF8
    $content = $content -replace "`r`n", "`n"
    $content = $content -replace "`n", "`r`n"
    [System.IO.File]::WriteAllText($Dst, $content, $utf8NoBom)
    Write-Host ("  -> {0} ({1} bytes)" -f $Dst, (Get-Item $Dst).Length)
}

$repoRoot = Split-Path -Parent $PSScriptRoot

# 1. The plugin folder itself. res\c4d_symbols.h MUST come with it or C4D
#    skips the whole folder.
$srcPlugin = Join-Path $PSScriptRoot "ArchiverExport"
$dstPlugin = Join-Path $dstDir "ArchiverExport"

Write-Host "Installing ArchiverExport..."
if (Test-Path $dstPlugin) { Remove-Item -Recurse -Force $dstPlugin }
New-Item -ItemType Directory -Path (Join-Path $dstPlugin "res") -Force | Out-Null

Copy-WithCRLF `
    -Src (Join-Path $srcPlugin "ArchiverExport.pyp") `
    -Dst (Join-Path $dstPlugin "ArchiverExport.pyp")
Copy-WithCRLF `
    -Src (Join-Path $srcPlugin "res\c4d_symbols.h") `
    -Dst (Join-Path $dstPlugin "res\c4d_symbols.h")

# 2. The two shared modules, copied ONE LEVEL UP from the plugin folder --
#    directly into plugins\ -- which is where _load_shared() looks first.
#
#    They are Archiver's OWN core modules, copied rather than rewritten, so
#    the sidecar format can never drift between the writer and the reader.
#    That drift is a live problem in the Iris bridge (its PBR suffix list is a
#    hand-maintained copy that has fallen out of step); copying the real file
#    is what avoids repeating it. Re-run this script after changing either.
#
#    They are plain .py, not .pyp, so C4D never scans them as plugins.
Write-Host "Installing shared modules..."
foreach ($name in @("sidecar", "c4d_assets")) {
    Copy-WithCRLF `
        -Src (Join-Path $repoRoot "core\$name.py") `
        -Dst (Join-Path $dstDir "archiver_$name.py")
}

Write-Host "`nDone. Restart Cinema 4D, then use:"
Write-Host "  Extensions -> Archiver Asset Export"
