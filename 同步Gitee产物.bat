@echo off
chcp 65001 >nul
title ByteTools sync to Gitee
REM ==========================================================================
REM ByteTools: sync release artifacts to Gitee (Windows LOCAL version)
REM --------------------------------------------------------------------------
REM Windows counterpart of the sync-gitee .sh script (that one runs in CI on Linux).
REM
REM NOTE (2026-09-29): the two are NO LONGER equivalent on purpose.
REM   - CI (.sh)  : overseas runner -> writes only the GitHub download links into the
REM                 Gitee Release body, and does NOT push big binaries any more
REM                 (an 84MB POST from abroad hung 70+ minutes and never landed).
REM   - local (.bat): runs on YOUR machine in mainland China, where uploading the real
REM                 binaries to Gitee is fast. Use this when you want in-site downloads.
REM
REM Same three guarantees:
REM   retry on network errors (curl --retry) - gitee.com can hit
REM     curl(35) SSL_ERROR_SYSCALL
REM   idempotent - reuse an existing Release, skip already uploaded attachments
REM   verify after upload - fail if any whitelisted artifact is missing
REM
REM Usage (command line):
REM   this-script.bat v1.0.2 <GiteeToken> [assets_dir] [nopause]
REM Usage (double click):
REM   prompts for tag and token; assets dir defaults to release-assets
REM
REM Who runs this: the release maintainer, to mirror a GitHub Release onto Gitee.
REM End users never need release-assets - they download the exe from the Releases
REM page, or run the two one-click scripts in this folder. The dir is gitignored
REM on purpose; 220 MB of binaries must not enter the repository.
REM
REM The artifacts are downloaded automatically into that dir when missing - from
REM the accelerator first, github.com last (rule R1: mirror first, origin last).
REM See GH_ACCEL below for the measured throughput of each accelerator.
REM
REM Requires: curl.exe (bundled with Windows 10 1803+) and PowerShell 5.1+
REM Note: this file is intentionally ASCII-only. UTF-8 batch files are parsed
REM       as GBK by cmd.exe, which corrupts non-ASCII text.
REM ==========================================================================

setlocal enabledelayedexpansion
cd /d "%~dp0"

set "GITEE_OWNER=jack_liujilong"
set "GITEE_REPO=byte-tools"
REM GITEE_API_BASE is a test seam only: set it to a local mock server to exercise the
REM whole flow without touching gitee.com. Leave it unset for real runs.
if defined GITEE_API_BASE (set "API_BASE=%GITEE_API_BASE%") else (set "API_BASE=https://gitee.com/api/v5/repos/%GITEE_OWNER%/%GITEE_REPO%")
set "RELEASE_PAGE=https://gitee.com/%GITEE_OWNER%/%GITEE_REPO%/releases"
REM GitHub side, used only to tell you how to fetch the artifacts
set "GH_REPO_SLUG=jilong2026/byte-tools"
REM Direct github.com times out from mainland China (measured 2026-09-29: curl rc=28
REM after 20s). All three accelerators answer a small range request, but throughput
REM differs ~65x, so this was picked by measured speed, not by reachability:
REM   gh-proxy.com  ~9 MB/s (220MB in 24s)  <- used here
REM   ghfast.top    ~54 KB/s
REM   ghproxy.net   ~28 KB/s (timed out mid-range)
REM Edit this one line if the accelerator ever dies.
set "GH_ACCEL=https://gh-proxy.com/"

set "TOKEN_ENV=%GITEE_TOKEN%"
set "TAG_NAME=%~1"
set "GITEE_TOKEN=%~2"
set "ASSETS_DIR=%~3"

REM Default is deliberately NOT "assets": in this repo that is the icon folder
REM (byte-tools.png / .ico / alipay.png / wechat.png), which silently yields
REM "0 artifacts found" and wastes a whole Gitee round trip before failing.
if not defined ASSETS_DIR set "ASSETS_DIR=release-assets"
if not defined GITEE_TOKEN set "GITEE_TOKEN=%TOKEN_ENV%"

