@echo off
setlocal
chcp 65001 >nul
title 品溢钢铁 - 手机访问地址
powershell -NoProfile -Command "$cfg = Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -ne $null } | Select-Object -First 1; if ($cfg) { Write-Host ('手机浏览器访问: http://' + $cfg.IPv4Address.IPAddress + ':8080') } else { Write-Host '未找到局域网连接，请检查 Wi-Fi。' }"
echo.
echo 手机需要和这台电脑连接同一个网络。
pause
