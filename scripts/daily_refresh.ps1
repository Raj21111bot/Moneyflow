$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONIOENCODING = "utf-8"

$logDir = Join-Path $root "logs"
if(-not (Test-Path $logDir)){ New-Item -ItemType Directory -Path $logDir | Out-Null }
$logFile = Join-Path $logDir ("fetch_{0}.log" -f (Get-Date -Format "yyyy-MM-dd"))

$py = "C:\Users\Manju\AppData\Local\Programs\Python\Python314\python.exe"
if(-not (Test-Path $py)){
    $py = (Get-Command python.exe -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source)
}
if(-not $py){ $py = "python" }

& $py scripts\fetch_daily.py *> $logFile

# Best-effort: push the updated data to GitHub Pages, if this machine has git
# set up and can currently reach GitHub. Never fails the overall task -- the
# NSE fetch above already succeeded and wrote history.json regardless of
# whether this publish step works (e.g. office network blocks GitHub; git
# not installed yet; not set up as a repo yet).
try {
    $git = Get-Command git.exe -ErrorAction SilentlyContinue
    $hasRemote = $false
    if($git -and (Test-Path (Join-Path $root ".git"))){
        Push-Location $root
        $remotes = git remote 2>$null
        $hasRemote = ($remotes -contains "origin")
        Pop-Location
    }
    if($git -and $hasRemote){
        Push-Location $root
        git add docs/data/history.json *>> $logFile
        git diff --cached --quiet
        $hasChanges = ($LASTEXITCODE -ne 0)
        if($hasChanges){
            git commit -m "data: $(Get-Date -Format 'yyyy-MM-dd') update" *>> $logFile
            git push *>> $logFile
        }
        Pop-Location
    }
} catch {
    "[publish] skipped: $($_.Exception.Message)" | Out-File -Append $logFile
}
