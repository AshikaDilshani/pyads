<#
.SYNOPSIS
Registers a persistent `pyads` command in the current user's PowerShell profile.

.DESCRIPTION
After running this once, `pyads` can be typed directly in PowerShell.
It prefers a configured Python from $env:PYADS_PYTHON, then common conda env paths,
then falls back to `python` on PATH.
#>

[CmdletBinding()]
param()

$homeDir = [Environment]::GetFolderPath("MyDocuments")
$profilePaths = @(
    (Join-Path $homeDir "PowerShell\Microsoft.PowerShell_profile.ps1"),
    (Join-Path $homeDir "WindowsPowerShell\Microsoft.PowerShell_profile.ps1")
)

$blockStart = "# >>> pyads command >>>"
$blockEnd = "# <<< pyads command <<<"

function Update-ProfileFile {
    param([string]$ProfilePath, [string]$BlockStart, [string]$BlockEnd, [string]$BlockText)

    $profileDir = Split-Path -Parent $ProfilePath
    if (-not (Test-Path $profileDir)) {
        New-Item -ItemType Directory -Path $profileDir -Force | Out-Null
    }
    if (-not (Test-Path $ProfilePath)) {
        New-Item -ItemType File -Path $ProfilePath -Force | Out-Null
    }

    $profileContent = Get-Content -Path $ProfilePath -Raw -ErrorAction SilentlyContinue
    if (-not $profileContent) {
        $profileContent = ""
    }

    # Remove old block if it exists.
    $pattern = [regex]::Escape($BlockStart) + ".*?" + [regex]::Escape($BlockEnd)
    $profileContent = [regex]::Replace($profileContent, $pattern, "", "Singleline").TrimEnd()

    if ($profileContent) {
        $newContent = $profileContent + "`r`n`r`n" + $BlockText + "`r`n"
    } else {
        $newContent = $BlockText + "`r`n"
    }

    Set-Content -Path $ProfilePath -Value $newContent -Encoding UTF8
    Write-Output "Updated profile: $ProfilePath"
}

$block = @"
$blockStart
function pyads {
    param(
        [Parameter(ValueFromRemainingArguments=`$true)]
        [object[]]`$Args
    )

    `$pythonCandidates = @()
    if (`$env:PYADS_PYTHON) {
        `$pythonCandidates += `$env:PYADS_PYTHON
    }
    `$pythonCandidates += @(
        "`$env:USERPROFILE\AppData\Local\anaconda3\envs\adsorption\python.exe",
        "`$env:USERPROFILE\AppData\Local\miniconda3\envs\adsorption\python.exe"
    )

    foreach (`$py in `$pythonCandidates) {
        if (`$py -and (Test-Path `$py)) {
            & `$py -m pyads @Args
            return
        }
    }

    if (Get-Command python -ErrorAction SilentlyContinue) {
        & python -m pyads @Args
        return
    }

    throw "No usable Python interpreter found for pyads."
}
$blockEnd
"@

foreach ($profilePath in $profilePaths) {
    Update-ProfileFile -ProfilePath $profilePath -BlockStart $blockStart -BlockEnd $blockEnd -BlockText $block
}
Write-Output "Open a new PowerShell session, then run: pyads --help"
