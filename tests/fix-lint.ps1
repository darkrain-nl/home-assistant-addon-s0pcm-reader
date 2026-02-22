# PowerShell script to run Ruff in Docker and copy back fixes
# Usage: .\tests\fix-lint.ps1

Write-Host "Building test container..." -ForegroundColor Blue
docker build --no-cache -f tests/Dockerfile.test -t s0pcm-reader-test .

if ($LASTEXITCODE -ne 0) {
    Write-Host "Build failed!" -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host "Starting temporary container..." -ForegroundColor Blue
$id = docker run -d -it --entrypoint sh s0pcm-reader-test

try {
    Write-Host "Running Ruff Check --fix..." -ForegroundColor Yellow
    docker exec $id ruff check . --fix

    Write-Host "Running Ruff Format..." -ForegroundColor Yellow
    docker exec $id ruff format .

    Write-Host "Copying patched files back to host..." -ForegroundColor Green
    # We only copy the directories we care about to avoid overwriting unrelated things
    docker cp "${id}:/workspace/rootfs" .
    docker cp "${id}:/workspace/tests" .
    
    Write-Host "Done! Files updated." -ForegroundColor Green
}
finally {
    Write-Host "Cleaning up container..." -ForegroundColor Blue
    docker rm -f $id | Out-Null
}
