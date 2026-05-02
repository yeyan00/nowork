@echo off
setlocal EnableDelayedExpansion

:: Upload nowork installer to GitHub Release
:: Requires GITHUB_TOKEN environment variable (with repo write permission)
:: Usage: upload-release.cmd [version]

set VERSION=%1
if "%VERSION%"=="" set VERSION=0.0.7

set REPO=yeyan00/nowork
set TAG=v%VERSION%
set FILE=src-tauri\target\release\bundle\nsis\nowork_%VERSION%_x64-setup.exe
set FILENAME=nowork_%VERSION%_x64-setup.exe

:: Check if file exists
if not exist "%FILE%" (
    echo ERROR: File not found: %FILE%
    echo Please run 'npm run tauri:build' first.
    exit /b 1
)

:: Check GitHub token
if "%GITHUB_TOKEN%"=="" (
    echo ERROR: GITHUB_TOKEN not set.
    echo Please set it via: set GITHUB_TOKEN=your_token_here
    exit /b 1
)

:: Get release upload URL
echo Fetching release info for %TAG%...
curl -s -H "Authorization: token %GITHUB_TOKEN%" ^
     -H "Accept: application/vnd.github.v3+json" ^
     "https://api.github.com/repos/%REPO%/releases/tags/%TAG%" > _release.json

:: Parse upload_url from JSON (simple regex-like parsing)
for /f "tokens=2 delims=:" %%a in ('findstr "upload_url" _release.json') do (
    set UPLOAD_URL=%%a
)
:: Remove quotes and {?name,label} suffix
set UPLOAD_URL=%UPLOAD_URL:"=%
set UPLOAD_URL=%UPLOAD_URL:{?name,label}=%

if "%UPLOAD_URL%"=="" (
    echo ERROR: Could not find release %TAG%
    echo You may need to create the release first on GitHub.
    del _release.json
    exit /b 1
)

echo Upload URL: %UPLOAD_URL%

:: Upload the file
echo Uploading %FILENAME%...
curl -s -X POST ^
     -H "Authorization: token %GITHUB_TOKEN%" ^
     -H "Content-Type: application/octet-stream" ^
     -H "Accept: application/vnd.github.v3+json" ^
     --data-binary "@%FILE%" ^
     "%UPLOAD_URL%?name=%FILENAME%" > _upload_result.json

:: Check result
findstr "state.*uploaded" _upload_result.json >nul
if !errorlevel!==0 (
    echo SUCCESS: %FILENAME% uploaded to release %TAG%
) else (
    echo ERROR: Upload failed. Response:
    type _upload_result.json
)

:: Cleanup
del _release.json _upload_result.json 2>nul
endlocal