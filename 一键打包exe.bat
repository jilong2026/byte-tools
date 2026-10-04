@echo off
REM ==========================================================================
REM byte-tools one-click exe packaging script.
REM --------------------------------------------------------------------------
REM Double-click to run. Like the launcher it needs nothing from the user: it
REM finds a usable Python, installs one when the machine has none, creates
REM .venv, installs the dependencies and PyInstaller, then builds
REM dist\byte-tools.exe. Pass "nopause" for scripted use.
REM --------------------------------------------------------------------------
REM KEEP THIS FILE PURE ASCII, for the same reason as the launcher: cmd.exe
REM tracks its position in a .bat as a byte offset, and a multibyte file plus a
REM mid-run "chcp 65001" desyncs it, so parsing resumes mid-line, comments and
REM echo text execute as commands, and whole statements disappear. Chinese UI
REM text lives in assets\msg_zh.txt as data and is printed by :say, with the
REM English argument as fallback. Never add non-ASCII bytes to this file.
REM ==========================================================================
setlocal enabledelayedexpansion

REM Capture the OEM codepage before chcp hides it: 936 means a Simplified
REM Chinese console, which is the second signal for choosing Chinese messages.
set "OEM_CP="
for /f "tokens=2 delims=:" %%P in ('chcp 2^>nul') do set "OEM_CP=%%P"
set "OEM_CP=!OEM_CP: =!"
chcp 65001 >nul
title byte-tools packer

cd /d "%~dp0"

set "VENV_DIR=.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "MSG_FILE=assets\msg_zh.txt"
set "PY_VER=3.12.10"
set "PY_FILE=python-%PY_VER%-amd64.exe"
set "PY_SETUP=%TEMP%\byte-tools-%PY_FILE%"
set "PIP_TUNA=https://pypi.tuna.tsinghua.edu.cn/simple"
set "PIP_TUNA_HOST=pypi.tuna.tsinghua.edu.cn"
set "PIP_ALIYUN=https://mirrors.aliyun.com/pypi/simple"
set "PIP_ALIYUN_HOST=mirrors.aliyun.com"
set "ZH=0"

call :detect_lang

echo.
echo ================================================================
call :say hdr_pack "  byte-tools one-click exe packaging"
call :say hdr_2 "  Work dir: {0}" "%CD%"
echo ================================================================
echo.

if not exist "main.py" goto :err_no_app
if not exist "byte-tools.spec" goto :err_no_spec

REM ==========================================================================
REM [1/4] Interpreter. A usable .venv already means this job is done, so check
REM       it first: hunting for or installing an interpreter then would only
REM       waste the user's time and download quota.
REM ==========================================================================
set "VENV_USABLE=0"
if not exist "%VENV_PY%" goto :venv_probe_done
call "%VENV_PY%" -c "import sys;sys.exit(0 if (3,10)<=sys.version_info[:2]<=(3,14) else 1)" >nul 2>&1
if %errorlevel% equ 0 set "VENV_USABLE=1"
:venv_probe_done

call :say step1 "[1/4] Looking for a usable Python 3.10-3.14 ..."
set "BASE_PY="
if "%VENV_USABLE%"=="1" goto :step1_done
call :discover_python
if defined BASE_PY goto :step1_got
call :bootstrap_python
:step1_got
if defined BASE_PY set "BASE_PY_SHOW=%BASE_PY:"=%"
if defined BASE_PY call :say step1_found "      Found: {0}" "!BASE_PY_SHOW!"
:step1_done
if not defined BASE_PY call :say step1_none "      No standalone interpreter, will reuse an existing .venv only"

REM ==========================================================================
REM [2/4] Virtual environment
REM ==========================================================================
echo.
call :say step2 "[2/4] Checking the Python virtual environment ..."
if not exist "%VENV_PY%" goto :venv_missing
if "%VENV_USABLE%"=="1" goto :venv_ready
call :say step2_rebuild "      Existing virtual environment is unusable, rebuilding it ..."
if not defined BASE_PY goto :err_no_python
call :create_venv --clear
if exist "%VENV_PY%" goto :venv_ready
goto :err_venv

