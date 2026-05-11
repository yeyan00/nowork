# upload-release-0.0.8.ps1 - Upload installer to GitHub Release
# Fill in your GITHUB_TOKEN below

$ErrorActionPreference = 'Stop'

# ============================================================
# >>> 填写你的 GitHub Token <<<
$Token = "YOUR_GITHUB_TOKEN_HERE"
# ============================================================

$Version = "0.0.8"
$Repo = "yeyan00/nowork"
$Tag = "v$Version"
$File = "src-tauri\target\release\bundle\nsis\nowork_${Version}_x64-setup.exe"
$FileName = "nowork_${Version}_x64-setup.exe"

# Check file
if (-not (Test-Path $File)) {
    Write-Error "File not found: $File"
    exit 1
}

$Headers = @{
    Authorization = "token $Token"
    Accept = "application/vnd.github.v3+json"
}

# Check if release exists, create if not
Write-Host "Checking release $Tag..." -ForegroundColor Cyan
$ReleaseUrl = "https://api.github.com/repos/$Repo/releases/tags/$Tag"
try {
    $Release = Invoke-RestMethod -Uri $ReleaseUrl -Headers $Headers -Method Get
    Write-Host "Release $Tag exists (ID: $($Release.id))" -ForegroundColor Green
    $UploadUrl = $Release.upload_url -replace '\{\?name,label\}', ''
} catch {
    Write-Host "Release $Tag not found, creating..." -ForegroundColor Yellow
    
    # Get recent commits for release notes
    $Notes = "## Changes in v$Version`n`n"
    $Commits = git log --oneline -10
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

# Upload file
Write-Host "Uploading $FileName..." -ForegroundColor Cyan
$FileSize = (Get-Item $File).Length / 1MB
Write-Host "File size: $([math]::Round($FileSize, 1)) MB" -ForegroundColor Gray

$FileBytes = [System.IO.File]::ReadAllBytes((Resolve-Path $File).Path)
$UploadHeaders = @{
    Authorization = "token $Token"
    Accept = "application/vnd.github.v3+json"
    "Content-Type" = "application/octet-stream"
}

$FullUrl = "${UploadUrl}?name=${FileName}"

try {
    $Result = Invoke-RestMethod -Uri $FullUrl -Headers $UploadHeaders -Method Post -Body $FileBytes
    Write-Host "SUCCESS: Uploaded to $Tag" -ForegroundColor Green
    Write-Host "Download URL: $($Result.browser_download_url)" -ForegroundColor Cyan
} catch {
    Write-Error "Upload failed: $_"
    Write-Host "Response: $($Error[0].ErrorDetails.Message)" -ForegroundColor Red
    exit 1
}

Write-Host "`nRelease page: https://github.com/$Repo/releases/tag/$Tag" -ForegroundColor Green