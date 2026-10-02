# share-ngrok.ps1 — Temporarily share the Sparsh app with a client over ngrok.
#
# Starts the backend + frontend, then opens ONE ngrok tunnel to the frontend.
# The Vite dev server proxies /api to the FastAPI backend, so a single tunnel
# covers the whole app — the client only needs the one ngrok URL.
#
# Prerequisite (one time): create a free account at https://ngrok.com and run
#   ngrok config add-authtoken <YOUR_TOKEN>
#
# Usage:  powershell -ExecutionPolicy Bypass -File .\share-ngrok.ps1

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

# Resolve ngrok (winget installs aren't on PATH until the shell is restarted).
$ngrok = (Get-Command ngrok -ErrorAction SilentlyContinue).Source
if (-not $ngrok) {
    $ngrok = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Recurse -Filter ngrok.exe -ErrorAction SilentlyContinue |
             Select-Object -First 1 -ExpandProperty FullName
}
if (-not $ngrok) {
    Write-Error "ngrok not found. Install it with:  winget install Ngrok.Ngrok"
    exit 1
}

Write-Host "Starting backend  (FastAPI  -> http://localhost:8000)..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", `
    "cd '$root\backend'; .\venv\Scripts\Activate.ps1; uvicorn main:app --host 0.0.0.0 --port 8000 --reload"

Write-Host "Starting frontend (Vite     -> http://localhost:5173)..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", `
    "cd '$root\frontend'; npm run dev"

Write-Host "Waiting for the dev servers to come up..." -ForegroundColor Cyan
Start-Sleep -Seconds 8

Write-Host ""
Write-Host "Opening public ngrok tunnel. Share the 'Forwarding' https URL below." -ForegroundColor Green
Write-Host "Press Ctrl+C to stop the tunnel (then close the two server windows)." -ForegroundColor Green
Write-Host ""
& $ngrok http 5173
