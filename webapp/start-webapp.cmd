@echo off
chcp 65001 >nul
REM ============================================
REM 量化回测 Web 前端一键启动（单服务托管前端+API）
REM 前置：webapp\client 已执行过 npm install 和 npm run build
REM 用法：双击本文件，然后浏览器打开 http://localhost:3001
REM ============================================
cd /d "%~dp0server"

REM 指定项目唯一可用的 Python（3.14 缺依赖，禁用）
set PYTHON_BIN=C:\Users\22646\AppData\Local\Programs\Python\Python311\python.exe

echo 启动量化回测服务: http://localhost:3001
echo 按 Ctrl+C 停止
echo.
node server.js
pause
