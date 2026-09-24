$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

$py = "C:\Users\Manju\AppData\Local\Programs\Python\Python314\python.exe"
if(-not (Test-Path $py)){
    $py = (Get-Command python.exe -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source)
}
if(-not $py){ $py = "python" }

$portInUse = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if(-not $portInUse){
    Start-Process -FilePath $py -ArgumentList "`"$root\scripts\dashboard_server.py`"","8000" -WorkingDirectory $root -WindowStyle Hidden
    Start-Sleep -Milliseconds 800
}

Start-Process "http://127.0.0.1:8000"
