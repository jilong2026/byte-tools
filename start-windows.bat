@echo off
REM ==========================================================================
REM byte-tools Windows 一键启动脚本
REM --------------------------------------------------------------------------
REM 功能：检查 Python -> 创建虚拟环境 -> 安装依赖 -> 启动 GUI
REM 用法：双击本文件，或在终端执行 start-windows.bat
REM --------------------------------------------------------------------------
REM 设计说明：
REM   1. 优先使用 py launcher（Windows 官方 Python 启动器），fallback 到 python.exe
REM   2. Python 版本必须 >= 3.9（PySide6 6.6+ 要求）
REM   3. pip 安装使用清华 TUNA 镜像加速（符合项目 R1 规则的国内镜像优先原则）
REM   4. 虚拟环境放在项目根目录 .venv 下，已存在则跳过创建
REM ==========================================================================

setlocal enabledelayedexpansion
cd /d "%~dp0"

REM ----- 可配置参数（按需修改）-----
REM Python 最低版本号（主.次）
set "PY_MIN_MAJOR=3"
set "PY_MIN_MINOR=9"
REM 国内 PyPI 镜像源（清华 TUNA）
set "PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple"
REM 备用镜像源（阿里云）
set "PIP_INDEX_URL_BACKUP=https://mirrors.aliyun.com/pypi/simple"
REM 虚拟环境目录名
set "VENV_DIR=.venv"

echo.
echo ================================================================
echo   byte-tools Windows 一键启动脚本
echo   工作目录: %CD%
echo ================================================================
echo.

REM ==========================================================================
REM 步骤 1：定位 Python 解释器
REM ==========================================================================
set "PY_CMD="

REM 优先尝试 py launcher（Windows 官方启动器，能按版本选择）
where py >nul 2>&1
if %errorlevel% equ 0 (
    set "PY_CMD=py"
    echo [1/4] 检测到 py launcher，使用 py 作为 Python 解释器
    goto :check_py_version
)

REM fallback：直接找 python.exe
where python >nul 2>&1
if %errorlevel% equ 0 (
    set "PY_CMD=python"
    echo [1/4] 检测到 python.exe，使用 python 作为 Python 解释器
    goto :check_py_version
)

echo [错误] 未找到 Python 解释器！
echo        请安装 Python %PY_MIN_MAJOR%.%PY_MIN_MINOR% 或更高版本：https://www.python.org/downloads/windows/
echo        或使用 winget 安装：winget install Python.Python.3.12
pause
exit /b 1

:check_py_version
REM 检查 Python 版本是否 >= 3.9
for /f "tokens=2 delims= " %%v in ('%PY_CMD% --version 2^>^&1') do set "PY_VERSION=%%v"
echo        Python 版本: %PY_VERSION%

REM 解析主版本号和次版本号
for /f "tokens=1,2 delims=." %%a in ("%PY_VERSION%") do (
    set "PY_MAJOR=%%a"
    set "PY_MINOR=%%b"
)

if !PY_MAJOR! lss %PY_MIN_MAJOR% goto :py_version_too_low
if !PY_MAJOR! equ %PY_MIN_MAJOR% (
    if !PY_MINOR! lss %PY_MIN_MINOR% goto :py_version_too_low
)
echo        版本符合要求 (>= %PY_MIN_MAJOR%.%PY_MIN_MINOR%)
goto :check_venv

:py_version_too_low
echo [错误] Python 版本过低：当前 %PY_VERSION%，要求 >= %PY_MIN_MAJOR%.%PY_MIN_MINOR%
echo        PySide6 6.6+ 需要 Python %PY_MIN_MAJOR%.%PY_MIN_MINOR% 及以上
pause
exit /b 1

REM ==========================================================================
REM 步骤 2：检查 / 创建虚拟环境
REM ==========================================================================
:check_venv
echo.
if exist "%VENV_DIR%\Scripts\python.exe" (
    echo [2/4] 虚拟环境已存在: %VENV_DIR%
) else (
    echo [2/4] 创建虚拟环境: %VENV_DIR%
    %PY_CMD% -m venv "%VENV_DIR%"
    if %errorlevel% neq 0 (
        echo [错误] 创建虚拟环境失败
        pause
        exit /b 1
    )
    echo        虚拟环境创建成功
)

REM 虚拟环境内的 python 和 pip
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "VENV_PIP=%VENV_DIR%\Scripts\pip.exe"

REM ==========================================================================
REM 步骤 3：安装 / 更新依赖
REM ==========================================================================
echo.
echo [3/4] 检查依赖（使用清华 TUNA PyPI 镜像加速）
"%VENV_PY%" -c "import PySide6, requests; print('依赖已安装')" >nul 2>&1
if %errorlevel% equ 0 (
    echo        依赖已就绪，跳过安装
) else (
    echo        正在安装依赖...
    "%VENV_PIP%" install --upgrade pip -i %PIP_INDEX_URL% --trusted-host pypi.tuna.tsinghua.edu.cn
    if %errorlevel% neq 0 (
        echo [警告] 清华镜像升级 pip 失败，切换到阿里云镜像重试
        "%VENV_PIP%" install --upgrade pip -i %PIP_INDEX_URL_BACKUP% --trusted-host mirrors.aliyun.com
    )
    "%VENV_PIP%" install -r requirements.txt -i %PIP_INDEX_URL% --trusted-host pypi.tuna.tsinghua.edu.cn
    if %errorlevel% neq 0 (
        echo [警告] 清华镜像安装依赖失败，切换到阿里云镜像重试
        "%VENV_PIP%" install -r requirements.txt -i %PIP_INDEX_URL_BACKUP% --trusted-host mirrors.aliyun.com
        if %errorlevel% neq 0 (
            echo [错误] 依赖安装失败，请检查网络或手动执行:
            echo        %VENV_PIP% install -r requirements.txt
            pause
            exit /b 1
        )
    )
    echo        依赖安装完成
)

REM ==========================================================================
REM 步骤 4：启动 GUI
REM ==========================================================================
echo.
echo [4/4] 启动 byte-tools GUI
echo.
"%VENV_PY%" main.py
if %errorlevel% neq 0 (
    echo.
    echo [错误] GUI 启动失败，退出码: %errorlevel%
    echo        请将以上错误信息反馈给开发者
    pause
)

endlocal
