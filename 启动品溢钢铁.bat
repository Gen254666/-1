@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title 品溢钢铁 - 启动系统
echo 正在检查 Docker...
docker info >nul 2>&1
if errorlevel 1 (
  if exist "D:\Docker\DockerDesktop\Docker Desktop.exe" (
    echo 正在启动 Docker Desktop...
    start "" "D:\Docker\DockerDesktop\Docker Desktop.exe"
  ) else (
    echo 未找到 Docker Desktop，请先手动启动 Docker Desktop。
    pause
    exit /b 1
  )
  for /l %%i in (1,1,60) do (
    timeout /t 2 /nobreak >nul
    docker info >nul 2>&1 && goto ready
  )
  echo Docker 启动超时，请手动打开 Docker Desktop 后重试。
  pause
  exit /b 1
)
:ready
echo 正在启动品溢钢铁...
docker compose up -d
if errorlevel 1 (
  echo 启动失败，请检查 Docker 和网络。
  pause
  exit /b 1
)
timeout /t 2 /nobreak >nul
start "" http://localhost:8080
echo.
echo 品溢钢铁已启动：http://localhost:8080
echo 手机访问：双击“显示手机访问地址.bat”查看当前地址。
pause
