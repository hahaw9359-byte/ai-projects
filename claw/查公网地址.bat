@echo off
chcp 65001 >nul
title 查询 Claw 公网地址
set "TUNNEL_LOG=%USERPROFILE%\claw_tunnel.log"

echo 正在读取公网地址...
powershell -NoProfile -Command "$log = Get-Content '%TUNNEL_LOG%' -Raw -ErrorAction SilentlyContinue; $m = [regex]::Match($log, 'https://[a-z0-9-]+\.trycloudflare\.com'); if ($m.Value) { Set-Clipboard -Value $m.Value; Write-Host ('公网地址: ' + $m.Value); Write-Host '已复制到剪贴板，直接 Ctrl+V 粘贴即可' } else { Write-Host '未找到地址，隧道可能未启动或还在建立中' }"
echo.
pause