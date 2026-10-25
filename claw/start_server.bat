@echo off
chcp 65001 >nul
title Claw 启动器
cd /d "%~dp0.."

set "PID_FILE=%CD%\server.pid"
set "TUNNEL_LOG=%USERPROFILE%\claw_tunnel.log"
set "CF=C:\Program Files (x86)\cloudflared\cloudflared.exe"

echo ============================================
echo    Claw 一体化启动（本地服务 + 公网隧道）
echo ============================================
echo.

REM ---------- 1. 本地服务 ----------
netstat -ano | findstr ":8080.*LISTENING" >nul
if errorlevel 1 (
    echo [1/3] 正在启动本地服务...
    if exist "%PID_FILE%" del "%PID_FILE%"
    powershell -NoProfile -Command " = Start-Process -FilePath 'python' -ArgumentList '-m','claw.server.main' -WorkingDirectory '%CD%' -WindowStyle Hidden -PassThru; .Id | Out-File -FilePath '%PID_FILE%' -NoNewline; Start-Sleep 3"
) else (
    echo [1/3] 本地服务已在运行
)

REM ---------- 2. 公网隧道 ----------
tasklist | findstr /i "cloudflared" >nul
if errorlevel 1 (
    echo [2/3] 正在启动公网隧道...
    powershell -NoProfile -Command "Start-Process -FilePath '%CF%' -ArgumentList 'tunnel','--url','http://localhost:8080','--logfile','%TUNNEL_LOG%' -WindowStyle Hidden"
    echo       等待隧道建立（约 6 秒）...
    timeout /t 6 /nobreak >nul
) else (
    echo [2/3] 公网隧道已在运行
)

REM ---------- 3. 读取地址 ----------
echo [3/3] 正在读取公网地址...
powershell -NoProfile -Command "$log = Get-Content '%TUNNEL_LOG%' -Raw -ErrorAction SilentlyContinue; $m = [regex]::Match($log, 'https://[a-z0-9-]+\.trycloudflare\.com'); if ($m.Value) { Set-Clipboard -Value $m.Value; Write-Host ('公网地址: ' + $m.Value); Write-Host '已复制到剪贴板，直接 Ctrl+V 粘贴即可' } else { Write-Host '未找到地址，隧道可能未启动或还在建立中' }"

echo.
echo --------------------------------------------
echo    本地访问:  http://127.0.0.1:8080
echo --------------------------------------------
echo.
pause