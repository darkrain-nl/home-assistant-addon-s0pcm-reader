# PowerShell script to run tests in Docker on Windows
# Usage: .\tests\docker-test.ps1 [pytest arguments]

param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PytestArgs
)

Write-Host "Building test container..." -ForegroundColor Blue
docker build -f tests/Dockerfile.test -t s0pcm-reader-test .

if ($LASTEXITCODE -ne 0) {
    Write-Host "Build failed!" -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host "Running tests..." -ForegroundColor Blue

# Get the current directory (project root)
$ProjectRoot = (Get-Location).Path

# For UNC paths or when Docker needs absolute paths, we need to handle this specially
# Docker on Windows doesn't handle UNC paths well in volume mounts
# Solution: Run without volume mounts since we already COPY the files in the Dockerfile
Write-Host "Note: Running tests from container (files copied during build)" -ForegroundColor Yellow

$dockerArgs = @(
    "run", "--rm",
    "s0pcm-reader-test"
)

if ($PytestArgs) {
    $dockerArgs += $PytestArgs
}

& docker $dockerArgs

if ($LASTEXITCODE -eq 0) {
    Write-Host "Unit Tests completed successfully!" -ForegroundColor Green
}
else {
    Write-Host "Unit Tests failed!" -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host "Running Standalone Integration Tests..." -ForegroundColor Blue
# Start infrastructure
docker compose -f tests/standalone/docker-compose.yml up -d --build

Write-Host "Waiting for Verification (approx 45s)..." -ForegroundColor Cyan
$exitCode = 0

try {
    # Wait for verifier to finish
    $verifierId = docker compose -f tests/standalone/docker-compose.yml ps -q verifier
    if (-not $verifierId) {
        Write-Host "Error: Verifier container not found." -ForegroundColor Red
        exit 1
    }

    $waitResult = docker wait $verifierId
    $exitCode = [int]$waitResult
}
catch {
    Write-Host "Error waiting for verifier: $_" -ForegroundColor Red
    $exitCode = 1
}

if ($exitCode -eq 0) {
    Write-Host "Standalone Verification: PASSED" -ForegroundColor Green
    docker compose -f tests/standalone/docker-compose.yml down
}
else {
    Write-Host "Standalone Verification: FAILED" -ForegroundColor Red
    Write-Host "--- Verifier Logs ---" -ForegroundColor Yellow
    docker compose -f tests/standalone/docker-compose.yml logs verifier
    Write-Host "--- App Logs ---" -ForegroundColor Yellow
    docker compose -f tests/standalone/docker-compose.yml logs app
    
    docker compose -f tests/standalone/docker-compose.yml down
    exit 1
}
