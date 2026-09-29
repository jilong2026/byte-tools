@echo off
chcp 65001 >nul
title byte-tools 打包脚本
REM ==========================================================================
REM byte-tools 一键打包脚本（自动准备环境 + PyInstaller）
REM --------------------------------------------------------------------------
REM 双击即可运行：自动检查 Python 与依赖 -> 缺什么装什么 -> 执行打包
REM 命令行用法：一键打包exe.bat nopause   （跑完不等待按键，便于脚本化调用）
REM --------------------------------------------------------------------------
REM 说明：
REM   1. 优先复用项目目录下已有的 .venv；探测到损坏会自动重建
REM   2. 依赖安装走清华 TUNA 镜像，失败自动切阿里云，再失败回退官方 PyPI
REM   3. 全程只在本项目目录内操作，不修改系统 PATH，也不碰系统全局 Python
REM ==========================================================================

setlocal enabledelayedexpansion
cd /d "%~dp0"

set "VENV_DIR=.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "PIP_TUNA=https://pypi.tuna.tsinghua.edu.cn/simple"
set "PIP_TUNA_HOST=pypi.tuna.tsinghua.edu.cn"
set "PIP_ALIYUN=https://mirrors.aliyun.com/pypi/simple"
set "PIP_ALIYUN_HOST=mirrors.aliyun.com"

echo.
echo ================================================================
echo   byte-tools 一键打包 exe
echo   工作目录: %CD%
echo ================================================================
echo.

if not exist "main.py" goto :err_no_app
if not exist "byte-tools.spec" goto :err_no_app

REM ==========================================================================
REM [1/4] 找一个可用的 Python（要求 3.9 及以上，PySide6 6.6+ 的硬性门槛）。
REM       已有可用的 .venv 时这一步只是备用，找不到也不会中断。
REM ==========================================================================
echo [1/4] 查找可用的 Python 3.9+ ...
set "BASE_PY="
where py >nul 2>&1
if %errorlevel% equ 0 for %%V in (3.12 3.13 3.11 3.10 3.9 3) do call :try_interp "py -%%V"
if not defined BASE_PY call :try_interp "python"
if defined BASE_PY (
    echo       找到: !BASE_PY!
) else (
    echo       未找到独立解释器，稍后仅尝试复用已有 .venv
)

REM ==========================================================================
REM [2/4] 检查 / 创建虚拟环境 .venv
REM ==========================================================================
echo.
echo [2/4] 检查 Python 虚拟环境...
if not exist "%VENV_PY%" goto :venv_missing
"%VENV_PY%" -c "import sys" >nul 2>&1
if %errorlevel% equ 0 goto :venv_ready
echo       已有虚拟环境不可用，重建中...
call :create_venv --clear
if exist "%VENV_PY%" goto :venv_ready
goto :err_venv

:venv_missing
if not defined BASE_PY goto :err_no_python
echo       未找到虚拟环境，正在创建 %VENV_DIR% ...
call :create_venv
if exist "%VENV_PY%" goto :venv_ready
goto :err_venv

:venv_ready
set "RUN_PY=%VENV_PY%"
echo       虚拟环境就绪:
"%RUN_PY%" --version
"%RUN_PY%" -m pip --version >nul 2>&1
if %errorlevel% equ 0 goto :venv_pip_done
echo       虚拟环境缺少 pip，执行 ensurepip...
"%RUN_PY%" -m ensurepip --upgrade
:venv_pip_done

REM ==========================================================================
REM [3/4] 检查 / 安装依赖
REM ==========================================================================
echo.
REM --------------------------------------------------------------------------
REM 环境自检：python 的 platform.win32_ver() 会走 WMI。WINMGMT 冷启动时这条调用
REM           可能阻塞几十秒到一两分钟（本机实测），期间脚本看起来就是"执行一半
REM           没反应"。这里做有界探测：先等 15 秒，没结果再明确提示并最多等 120 秒。
REM --------------------------------------------------------------------------
echo.
echo       自检系统 WMI（先等 15 秒）...
"%RUN_PY%" -c "import threading,platform,os;t=threading.Thread(target=lambda:platform.win32_ver(),daemon=True);t.start();t.join(15);os._exit(1 if t.is_alive() else 0)" 2>nul
if %errorlevel% equ 0 goto :wmi_ok
echo       WMI 15 秒没响应，WINMGMT 多半在冷启动。
echo       继续等待唤醒（最多 120 秒，期间不要关窗口）...
"%RUN_PY%" -c "import threading,platform,os;t=threading.Thread(target=lambda:platform.win32_ver(),daemon=True);t.start();t.join(120);os._exit(1 if t.is_alive() else 0)" 2>nul
if %errorlevel% equ 0 goto :wmi_warm
echo.
echo [错误] 本机 WMI 累计等待 135 秒仍无响应，打包无法继续。
echo        PyInstaller 一 import 就会调 platform.win32_ver，那条调用不返回，
echo        现象就是脚本跑到「检查 PyInstaller」之后再无输出。
echo        修复办法（用管理员身份打开 CMD 后逐条执行）：
echo          1. net stop winmgmt
echo          2. net start winmgmt
echo          3. winmgmt /verifyrepository   查看 WMI 仓库是否损坏
echo          4. winmgmt /resetrepository    确认损坏才执行，会重建仓库
echo        改好后重新双击本脚本；期间想看程序本身，可先用「一键启动项目.bat」。
goto :finish_fail
:wmi_warm
echo       WMI 已唤醒（本次等待较久，下次通常秒过）
goto :wmi_done
:wmi_ok
echo       WMI 正常
:wmi_done
echo.
echo [3/4] 检查项目依赖...
"%RUN_PY%" -c "import PySide6, requests" >nul 2>&1
if %errorlevel% neq 0 goto :deps_install
echo       PySide6 / requests 已就绪
goto :deps_runtime_done
:deps_install
echo       缺少 PySide6 / requests，开始安装（清华镜像优先）...
call :pip_install -r requirements.txt
"%RUN_PY%" -c "import PySide6, requests" >nul 2>&1
if %errorlevel% neq 0 goto :err_deps
echo       依赖安装完成
:deps_runtime_done
echo       检查 PyInstaller...
REM 只查落盘文件，不 import：PyInstaller 一 import 就要问 WMI，冷启动时几十秒不返回
if exist "%VENV_DIR%\Lib\site-packages\PyInstaller\__init__.py" goto :pyi_ok
goto :pyi_install
:pyi_ok
echo       已就绪
goto :deps_build_done
:pyi_install
echo       未安装 PyInstaller，开始安装...
call :pip_install pyinstaller
if exist "%VENV_DIR%\Lib\site-packages\PyInstaller\__init__.py" goto :pyi_done_ok
goto :err_deps
:pyi_done_ok
echo       PyInstaller 安装完成
:deps_build_done