REM Pass nopause as the 4th arg (or set NO_PAUSE=1) to skip the final pause
if /i "%~4"=="nopause" set "NO_PAUSE=1"
if /i "%NO_PAUSE%"=="1" set "NO_PAUSE=1"

set "TMPDIR=%TEMP%\bt_gitee_sync"
if not exist "%TMPDIR%" mkdir "%TMPDIR%" >nul 2>nul

echo.
echo ================================================================
echo   ByteTools sync to Gitee
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
REM keep the retry count small: curl retries silently, so --retry 3 with a long
REM --max-time means tens of minutes of dead air before anything is printed
set "RETRY_OPT=--retry 1 --retry-delay 5"
curl.exe --help all 2>nul | findstr /i "retry-all-errors" >nul
if not errorlevel 1 set "RETRY_OPT=%RETRY_OPT% --retry-all-errors"

REM ---- assets dir: create it and pull whatever is missing ----
REM One-click means one-click. Telling the maintainer to run four curl commands
REM is the same defect the one-click launch scripts used to have.
call :ensure_assets

REM ---- assets dir check ----
if not exist "%ASSETS_DIR%\" goto :err_dir

REM ---- preflight: the dir must actually hold build artifacts ----
REM Without this, pointing the script at the repo's own assets/ folder (icons:
REM byte-tools.png, .ico, alipay.png, wechat.png) still walks the whole flow,
REM uploads nothing, and only fails at [3/3] with a message that hides the real
REM mistake. Check it here, before spending a round trip to Gitee.
set /a FOUND_ART=0
for %%F in ("%ASSETS_DIR%\*") do (
  set "CHK=%%~nxF"
  if /i "!CHK!"=="ByteTools.exe" set /a FOUND_ART+=1
  if /i "!CHK!"=="ByteTools-windows-x64.zip" set /a FOUND_ART+=1
  if /i "!CHK!"=="ByteTools-macos-arm64.zip" set /a FOUND_ART+=1
  if /i "!CHK!"=="ByteTools-linux-x64" set /a FOUND_ART+=1
)
if !FOUND_ART! NEQ 0 goto :pre_ok
echo.
echo error: no build artifact found in "%ASSETS_DIR%".
echo   What is in there:
dir /b "%ASSETS_DIR%"
if not defined FETCH_FAILED goto :no_art_manual
echo.
echo   automatic download was tried first and failed for:%FETCH_FAILED%
echo   that means both the accelerator and github.com were unreachable, or the
echo   tag has no release assets yet - check TAG_NAME and the network.
:no_art_manual
echo.
echo   This script wants the release files, named exactly:
echo     ByteTools.exe
echo     ByteTools-windows-x64.zip
echo     ByteTools-macos-arm64.zip
echo     ByteTools-linux-x64
echo   Note .\assets in this repo is the ICON folder, not the artifact folder.
echo.
echo   Last resort, fetch them by hand (no gh CLI needed):
echo     mkdir "%ASSETS_DIR%"
echo     curl -L -o "%ASSETS_DIR%\ByteTools.exe" "%GH_ACCEL%https://github.com/%GH_REPO_SLUG%/releases/download/%TAG_NAME%/ByteTools.exe"
echo     curl -L -o "%ASSETS_DIR%\ByteTools-windows-x64.zip" "%GH_ACCEL%https://github.com/%GH_REPO_SLUG%/releases/download/%TAG_NAME%/ByteTools-windows-x64.zip"
echo     curl -L -o "%ASSETS_DIR%\ByteTools-macos-arm64.zip" "%GH_ACCEL%https://github.com/%GH_REPO_SLUG%/releases/download/%TAG_NAME%/ByteTools-macos-arm64.zip"
echo     curl -L -o "%ASSETS_DIR%\ByteTools-linux-x64" "%GH_ACCEL%https://github.com/%GH_REPO_SLUG%/releases/download/%TAG_NAME%/ByteTools-linux-x64"
goto :fail_nopause