:venv_missing
if not defined BASE_PY goto :err_no_python
call :say step2_creating "      No virtual environment, creating {0} ..." "%VENV_DIR%"
call :create_venv
if exist "%VENV_PY%" goto :venv_ready
goto :err_venv

:venv_ready
set "RUN_PY=%VENV_PY%"
call :say step2_ready "      Virtual environment ready:"
call "%RUN_PY%" --version
call "%RUN_PY%" -m pip --version >nul 2>&1
if %errorlevel% equ 0 goto :venv_pip_done
call :say step2_nopip "      pip is missing in the virtual environment, running ensurepip ..."
call "%RUN_PY%" -m ensurepip --upgrade
:venv_pip_done

REM ==========================================================================
REM [3/4] Dependencies
REM --------------------------------------------------------------------------
REM No WMI wait here any more. The old self-check waited 15 seconds and then up
REM to 120 more for platform.win32_ver() to return; WINMGMT cold start makes
REM that call neither return nor fail (25 seconds measured on this machine,
REM 0.1 when warm), so the worst case was standing and watching for 135 seconds
REM before an error. Instead [4/4] runs pyinstaller_no_wmi.py, which replaces
REM the platform WMI query with an immediate OSError, lets the standard library
REM compute the version, and passes the same stub into PyInstaller's isolated
REM child through a sitecustomize on PYTHONPATH. Stubbing the parent alone is
REM not enough: measured 2394 seconds that way, 60 seconds done right.
REM Guard cases: PackagingEntryNoWmi and PackagingChildProcessesNoWmi in
REM bt_startup_tests.py.
REM ==========================================================================
echo.
call :say step3 "[3/4] Checking project dependencies ..."
call "%RUN_PY%" -c "import PySide6, requests" >nul 2>&1
if %errorlevel% neq 0 goto :deps_install
call :say step3_ready "      PySide6 / requests already installed"
goto :deps_build_start
:deps_install
call :say step3_installing "      Installing PySide6 / requests, Tsinghua mirror first ..."
call :pip_install -r requirements.txt
call "%RUN_PY%" -c "import PySide6, requests" >nul 2>&1
if %errorlevel% neq 0 goto :err_deps
call :say step3_done "      Dependencies installed"

:deps_build_start
call :say pyi_check "      Checking PyInstaller ..."
REM Check the file on disk instead of importing it: importing PyInstaller asks
REM WMI, which is the exact thing this script must never block on.
if exist "%VENV_DIR%\Lib\site-packages\PyInstaller\__init__.py" goto :pyi_ok
call :say pyi_installing "      PyInstaller is missing, installing it ..."
call :pip_install pyinstaller
if exist "%VENV_DIR%\Lib\site-packages\PyInstaller\__init__.py" goto :pyi_done_ok
goto :err_deps
:pyi_ok
call :say pyi_ready "      PyInstaller ready"
goto :deps_build_done
:pyi_done_ok
call :say pyi_done "      PyInstaller installed"
:deps_build_done

REM ==========================================================================
REM [4/4] Build
REM ==========================================================================
echo.
call :say step4_pack "[4/4] Packaging with PyInstaller against byte-tools.spec, 1 to 3 minutes, do not close this window"
echo.
call "%RUN_PY%" pyinstaller_no_wmi.py --noconfirm byte-tools.spec
set "RC=%errorlevel%"
if %RC% neq 0 goto :err_main

if not exist "dist\byte-tools.exe" goto :err_no_dist
for %%F in ("dist\byte-tools.exe") do (
    echo ================================================================
    call :say pack_ok_1 "  Built: {0}" "%CD%\dist\byte-tools.exe"
    call :say pack_ok_2 "  Size: {0} bytes" "%%~zF"
    call :say pack_ok_3 "  Built at: {0}" "%%~tF"
    call :say pack_ok_4 "  Double-click dist\byte-tools.exe, or copy it to any Win10/11 64-bit machine"
    echo ================================================================
)
if /i not "%~1"=="nopause" start "" explorer "%CD%\dist"
goto :done
:err_no_dist
call :say err_no_dist "[error] Packaging finished but dist\byte-tools.exe was not found."
goto :finish_fail
:done

