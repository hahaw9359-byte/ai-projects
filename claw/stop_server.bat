@echo off
chcp 65001 >nul
cd /d "%~dp0.."

set PID_FILE=%CD%\server.pid

REM 1. PID
if exist "%PID_FILE%" (
    set /p PID=<"%PID_FILE%"
    taskkill /pid !PID! /f >nul 2>&1
    del "%PID_FILE%" 2>nul
)

REM 2. port 8080
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8080.*LISTENING"') do (
    taskkill /pid %%a /f >nul 2>&1
)

echo [Claw] Stopped
timeout /t 2 >nul
