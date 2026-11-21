@echo off
setlocal
chcp 65001 >nul
title 品溢钢铁 - 公网访问地址
powershell -NoProfile -Command "$u = (docker logs cf-quick 2>&1 | Select-String -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' | Select-Object -Last 1).Matches.Value; if ($u) { Set-Clipboard $u; Write-Host ('公网访问: ' + $u); Write-Host '已复制到剪贴板' } else { Write-Host '未找到地址，请确认容器 cf-quick 正在运行：docker ps' }"
echo.
pause