echo.
if /i "%~1"=="nopause" exit /b 0
call :say press_key "Press any key to close this window ..."
pause >nul
exit /b 0

REM ==========================================================================
REM Messages
REM ==========================================================================
:detect_lang
REM Chinese when the user locale is a Chinese LCID, or when the console is a
REM Chinese codepage. Any failure here leaves ZH=0 and the script speaks
REM English - the safe direction, since English needs no extra file. reg.exe is
REM the only external command used: piped filters such as "find" get shadowed
REM by the GNU find on a Git Bash PATH, which then fails on the /i argument.
set "LOCALE_LCID="
for /f "tokens=3" %%V in ('reg query "HKCU\Control Panel\International" /v Locale 2^>nul') do set "LOCALE_LCID=%%V"
if defined LOCALE_LCID set "LOCALE_LCID=!LOCALE_LCID:~-4!"
for %%S in (0804 0404 0C04 1004) do if /i "!LOCALE_LCID!"=="%%S" set "ZH=1"
if "%OEM_CP%"=="936" set "ZH=1"
if "%OEM_CP%"=="950" set "ZH=1"
if "%ZH%"=="0" goto :eof
if not exist "%MSG_FILE%" set "ZH=0"
if "%ZH%"=="0" goto :eof
REM Message values are read as data, so their bytes never reach the batch parser.
for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%MSG_FILE%") do set "MSG_%%A=%%B"
goto :eof

:say
REM %~1 = key in assets\msg_zh.txt, %~2 = English fallback, %~3 = value for {0}.
REM Keep the English argument free of cmd metacharacters: it is substituted at
REM parse time, while a table value is not, so parentheses are fine in Chinese.
set "T="
if defined MSG_%~1 set "T=!MSG_%~1!"
if not defined MSG_%~1 set "T=%~2"
if not "%~3"=="" set "T=!T:{0}=%~3!"
echo !T!
goto :eof

REM ==========================================================================
REM Interpreter discovery. The one-click contract says this script installs
REM Python itself, so it has to miss as little as possible.
REM ==========================================================================
:discover_python
if defined BASE_PY goto :eof
where py >nul 2>&1
if %errorlevel% neq 0 goto :disc_no_launcher
for %%V in (3.12 3.13 3.11 3.10 3.14) do call :try_cmd "py -%%V"
:disc_no_launcher
if defined BASE_PY goto :eof
for %%V in (python python3) do call :try_cmd %%V
if defined BASE_PY goto :eof
for %%V in (3.12 3.13 3.11 3.10 3.14 312 313 311 310 314) do call :try_exe "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
REM These sweeps catch what fixed names cannot: an install that landed as
REM "Python 3.12", one that never touched PATH, and a copy that winget or the
REM installer below just placed there under a slightly different folder name.
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\?*") do call :try_exe "%%D\python.exe"
for /d %%D in ("%ProgramFiles%\Python*") do call :try_exe "%%D\python.exe"
for /d %%D in ("%ProgramFiles(x86)%\Python*") do call :try_exe "%%D\python.exe"
goto :eof

:try_cmd
REM %~1 = interpreter invocation, e.g. py -3.12 or python.
REM BASE_PY is stored unquoted here and quoted by :try_exe. That split is
REM deliberate: the value is expanded as bare %BASE_PY% by :create_venv, so a
REM command with arguments must not be wrapped in quotes and a path containing
REM spaces must be.
if defined BASE_PY goto :eof
call %~1 -c "import sys;sys.exit(0 if (3,10)<=sys.version_info[:2]<=(3,14) else 1)" >nul 2>&1
if %errorlevel% equ 0 set "BASE_PY=%~1"
goto :eof

