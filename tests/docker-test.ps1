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
docker compose -f tests/standalone/docker-compose.yml up -d --build
Start-Sleep -Seconds 20
$appState = docker inspect -f '{{.State.Running}}' standalone-app-1

if ($appState -eq "true") {
    Write-Host "Standalone Verification: App is RUNNING" -ForegroundColor Green
    docker compose -f tests/standalone/docker-compose.yml down
}
else {
    Write-Host "Standalone Verification: App FAILED too start" -ForegroundColor Red
    docker compose -f tests/standalone/docker-compose.yml logs
    docker compose -f tests/standalone/docker-compose.yml down
    exit 1
}
