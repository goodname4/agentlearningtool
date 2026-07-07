@echo off
setlocal

cd /d "%~dp0"
title Zhixue Demo

echo [1/3] Locating Python...
set "PYTHON_EXE="

if exist ".venv\Scripts\python.exe" set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"
if not defined PYTHON_EXE if exist "..\.venv\Scripts\python.exe" set "PYTHON_EXE=%CD%\..\.venv\Scripts\python.exe"
if not defined PYTHON_EXE where python >nul 2>nul && set "PYTHON_EXE=python"
if not defined PYTHON_EXE if exist "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
if not defined PYTHON_EXE where py >nul 2>nul && set "PYTHON_EXE=py"

if not defined PYTHON_EXE (
  echo Python was not found. Please install Python first.
  pause
  exit /b 1
)

echo Using: %PYTHON_EXE%
echo.

echo [2/3] Installing/updating dependencies...
"%PYTHON_EXE%" -m pip install -r demo\requirements.txt
if errorlevel 1 (
  echo Dependency installation failed.
  pause
  exit /b 1
)

echo.
echo [3/3] Starting demo...
echo URL: http://127.0.0.1:5000
echo Login: demo / demo2026
echo.

start "" /b powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 3; Start-Process 'http://127.0.0.1:5000'"

cd /d "%~dp0demo"
"%PYTHON_EXE%" app.py

pause