:try_exe
REM %~1 = absolute python.exe path. 3.10-3.14 only, because PySide6 6.11
REM declares requires_python >=3.10,<3.15: outside that range the dependency
REM step is a dead end the user would then be asked to fix by hand.
if defined BASE_PY goto :eof
if not exist "%~1" goto :eof
call "%~1" -c "import sys;sys.exit(0 if (3,10)<=sys.version_info[:2]<=(3,14) else 1)" >nul 2>&1
if %errorlevel% equ 0 set BASE_PY="%~1"
goto :eof

REM ==========================================================================
REM Installing Python when the machine has none
REM ==========================================================================
:bootstrap_python
if defined BASE_PY goto :eof
set "WINGET_TRIED=0"
set "WINGET_EXE="
where winget >nul 2>&1
if %errorlevel% equ 0 set "WINGET_EXE=winget"
if defined WINGET_EXE goto :boot_winget
REM winget lives in WindowsApps, which is absent from some PATHs even when the
REM file itself is installed, so "where" alone would skip the cheapest route.
if exist "%LOCALAPPDATA%\Microsoft\WindowsApps\winget.exe" set "WINGET_EXE=%LOCALAPPDATA%\Microsoft\WindowsApps\winget.exe"
:boot_winget
if not defined WINGET_EXE goto :boot_download
set "WINGET_TRIED=1"
call :say boot_winget "      No usable Python found, installing 3.12 through winget, user scope, no admin ..."
call "%WINGET_EXE%" install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements >nul 2>&1
call :discover_python
if defined BASE_PY goto :boot_report
:boot_download
if "%WINGET_TRIED%"=="0" goto :boot_no_winget
call :say boot_winget_fail "      winget gave no usable Python, downloading the official installer ..."
goto :boot_fetch
:boot_no_winget
call :say boot_no_winget "      No winget on this machine, downloading the official installer ..."
:boot_fetch
del /q "%PY_SETUP%" >nul 2>&1
set "SETUP_OK=0"
REM Rule R1 applies to this download as well: domestic mirrors first, python.org
REM last. One source is not a download plan.
call :fetch_installer https://repo.huaweicloud.com/python/%PY_VER%/%PY_FILE%
call :fetch_installer https://registry.npmmirror.com/-/binary/python/%PY_VER%/%PY_FILE%
call :fetch_installer https://www.python.org/ftp/python/%PY_VER%/%PY_FILE%
if "%SETUP_OK%"=="0" goto :boot_report
call :say boot_dl_ok "      Installer downloaded, size check passed"
call :say boot_installing "      Installing silently, about a minute, please wait ..."
REM PrependPath=0 on purpose: discovery reads the install directory, so this
REM never has to touch PATH and the promise of not modifying the system holds.
call "%PY_SETUP%" /quiet InstallAllUsers=0 PrependPath=0 Include_launcher=0 Include_test=0
set "SETUP_RC=%errorlevel%"
REM 0 means installed, 3010 means installed and a reboot was requested. Anything
REM else is a hard failure: no new interpreter can exist, so do not make the
REM user watch thirty seconds of re-scanning that cannot succeed.
if not "%SETUP_RC%"=="0" if not "%SETUP_RC%"=="3010" goto :boot_cleanup
call :wait_for_python 30
:boot_cleanup
REM Keep the installer when the run failed, so the next double-click does not
REM download 27 MB again; drop it when it worked, it is just litter by then.
if defined BASE_PY del /q "%PY_SETUP%" >nul 2>&1
:boot_report
if not defined BASE_PY call :say boot_failed "      Automatic install failed: winget and all three download sources."
goto :eof

:fetch_installer
REM %* = URL of the official installer.
if "%SETUP_OK%"=="1" goto :eof
call :say boot_try "      Trying download source: {0}" "%*"
del /q "%PY_SETUP%" >nul 2>&1
where curl >nul 2>&1
if %errorlevel% neq 0 goto :fetch_ps
call curl -fL --retry 2 --connect-timeout 20 -m 900 -o "%PY_SETUP%" %*
goto :fetch_check
:fetch_ps
REM curl ships with Windows 10 1803 and newer; PowerShell covers everything else.
call powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop';(New-Object Net.WebClient).DownloadFile('%*','%PY_SETUP%')"
:fetch_check
if not exist "%PY_SETUP%" goto :eof
set "SZ=0"
for %%F in ("%PY_SETUP%") do set "SZ=%%~zF"
if %SZ% GEQ 5000000 goto :fetch_ok
REM Never trust a download that cannot be size-checked: a mirror 404 page or a
REM truncated file installs into a broken interpreter that is harder to debug.
call :say boot_dl_bad "      This source returned an incomplete file, trying the next one ..."
del /q "%PY_SETUP%" >nul 2>&1
goto :eof
:fetch_ok
set "SETUP_OK=1"
goto :eof

