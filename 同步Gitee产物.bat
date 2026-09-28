@echo off
chcp 65001 >nul
title byte-tools sync to Gitee
REM ==========================================================================
REM byte-tools: sync release artifacts to Gitee (Windows version)
REM --------------------------------------------------------------------------
REM Windows counterpart of the sync-gitee .sh script (that one runs in CI on Linux).
REM Same three guarantees:
REM   retry on network errors (curl --retry) - overseas runners sometimes hit
REM     curl(35) SSL_ERROR_SYSCALL when calling gitee.com:443
REM   idempotent - reuse an existing Release, skip already uploaded attachments
REM   verify after upload - fail if any whitelisted artifact is missing
REM
REM Usage (command line):
REM   this-script.bat v1.0.2 <GiteeToken> [assets_dir] [nopause]
REM Usage (double click):
REM   prompts for tag and token; assets dir defaults to assets
REM
REM Prepare the artifacts first, e.g.:
REM   gh release download v1.0.2 --dir assets --clobber
REM
REM Requires: curl.exe (bundled with Windows 10 1803+) and PowerShell 5.1+
REM Note: this file is intentionally ASCII-only. UTF-8 batch files are parsed
REM       as GBK by cmd.exe, which corrupts non-ASCII text.
REM ==========================================================================

setlocal enabledelayedexpansion
cd /d "%~dp0"

set "GITEE_OWNER=jack_liujilong"
set "GITEE_REPO=byte-tools"
set "API_BASE=https://gitee.com/api/v5/repos/%GITEE_OWNER%/%GITEE_REPO%"
set "RELEASE_PAGE=https://gitee.com/%GITEE_OWNER%/%GITEE_REPO%/releases"

set "TOKEN_ENV=%GITEE_TOKEN%"
set "TAG_NAME=%~1"
set "GITEE_TOKEN=%~2"
set "ASSETS_DIR=%~3"

if not defined ASSETS_DIR set "ASSETS_DIR=assets"
if not defined GITEE_TOKEN set "GITEE_TOKEN=%TOKEN_ENV%"

REM Pass nopause as the 4th arg (or set NO_PAUSE=1) to skip the final pause
if /i "%~4"=="nopause" set "NO_PAUSE=1"
if /i "%NO_PAUSE%"=="1" set "NO_PAUSE=1"

set "TMPDIR=%TEMP%\bt_gitee_sync"
if not exist "%TMPDIR%" mkdir "%TMPDIR%" >nul 2>nul

echo.
echo ================================================================
echo   byte-tools sync to Gitee
echo   repo: %GITEE_OWNER%/%GITEE_REPO%
echo   dir : %CD%
echo ================================================================
echo.

REM ---- interactive fallback (when double clicked) ----
if not defined TAG_NAME set /p TAG_NAME="tag (e.g. v1.0.2): "
if not defined GITEE_TOKEN set /p GITEE_TOKEN="Gitee token: "
if not defined TAG_NAME goto :err_args
if not defined GITEE_TOKEN goto :err_args

REM ---- dependency check: curl.exe ----
where curl.exe >nul 2>nul
if errorlevel 1 goto :err_curl

REM ---- curl retry flags: --retry-all-errors only exists on newer builds ----
set "RETRY_OPT=--retry 3 --retry-delay 5"
curl.exe --help all 2>nul | findstr /i "retry-all-errors" >nul
if not errorlevel 1 set "RETRY_OPT=%RETRY_OPT% --retry-all-errors"

REM ---- assets dir check ----
if not exist "%ASSETS_DIR%\" goto :err_dir

REM ==========================================================================
REM [1/3] get-or-create Gitee Release (idempotent: reuse if exists)
REM ==========================================================================
echo [1/3] get-or-create Gitee Release %TAG_NAME% ...

curl.exe -sS %RETRY_OPT% --connect-timeout 20 --max-time 300 "%API_BASE%/releases/tags/%TAG_NAME%" -o "%TMPDIR%\rel.json"
if errorlevel 1 goto :err_net