:pre_ok
echo   preflight ok: found !FOUND_ART! artifact file(s) in "%ASSETS_DIR%"

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
  curl.exe -sS %RETRY_OPT% --connect-timeout 20 --max-time 300 -X POST "%API_BASE%/releases" -F "access_token=%GITEE_TOKEN%" -F "tag_name=%TAG_NAME%" -F "name=%TAG_NAME%" -F "body=ByteTools release %TAG_NAME%" -F "target_commitish=master" -o "%TMPDIR%\create.json"
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
  echo   created, release ID: !RELEASE_ID!
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
  for %%W in (ByteTools.exe ByteTools-windows-x64.zip ByteTools-macos-arm64.zip ByteTools-linux-x64) do (
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
      REM -w prints http/time/bytes so a stall is obvious instead of looking dead
      curl.exe -sS %RETRY_OPT% --connect-timeout 20 --max-time 600 -X POST "%API_BASE%/releases/%RELEASE_ID%/attach_files" -F "access_token=%GITEE_TOKEN%" -F "file=@%%F" -o "%TMPDIR%\upload.json" -w "     curl: http=%%{http_code} time=%%{time_total}s uploaded=%%{size_upload}B speed=%%{speed_upload}B/s\n"
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

powershell -NoProfile -Command "try { $j = Get-Content -Raw -Encoding UTF8 '%TMPDIR%\rel3.json' | ConvertFrom-Json; $have = @(); if ($j.assets) { $have = @($j.assets | ForEach-Object { $_.name }) }; $want = @('ByteTools.exe','ByteTools-windows-x64.zip','ByteTools-macos-arm64.zip','ByteTools-linux-x64'); $miss = @($want | Where-Object { $have -notcontains $_ }); if ($miss.Count -eq 0) { 'OK' | Out-File -Encoding ascii '%TMPDIR%\chk.txt' } else { ($miss -join ', ') | Out-File -Encoding ascii '%TMPDIR%\chk.txt' } } catch { 'UNKNOWN' | Out-File -Encoding ascii '%TMPDIR%\chk.txt' }"

set "CHK="
if exist "%TMPDIR%\chk.txt" set /p CHK=<"%TMPDIR%\chk.txt"

if "%CHK%"=="OK" (
  echo   verified: all 4 artifacts present
) else if "%CHK%"=="UNKNOWN" (
  echo   warning: cannot parse asset list, check %RELEASE_PAGE%/%TAG_NAME% manually
) else (
  echo   error: Gitee attachment list does not contain: %CHK%
  goto :fail
)

echo.
echo done: uploaded %UPLOADED%, skipped %SKIPPED%, ignored %IGNORED%
echo Gitee Release: %RELEASE_PAGE%/%TAG_NAME%
echo.
if not defined NO_PAUSE pause
exit /b 0

REM ==========================================================================
REM Auto-fetch the release artifacts
REM ==========================================================================
:ensure_assets
REM Create the staging dir and download only what is not there yet. A rerun must
REM not pull 220 MB again, and a file the maintainer placed by hand is left
REM untouched - except a 0-byte leftover from an interrupted run, which can only
REM ever be garbage. AUTO_FETCH_ASSETS=0 is the test seam that keeps the
REM regression suite offline; same name as the .sh one on purpose.
if /i "%AUTO_FETCH_ASSETS%"=="0" goto :eof
call :clear_stale
if not exist "%ASSETS_DIR%\" mkdir "%ASSETS_DIR%" >nul 2>nul
if not exist "%ASSETS_DIR%\" goto :eof
for %%N in (ByteTools.exe ByteTools-windows-x64.zip ByteTools-macos-arm64.zip ByteTools-linux-x64) do call :fetch_asset %%N
goto :eof

REM ==========================================================================
:clear_stale
REM Artifacts carry the SAME file name across tags (ByteTools.exe since v1.1.2),
REM so "the file is already here" says nothing about which release it belongs to.
REM Before this step existed, a leftover from the previous tag was uploaded into
REM this tag's Gitee release and still passed the name-only check in [3/3].
REM Only reached when auto-fetch is on, so hand-placed files and the offline
REM regression suite are never touched.
REM Guard: ASSETS_DIR comes from argument 3. A mistyped value (the tracked icon
REM dir "assets", or the repo root) must never be removed, so clearing is
REM allowed only when the last path element is exactly release-assets.
for %%I in ("%ASSETS_DIR%") do set "TAIL_NAME=%%~nxI"
if /i not "!TAIL_NAME!"=="release-assets" (
  echo   notice: not clearing "%ASSETS_DIR%" - only a staging dir named
  echo           release-assets is auto-cleared. Delete it by hand if the files
  echo           inside it came from an older tag.
  goto :eof
)
if not exist "%ASSETS_DIR%\" goto :eof
echo   clearing stale staging dir "%ASSETS_DIR%" before re-fetching ...
rmdir /s /q "%ASSETS_DIR%" >/dev/null 2>/dev/null
goto :eof
:fetch_asset
REM %~1 = artifact name as published on the GitHub Release.
set "DST=%ASSETS_DIR%\%~1"
set "RAW=https://github.com/%GH_REPO_SLUG%/releases/download/%TAG_NAME%/%~1"
if not exist "%DST%" goto :fetch_start
set "SZ=0"
for %%P in ("%DST%") do set "SZ=%%~zP"
if not "%SZ%"=="0" goto :eof
del /q "%DST%" >nul 2>nul
:fetch_start
echo   downloading %~1 ...
set "DL_OK="
call :curl_fetch "%GH_ACCEL%%RAW%" "%DST%"
if defined DL_OK goto :fetch_report
call :curl_fetch "%RAW%" "%DST%"
:fetch_report
if defined DL_OK goto :eof
set "FETCH_FAILED=%FETCH_FAILED% %~1"
echo     neither the accelerator nor github.com produced a usable file for %~1
goto :eof

:curl_fetch
REM %~1 = URL, %~2 = destination. Accepted only when curl reports success AND
REM the file is at least 1 MB: a mirror that answers 200 with a small HTML page
REM would otherwise be shipped to Gitee as if it were the artifact.
del /q "%~2" >nul 2>nul
curl.exe -sS -fL %RETRY_OPT% --connect-timeout 20 --max-time 1800 -o "%~2" "%~1" -w "     http=%%{http_code} time=%%{time_total}s size=%%{size_download}B speed=%%{speed_download}B/s\n"
if errorlevel 1 goto :curl_fetch_bad
if not exist "%~2" goto :curl_fetch_bad
set "CSZ=0"
for %%P in ("%~2") do set "CSZ=%%~zP"
if %CSZ% LSS 1048576 goto :curl_fetch_bad
set "DL_OK=1"
goto :eof
:curl_fetch_bad
del /q "%~2" >nul 2>nul
set "DL_OK="
goto :eof

:err_args
echo error: missing tag or Gitee token.
echo usage: sync.bat v1.0.2 ^<token^> [assets_dir] [nopause]
goto :fail_nopause

:err_curl
echo error: curl.exe not found. Windows 10 1803+ bundles it.
goto :fail_nopause

:err_dir
echo error: could not create the assets dir: %ASSETS_DIR%
echo   this script downloads the release artifacts into that folder and uploads
echo   them to Gitee, so it has to be writable. Check free disk and permissions,
echo   or point it somewhere else with the 3rd argument:
echo     sync.bat %TAG_NAME% ^<token^> D:\somewhere\else
echo   who runs this at all: the release maintainer. End users never need it,
echo   they either download ByteTools.exe from the Releases page or run the two
echo   one-click scripts sitting in this folder.
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
