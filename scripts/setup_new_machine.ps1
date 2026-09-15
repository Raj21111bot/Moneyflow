# Run this once on a new machine after copying the whole "moneyflow" folder over.
# It installs the Python dependency, registers the daily-refresh scheduled task,
# and creates the desktop launcher shortcut -- everything that does NOT travel
# with the files themselves (OS-level registrations tied to this machine/user).

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Write-Host "== NSE Money Flow -- new machine setup ==" -ForegroundColor Cyan

# 1. Find a real python.exe -- skip the WindowsApps "alias stub" entry, which
#    resolves fine interactively but silently fails when launched by Task
#    Scheduler (no console/session to activate through).
$py = Get-Command python.exe -All -ErrorAction SilentlyContinue |
    Where-Object { $_.Source -notmatch "WindowsApps" } |
    Select-Object -First 1 -ExpandProperty Source
if(-not $py){
    $py = Get-ChildItem "$env:LOCALAPPDATA\Python","$env:LOCALAPPDATA\Programs\Python" -Recurse -Filter python.exe -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty FullName
}
if(-not $py){
    Write-Host "Python not found. Install Python 3.10+ from python.org (check 'Add to PATH'), then re-run this script." -ForegroundColor Red
    exit 1
}
Write-Host "Using Python: $py"

# 2. Install the one dependency
& $py -m pip install requests --quiet
Write-Host "requests installed."

# 3. Point the two helper scripts at THIS machine's python.exe
foreach($f in "daily_refresh.ps1","launch_dashboard.ps1"){
    $path = Join-Path $root "scripts\$f"
    $content = Get-Content $path -Raw
    $content = $content -replace '\$py = "[^"]*pythoncore[^"]*python\.exe"', "`$py = `"$py`""
    Set-Content $path $content -Encoding UTF8 -NoNewline
}
Write-Host "Helper scripts updated with this machine's Python path."

# 4. Register the daily-refresh scheduled task (Mon-Fri, two triggers: an early
#    catch-up and a primary run timed for after NSE publishes ~6:30-7 PM IST).
#    Trigger times are computed relative to IST so this works unmodified
#    regardless of which timezone this machine is actually in.
Unregister-ScheduledTask -TaskName "MoneyFlow Daily Refresh" -Confirm:$false -ErrorAction SilentlyContinue
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$root\scripts\daily_refresh.ps1`""

$istZone = [System.TimeZoneInfo]::FindSystemTimeZoneById("India Standard Time")
$nowUtc = [System.DateTime]::UtcNow
$istNow = [System.TimeZoneInfo]::ConvertTimeFromUtc($nowUtc, $istZone)
$localZone = [System.TimeZoneInfo]::Local
function IstTimeToLocal([int]$hourIst, [int]$minuteIst){
    $istToday = New-Object System.DateTime($istNow.Year, $istNow.Month, $istNow.Day, $hourIst, $minuteIst, 0, [DateTimeKind]::Unspecified)
    $istUtc = [System.TimeZoneInfo]::ConvertTimeToUtc($istToday, $istZone)
    [System.TimeZoneInfo]::ConvertTimeFromUtc($istUtc, $localZone)
}
$catchUpLocal = IstTimeToLocal 7 0
$primaryLocal = IstTimeToLocal 19 15

$trigger1 = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $catchUpLocal.ToString("HH:mm")
$trigger2 = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $primaryLocal.ToString("HH:mm")
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd -WakeToRun
Register-ScheduledTask -TaskName "MoneyFlow Daily Refresh" -Action $action -Trigger @($trigger1, $trigger2) -Settings $settings `
    -Description "Fetches NSE bhavcopy and updates the Money Flow dashboard's history.json, Mon-Fri after market close." | Out-Null
Write-Host ("Scheduled task registered: {0} local (7:00 AM IST catch-up) and {1} local (7:15 PM IST primary)." -f $catchUpLocal.ToString("HH:mm"), $primaryLocal.ToString("HH:mm")) -ForegroundColor Yellow

# 5. Desktop shortcut
$desktop = [Environment]::GetFolderPath("Desktop")
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut((Join-Path $desktop "NSE Money Flow.lnk"))
$Shortcut.TargetPath = "powershell.exe"
$Shortcut.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$root\scripts\launch_dashboard.ps1`""
$Shortcut.WorkingDirectory = $root
$Shortcut.Description = "Launch NSE Money Flow dashboard"
$Shortcut.WindowStyle = 7
$Shortcut.Save()
Write-Host "Desktop shortcut 'NSE Money Flow' created at: $desktop"

Write-Host ""
Write-Host "Setup complete. Double-click the desktop shortcut to launch." -ForegroundColor Green
Write-Host "If docs\data\history.json wasn't copied over with the folder, seed it with:" -ForegroundColor Green
Write-Host "  $py scripts\fetch_daily.py --backfill 160" -ForegroundColor Green