set "RELEASE_ID="
powershell -NoProfile -Command "try { $j = Get-Content -Raw -Encoding UTF8 '%TMPDIR%\rel.json' | ConvertFrom-Json; if ($j.id) { $j.id | Out-File -Encoding ascii '%TMPDIR%\id.txt' } } catch {}"
if exist "%TMPDIR%\id.txt" set /p RELEASE_ID=<"%TMPDIR%\id.txt"
if exist "%TMPDIR%\id.txt" del "%TMPDIR%\id.txt" >nul 2>nul

if defined RELEASE_ID (
  echo   release exists, reuse ID: %RELEASE_ID%
) else (
  echo   creating release for tag %TAG_NAME% ...
  curl.exe -sS %RETRY_OPT% --connect-timeout 20 --max-time 300 -X POST "%API_BASE%/releases" -F "access_token=%GITEE_TOKEN%" -F "tag_name=%TAG_NAME%" -F "name=%TAG_NAME%" -F "body=byte-tools release %TAG_NAME%" -F "target_commitish=master" -o "%TMPDIR%\create.json"
  if errorlevel 1 goto :err_net

  set "RELEASE_ID="
  powershell -NoProfile -Command "try { $j = Get-Content -Raw -Encoding UTF8 '%TMPDIR%\create.json' | ConvertFrom-Json; if ($j.id) { $j.id | Out-File -Encoding ascii '%TMPDIR%\id.txt' } } catch {}"
  if exist "%TMPDIR%\id.txt" set /p RELEASE_ID=<"%TMPDIR%\id.txt"
  if exist "%TMPDIR%\id.txt" del "%TMPDIR%\id.txt" >nul 2>nul

  if not defined RELEASE_ID (
    echo   create failed, raw response:
    type "%TMPDIR%\create.json"
    goto :fail
  )
  echo   created, release ID: %RELEASE_ID%
)

REM ==========================================================================
REM [2/3] upload artifacts (skip names already attached)
REM ==========================================================================
echo [2/3] upload artifacts ...

curl.exe -sS %RETRY_OPT% --connect-timeout 20 --max-time 300 "%API_BASE%/releases/%RELEASE_ID%" -o "%TMPDIR%\rel2.json"
if errorlevel 1 goto :err_net

powershell -NoProfile -Command "try { $j = Get-Content -Raw -Encoding UTF8 '%TMPDIR%\rel2.json' | ConvertFrom-Json; if ($j.assets) { $j.assets | ForEach-Object { $_.name } | Out-File -Encoding ascii '%TMPDIR%\assets.txt' } } catch {}"
if not exist "%TMPDIR%\assets.txt" type nul > "%TMPDIR%\assets.txt"

set /a UPLOADED=0
set /a SKIPPED=0
set /a IGNORED=0

