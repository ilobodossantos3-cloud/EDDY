@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title EDDY

rem --- 1. Python / ambiente virtual ---
if not exist ".venv\Scripts\python.exe" (
  echo [Eddy] A criar o ambiente virtual ^(so na primeira vez^)...
  where py >nul 2>nul && ( py -3.12 -m venv .venv 2>nul )
  if not exist ".venv\Scripts\python.exe" ( python -m venv .venv )
  if not exist ".venv\Scripts\python.exe" (
    echo [ERRO] Nao consegui criar o ambiente. Instala o Python 3.12 e tenta outra vez.
    pause & exit /b 1
  )
)
set "PY=.venv\Scripts\python.exe"

rem --- 2. Dependencias (so se faltarem; o marcador evita repetir) ---
if not exist ".venv\.eddy_deps_ok" (
  echo [Eddy] A instalar dependencias ^(so na primeira vez^)...
  "%PY%" -m pip install --disable-pip-version-check -q -r requirements-voice.txt
  if errorlevel 1 (
    echo [ERRO] Falhou a instalacao das dependencias. Corre: %PY% -m pip install -r requirements-voice.txt
    pause & exit /b 1
  )
  echo ok> ".venv\.eddy_deps_ok"
)

rem --- 3. Chaves (.env) ---
if not exist ".env" (
  copy /y ".env.example" ".env" >nul
  echo [Eddy] Criei o ficheiro .env. Abre-o, cola as tuas chaves e volta a abrir o Eddie.bat.
  notepad ".env"
  pause & exit /b 1
)
findstr /b /c:"GEMINI_API_KEY=." ".env" >nul || echo [AVISO] GEMINI_API_KEY esta vazia no .env: sem ela nao ha cerebro nem voz da Gemini.

rem --- 4. Eddy (recusa segunda instancia: o Python devolve 3) ---
echo [Eddy] A iniciar...
"%PY%" -m eddy %*
set "RC=%ERRORLEVEL%"
if "%RC%"=="3" (
  echo.
  echo [Eddy] Ja esta a correr. Fecha a outra janela antes de abrir outra.
  pause
  exit /b 3
)
if not "%RC%"=="0" (
  echo.
  echo [ERRO] O Eddy terminou com o codigo %RC%. Ve logs\eddy.log
  pause
)
exit /b %RC%