REM ==========================================================================
REM [4/4] 打包
REM ==========================================================================
echo.
echo [4/4] 用 PyInstaller 按 byte-tools.spec 打包（约 1-3 分钟，请勿关闭窗口）
echo.
"%RUN_PY%" -m PyInstaller --noconfirm byte-tools.spec
if %errorlevel% neq 0 goto :err_main

if not exist "dist\byte-tools.exe" goto :err_no_dist
for %%F in ("dist\byte-tools.exe") do (
    echo ================================================================
    echo   打包成功: %CD%\dist\byte-tools.exe
    echo   文件大小: %%~zF 字节
    echo   生成时间: %%~tF
    echo   双击 dist 里的 byte-tools.exe 即可运行，也可拷到其他 Win10/11 64 位电脑
    echo ================================================================
)
if /i not "%~1"=="nopause" start "" explorer "%CD%\dist"
goto :done
:err_no_dist
echo [错误] 打包流程结束，但没有找到 dist\byte-tools.exe
goto :finish_fail
:done

echo.
if /i "%~1"=="nopause" exit /b 0
echo 按任意键关闭窗口...
pause >nul
exit /b 0

REM ==========================================================================
REM 子过程
REM ==========================================================================
:try_interp
REM 入参 %~1: 解释器命令（如 py -3.12 / python）；已找到则直接返回
if defined BASE_PY goto :eof
%~1 -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >nul 2>&1
if %errorlevel% equ 0 set "BASE_PY=%~1"
goto :eof

:create_venv
REM 入参 %1: 可选 --clear（覆盖重建已有目录）
if not defined BASE_PY goto :eof
%BASE_PY% -m venv %1 "%VENV_DIR%"
goto :eof

:pip_install
REM 入参 %*: 传给 pip install 的参数（如 -r requirements.txt）
"%RUN_PY%" -m pip install --upgrade pip -i %PIP_TUNA% --trusted-host %PIP_TUNA_HOST% >nul 2>&1
"%RUN_PY%" -m pip install %* -i %PIP_TUNA% --trusted-host %PIP_TUNA_HOST%
if %errorlevel% equ 0 goto :eof
echo       清华镜像失败，改用阿里云镜像...
"%RUN_PY%" -m pip install %* -i %PIP_ALIYUN% --trusted-host %PIP_ALIYUN_HOST%
if %errorlevel% equ 0 goto :eof
echo       阿里云镜像也失败，回退官方 PyPI...
"%RUN_PY%" -m pip install %*
goto :eof

REM ==========================================================================
REM 错误出口
REM ==========================================================================
:err_no_app
echo [错误] 当前目录缺少 byte-tools 的必要文件（main.py 或 byte-tools.spec）。
echo        请把本脚本放在 byte-tools 项目根目录里再运行。
echo        当前目录: %CD%
goto :finish_fail

:err_no_python
echo [错误] 既没有可用的 .venv，也没找到 Python 3.9 及以上版本。
echo        方式一（推荐）：在命令行执行  winget install Python.Python.3.12
echo        方式二：到 https://www.python.org/downloads/windows/ 下载安装，
echo               安装时勾选 Add python.exe to PATH
echo        装好后重新双击本脚本即可。
goto :finish_fail

:err_venv
echo [错误] 创建或重建虚拟环境 %VENV_DIR% 失败。
echo        可以先手工删掉 %VENV_DIR% 目录再重试；完整报错见上方输出。
goto :finish_fail

:err_deps
echo [错误] 依赖安装失败。
echo        原因一：网络不通，换个网络后重试，或手工执行：
echo               %VENV_PY% -m pip install -r requirements.txt
echo        原因二：本机只有过新的 Python（比如 3.14），PySide6 还没有对应轮子。
echo               此时加装一个 3.12 后重试：winget install Python.Python.3.12
goto :finish_fail

:err_main
echo.
echo [错误] 打包失败，退出码: %errorlevel%
echo        请把上面的报错信息一起反馈，方便定位。
goto :finish_fail

:finish_fail
if /i "%~1"=="nopause" exit /b 1
echo.
echo 按任意键关闭窗口...
pause >nul
exit /b 1
