# Instalação do Eddy no Windows (PowerShell). Corre:  .\setup.ps1
$ErrorActionPreference = "Stop"
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { Write-Host "Instala o Python 3.12 primeiro: https://www.python.org/downloads/"; exit 1 }
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\pip install -r requirements.txt
$extras = Read-Host "Instalar voz (microfone + Whisper local)? [S/n]"
if ($extras -ne "n") { .\.venv\Scripts\pip install -r requirements-voice.txt }
$ctl = Read-Host "Instalar controlo do PC (volume, teclas, rato, ecrã)? [S/n]"
if ($ctl -ne "n") { .\.venv\Scripts\pip install -r requirements-control.txt pynput pyperclip pillow pywebview }
if (-not (Test-Path .env)) { Copy-Item .env.example .env; Write-Host "Criei .env. Abre-o e põe as tuas chaves (INCEPTION_API_KEY, ELEVENLABS_API_KEY)." }
Write-Host "`nPronto. Arranca com:  .\start.bat   (ou:  .\.venv\Scripts\python -m eddy)"