for %%F in ("%ASSETS_DIR%\*") do (
  set "NAME=%%~nxF"
  set "ALLOWED=0"
  for %%W in (byte-tools.exe byte-tools-windows-x64.zip byte-tools-macos-arm64.zip byte-tools-linux-x64) do (
    if /i "!NAME!"=="%%W" set "ALLOWED=1"
  )
  if "!ALLOWED!"=="0" (
    echo   -- skip non-artifact: !NAME!
    set /a IGNORED+=1
  ) else (
    findstr /i /x /c:"!NAME!" "%TMPDIR%\assets.txt" >nul
    if not errorlevel 1 (
      echo   == already exists, skip: !NAME!
      set /a SKIPPED+=1
    ) else (
      if %%~zF GTR 104857600 (
        echo   error: !NAME! exceeds Gitee 100MB attachment limit
        goto :fail
      )
      echo   -^> uploading !NAME! ...
      curl.exe -sS %RETRY_OPT% --connect-timeout 20 --max-time 1800 -X POST "%API_BASE%/releases/%RELEASE_ID%/attach_files" -F "access_token=%GITEE_TOKEN%" -F "file=@%%F" -o "%TMPDIR%\upload.json"
      if errorlevel 1 goto :err_net

      powershell -NoProfile -Command "try { $j = Get-Content -Raw -Encoding UTF8 '%TMPDIR%\upload.json' | ConvertFrom-Json; if ($j.browser_download_url) { $j.browser_download_url | Out-File -Encoding ascii '%TMPDIR%\url.txt' } elseif ($j.attach_file_url) { $j.attach_file_url | Out-File -Encoding ascii '%TMPDIR%\url.txt' } } catch {}"
      set "ATTACH_URL="
      if exist "%TMPDIR%\url.txt" set /p ATTACH_URL=<"%TMPDIR%\url.txt"
      if exist "%TMPDIR%\url.txt" del "%TMPDIR%\url.txt" >nul 2>nul

      if not defined ATTACH_URL (
        echo   upload failed, raw response:
        type "%TMPDIR%\upload.json"
        goto :fail
      )
      echo      ok: !ATTACH_URL!
      set /a UPLOADED+=1
    )
  )
)

REM ==========================================================================
REM [3/3] verify: every whitelisted artifact must be attached
REM ==========================================================================
echo [3/3] verify attachments ...

curl.exe -sS %RETRY_OPT% --connect-timeout 20 --max-time 300 "%API_BASE%/releases/%RELEASE_ID%" -o "%TMPDIR%\rel3.json"
if errorlevel 1 goto :err_net

powershell -NoProfile -Command "try { $j = Get-Content -Raw -Encoding UTF8 '%TMPDIR%\rel3.json' | ConvertFrom-Json; $have = @(); if ($j.assets) { $have = @($j.assets | ForEach-Object { $_.name }) }; $want = @('byte-tools.exe','byte-tools-windows-x64.zip','byte-tools-macos-arm64.zip','byte-tools-linux-x64'); $miss = @($want | Where-Object { $have -notcontains $_ }); if ($miss.Count -eq 0) { 'OK' | Out-File -Encoding ascii '%TMPDIR%\chk.txt' } else { ('MISSING:' + ($miss -join ',')) | Out-File -Encoding ascii '%TMPDIR%\chk.txt' } } catch { 'UNKNOWN' | Out-File -Encoding ascii '%TMPDIR%\chk.txt' }"

set "CHK="
if exist "%TMPDIR%\chk.txt" set /p CHK=<"%TMPDIR%\chk.txt"

if "%CHK%"=="OK" (
  echo   verified: all 4 artifacts present
) else if "%CHK%"=="UNKNOWN" (
  echo   warning: cannot parse asset list, check %RELEASE_PAGE%/%TAG_NAME% manually
) else (
  echo   error: missing %CHK%
  goto :fail
)

echo.
echo done: uploaded %UPLOADED%, skipped %SKIPPED%, ignored %IGNORED%
echo Gitee Release: %RELEASE_PAGE%/%TAG_NAME%
echo.
if not defined NO_PAUSE pause
exit /b 0

:err_args
echo error: missing tag or Gitee token.
echo usage: sync.bat v1.0.2 ^<token^> [assets_dir] [nopause]
goto :fail_nopause

:err_curl
echo error: curl.exe not found. Windows 10 1803+ bundles it.
goto :fail_nopause

:err_dir
echo error: assets dir not found: %ASSETS_DIR%
echo run first: gh release download %TAG_NAME% --dir %ASSETS_DIR% --clobber
goto :fail_nopause

:err_net
echo.
echo error: Gitee request failed (network). This script is idempotent, just rerun it.
goto :fail

:fail
echo.
echo sync incomplete. Fix the issue and rerun - already uploaded files are skipped.
if not defined NO_PAUSE pause
exit /b 1

:fail_nopause
if not defined NO_PAUSE pause
exit /b 1
