param(
    [switch]$SelfTest
)

$ErrorActionPreference = "Stop"
$script:MinerUCheckExitCode = 0
$TokenName = "MINERU_API_TOKEN"
$ExpiryName = "MINERU_API_EXPIRES_ON"
$StateDirName = "MANAGE_ARTICLE_KNOWLEDGE_STATE_DIR"
$Runner = Join-Path $PSScriptRoot "run_mineru.py"

function Find-Python {
    $candidates = [System.Collections.Generic.List[string]]::new()
    $command = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($command) { $candidates.Add($command.Source) }

    $command = Get-Command python3.exe -ErrorAction SilentlyContinue
    if ($command) { $candidates.Add($command.Source) }

    $bundled = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    $candidates.Add($bundled)

    $runtimeRoot = Join-Path $env:USERPROFILE ".cache\codex-runtimes"
    if (Test-Path -LiteralPath $runtimeRoot) {
        Get-ChildItem -LiteralPath $runtimeRoot -Recurse -Filter python.exe -File -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -like "*\dependencies\python\python.exe" } |
            ForEach-Object { $candidates.Add($_.FullName) }
    }

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            return $candidate
        }
    }
    return $null
}

function Invoke-MinerUCheck {
    param(
        [string]$Python,
        [string[]]$Arguments
    )
    & $Python $Runner @Arguments
    $script:MinerUCheckExitCode = [int]$LASTEXITCODE
}

Write-Host "MinerU administrator setup" -ForegroundColor Cyan
Write-Host "The token will not be written to the Skill, client projects, or check logs."
Write-Host ""

if (-not (Test-Path -LiteralPath $Runner -PathType Leaf)) {
    throw "run_mineru.py was not found. Run this setup from the complete Skill directory."
}

$python = Find-Python
if (-not $python) {
    throw "Python was not found. Install or start Codex Desktop once, then run this setup again."
}

if ($SelfTest) {
    $originalToken = $env:MINERU_API_TOKEN
    $originalExpiry = $env:MINERU_API_EXPIRES_ON
    $originalStateDir = $env:MANAGE_ARTICLE_KNOWLEDGE_STATE_DIR
    $testStateDir = Join-Path ([IO.Path]::GetTempPath()) "manage-article-knowledge-initializer-test"
    try {
        $env:MINERU_API_TOKEN = "initializer-self-test-token"
        $env:MINERU_API_EXPIRES_ON = "2099-12-31"
        $env:MANAGE_ARTICLE_KNOWLEDGE_STATE_DIR = $testStateDir
        Invoke-MinerUCheck -Python $python -Arguments @("probe")
        $probeExit = $script:MinerUCheckExitCode
        if ($probeExit -ne 0) {
            throw "Setup subprocess exit-code check failed."
        }
    }
    finally {
        $env:MINERU_API_TOKEN = $originalToken
        $env:MINERU_API_EXPIRES_ON = $originalExpiry
        $env:MANAGE_ARTICLE_KNOWLEDGE_STATE_DIR = $originalStateDir
        Remove-Item -LiteralPath $testStateDir -Recurse -Force -ErrorAction SilentlyContinue
    }
    Write-Host "Setup structure check passed." -ForegroundColor Green
    Write-Host "Python: $python"
    Write-Host "Runner: $Runner"
    exit 0
}

Write-Host "Copy the complete token line from the TXT file now." -ForegroundColor Cyan
[void](Read-Host "After copying it, return here and press Enter (do not paste into this window)")
$clipboardText = Get-Clipboard -Raw -ErrorAction Stop
try {
    # Windows PowerShell 5.1 rejects an empty string; one space still replaces the secret.
    Set-Clipboard -Value " " -ErrorAction Stop
}
catch {
    Write-Host "Warning: the clipboard could not be cleared. Copy non-sensitive text after setup." -ForegroundColor Yellow
}
if ($null -eq $clipboardText) {
    throw "The clipboard does not contain text. Copy the complete token line and run setup again."
}
$token = $clipboardText.TrimEnd([char[]]"`r`n")
$clipboardText = $null
if ([string]::IsNullOrWhiteSpace($token)) {
    throw "The clipboard is empty. Copy the complete token line and run setup again."
}
if ($token.Contains("`r") -or $token.Contains("`n")) {
    throw "The clipboard contains multiple lines. Copy only the single token line and run setup again."
}
if ($token -ne $token.Trim()) {
    throw "Token contains leading or trailing spaces. Copy only the token value and try again."
}
if ($token.StartsWith("Bearer ", [StringComparison]::OrdinalIgnoreCase)) {
    throw "Do not include the 'Bearer ' prefix. Copy only the token value and try again."
}
if (($token.StartsWith('"') -and $token.EndsWith('"')) -or
    ($token.StartsWith("'") -and $token.EndsWith("'"))) {
    throw "Do not include quotation marks. Copy only the token value and try again."
}
if ($token.Length -lt 20) {
    throw "Only $($token.Length) character(s) were received. This is not a complete MinerU API Token."
}
Write-Host "Token received: $($token.Length) characters (content remains hidden)." -ForegroundColor Green

do {
    $expiry = Read-Host "Enter the token expiry date (YYYY-MM-DD)"
    $parsedExpiry = [datetime]::MinValue
    $validExpiry = [datetime]::TryParseExact(
        $expiry,
        "yyyy-MM-dd",
        [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::None,
        [ref]$parsedExpiry
    )
    if (-not $validExpiry) {
        Write-Host "Invalid date. Example: 2026-12-31." -ForegroundColor Yellow
    }
} until ($validExpiry)

$stateDir = Join-Path ([IO.Path]::GetTempPath()) "manage-article-knowledge"
New-Item -ItemType Directory -Path $stateDir -Force | Out-Null

[Environment]::SetEnvironmentVariable($TokenName, $token, "User")
[Environment]::SetEnvironmentVariable($ExpiryName, $expiry, "User")
[Environment]::SetEnvironmentVariable($StateDirName, $stateDir, "User")
$env:MINERU_API_TOKEN = $token
$env:MINERU_API_EXPIRES_ON = $expiry
$env:MANAGE_ARTICLE_KNOWLEDGE_STATE_DIR = $stateDir

Write-Host ""
Write-Host "1/2 Checking local configuration..."
Invoke-MinerUCheck -Python $python -Arguments @("probe")
$probeExit = $script:MinerUCheckExitCode
if ($probeExit -ne 0) {
    throw "Local configuration check failed. The token was saved, but MinerU is not ready."
}

Write-Host ""
Write-Host "2/2 Checking token, upload, processing, and download..."
Invoke-MinerUCheck -Python $python -Arguments @("health-check")
$healthExit = $script:MinerUCheckExitCode
if ($healthExit -eq 3) {
    $token = $null
    Write-Host ""
    Write-Host "Local setup completed. MinerU online verification is temporarily pending." -ForegroundColor Yellow
    Write-Host "Fully exit and reopen Codex Desktop. Codex will retry automatically when MinerU is needed."
    Write-Host "Do not replace or re-enter the token because of this temporary network/service result."
    exit 0
}
if ($healthExit -ne 0) {
    throw "Online check failed. Use failure_stage above to identify token, network, upload, processing, or download failure."
}

$token = $null
Write-Host ""
Write-Host "Setup completed. Fully exit and reopen Codex Desktop." -ForegroundColor Green
Write-Host "Content operators can now give a PDF/PPT to Codex and request processing. No token or command is needed."
