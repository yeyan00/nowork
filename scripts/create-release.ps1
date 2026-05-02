# create-release.ps1 - Create GitHub release and upload asset
# Usage: run this script, it will prompt for GitHub token if not set

param(
    [string]$Version = "0.0.7",
    [string]$Repo = "yeyan00/nowork"
)

$ErrorActionPreference = 'Stop'
$Tag = "v$Version"
$File = "src-tauri\target\release\bundle\nsis\nowork_$Version_x64-setup.exe"

# Check file exists
if (-not (Test-Path $File)) {
    Write-Error "File not found: $File. Please build first."
    exit 1
}

# Get token
$Token = $env:GITHUB_TOKEN
if (-not $Token) {
    Write-Host "GITHUB_TOKEN not set. Please enter your GitHub Personal Access Token:" -ForegroundColor Yellow
    Write-Host "(Token needs 'repo' scope for write access)" -ForegroundColor Gray
    $Token = Read-Host "Token"
    if (-not $Token) {
        Write-Error "No token provided, exiting."
        exit 1
    }
}

$Headers = @{
    Authorization = "token $Token"
    Accept = "application/vnd.github.v3+json"
}

# Check if release exists
Write-Host "Checking release $Tag..." -ForegroundColor Cyan
$ReleaseUrl = "https://api.github.com/repos/$Repo/releases/tags/$Tag"
try {
    $Release = Invoke-RestMethod -Uri $ReleaseUrl -Headers $Headers -Method Get
    Write-Host "Release $Tag exists (ID: $($Release.id))" -ForegroundColor Green
    $UploadUrl = $Release.upload_url -replace '\{\?name,label\}', ''
} catch {
    Write-Host "Release $Tag not found, creating..." -ForegroundColor Yellow
    
    # Get commits since last release for release notes
    $Notes = "## Changes in v$Version`n`n"
    $Commits = git log --oneline --since="2026-05-02 00:00" --until="2026-05-02 23:59"
    foreach ($Commit in $Commits) {
        $Notes += "- $Commit`n"
    }
    
    $CreateBody = @{
        tag_name = $Tag
        name = "nowork v$Version"
        body = $Notes
        draft = $false
        prerelease = $false
    } | ConvertTo-Json -Depth 10
    
    $CreateUrl = "https://api.github.com/repos/$Repo/releases"
    $Release = Invoke-RestMethod -Uri $CreateUrl -Headers $Headers -Method Post -Body $CreateBody -ContentType "application/json"
    Write-Host "Release created (ID: $($Release.id))" -ForegroundColor Green
    $UploadUrl = $Release.upload_url -replace '\{\?name,label\}', ''
}

# Upload asset
Write-Host "Uploading $File..." -ForegroundColor Cyan
$FileName = "nowork_$Version_x64-setup.exe"
$FileBytes = [System.IO.File]::ReadAllBytes((Resolve-Path $File))

$UploadHeaders = @{
    Authorization = "token $Token"
    Accept = "application/vnd.github.v3+json"
    "Content-Type" = "application/octet-stream"
}

$UploadFullUrl = "$UploadUrl?name=$FileName"
try {
    $Result = Invoke-RestMethod -Uri $UploadFullUrl -Headers $UploadHeaders -Method Post -Body $FileBytes
    Write-Host "SUCCESS: $FileName uploaded to release $Tag" -ForegroundColor Green
    Write-Host "Download URL: $($Result.browser_download_url)" -ForegroundColor Cyan
} catch {
    Write-Error "Upload failed: $_"
    exit 1
}

Write-Host "`nDone! Release page: https://github.com/$Repo/releases/tag/$Tag" -ForegroundColor Green