:wait_for_python
REM %~1 = seconds. The installer can return before every file has reached disk,
REM and antivirus scanning widens that gap, so re-scan inside a bound.
set "WAIT_LEFT=%~1"
:wait_loop
call :discover_python
if defined BASE_PY goto :eof
if %WAIT_LEFT% LEQ 0 goto :eof
set /a WAIT_LEFT-=1
ping -n 2 -w 1000 127.0.0.1 >nul
goto :wait_loop

REM ==========================================================================
REM Subroutines
REM ==========================================================================
:create_venv
REM %1 = optional --clear to rebuild in place.
if not defined BASE_PY goto :eof
call %BASE_PY% -m venv %1 "%VENV_DIR%"
goto :eof

:pip_install
REM %* = arguments for pip install, e.g. -r requirements.txt
call "%RUN_PY%" -m pip install --upgrade pip -i %PIP_TUNA% --trusted-host %PIP_TUNA_HOST% >nul 2>&1
call "%RUN_PY%" -m pip install %* -i %PIP_TUNA% --trusted-host %PIP_TUNA_HOST%
if %errorlevel% equ 0 goto :eof
call :say step3_2 "      Tsinghua mirror failed, switching to Aliyun ..."
call "%RUN_PY%" -m pip install %* -i %PIP_ALIYUN% --trusted-host %PIP_ALIYUN_HOST%
if %errorlevel% equ 0 goto :eof
call :say step3_3 "      Aliyun failed too, falling back to the official PyPI ..."
call "%RUN_PY%" -m pip install %*
goto :eof

REM ==========================================================================
REM Error exits. Reaching :err_no_python now means winget and three download
REM sources all failed, so the manual hint is a last resort, not the plan.
REM ==========================================================================
:err_no_app
call :say err_no_app_1 "[error] This directory does not contain the byte-tools project."
call :say err_no_app_2 "        Put this script in the byte-tools project root and run it again."
call :say err_no_app_3 "        Current directory: {0}" "%CD%"
goto :finish_fail

:err_no_spec
call :say err_no_spec "[error] byte-tools.spec is missing, check this script sits in the project root."
goto :finish_fail

:err_no_python
call :say err_no_python_1 "[error] Could not prepare Python automatically."
call :say err_no_python_2 "        Tried: winget, Huawei Cloud mirror, npmmirror, then python.org."
call :say err_no_python_3 "        Most likely the network is blocked. Restore it and double-click again."
call :say err_no_python_4 "        Only if that still fails, install Python 3.12 by hand from python.org."
goto :finish_fail

:err_venv
call :say err_venv_1 "[error] Creating or rebuilding the virtual environment {0} failed." "%VENV_DIR%"
call :say err_venv_2 "        Delete the {0} folder by hand and run this script again. Full log is above." "%VENV_DIR%"
goto :finish_fail

:err_deps
call :say err_deps_1 "[error] Dependency installation failed."
call :say err_deps_2 "        Reason one: the network. Retry, or run this by hand:"
call :say err_deps_3 "          {0} -m pip install -r requirements.txt" "%VENV_PY%"
call :say err_deps_4 "        Reason two: not enough free disk, PySide6 needs about 1 GB."
goto :finish_fail

:err_main
call :say err_pack_1 "[error] Packaging failed with exit code {0}." "%RC%"
call :say err_pack_2 "        Please report the output above so this can be traced."
goto :finish_fail

:finish_fail
if /i "%~1"=="nopause" exit /b 1
echo.
call :say press_key "Press any key to close this window ..."
pause >nul
exit /b 1
