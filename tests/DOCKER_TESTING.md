# Docker-Based Testing Guide

This guide explains how to run tests using Docker, both locally and in CI/CD.

## Why Docker?

- ✅ **Consistent environment** across all machines
- ✅ **Isolated** from your system
- ✅ **Same as CI/CD** - tests run identically locally and in GitHub Actions
- ✅ **No Python installation needed** on your machine
- ✅ **Clean state** every run

## Prerequisites

- Docker Desktop installed and running
- That's it! No Python or pip needed.

## Running Tests Locally

### Windows (PowerShell)

```powershell
# From the project root
.\tests\docker-test.ps1

# Run specific tests
.\tests\docker-test.ps1 -k "test_serial"

# Run with coverage report
.\tests\docker-test.ps1 --cov=rootfs/usr/src --cov-report=html
```

### Linux/Mac (Bash)

```bash
# From the project root
./tests/docker-test.sh

# Run specific tests
./tests/docker-test.sh -k "test_serial"

# Run with coverage report
./tests/docker-test.sh --cov=rootfs/usr/src --cov-report=html
```

### Manual Docker Commands

If you prefer to run Docker commands directly:

```bash
# IMPORTANT: Run these commands from the PROJECT ROOT directory
# (not from the tests/ directory)

# Build the test container
docker build -f tests/Dockerfile.test -t s0pcm-reader-test .

# Run all tests
docker run --rm \
  -v "$(pwd)/rootfs:/workspace/rootfs:ro" \
  -v "$(pwd)/tests:/workspace/tests:ro" \
  s0pcm-reader-test

# Run with custom pytest arguments
docker run --rm \
  -v "$(pwd)/rootfs:/workspace/rootfs:ro" \
  -v "$(pwd)/tests:/workspace/tests:ro" \
  s0pcm-reader-test \
  pytest tests/ -v -k "test_mqtt"
```

## GitHub Actions (CI/CD)

Tests run automatically on:
- Every push to `main`, `master`, or `develop` branches
- Every pull request
- Manual workflow dispatch

### Workflow Features

1. **Python Tests** - Runs tests with Python 3.14
2. **Docker Tests** - Validates tests work in Docker
3. **Coverage Report** - Uploads to Codecov
4. **Test Artifacts** - Saves coverage reports for 30 days

### Viewing Results

1. Go to your repository on GitHub
2. Click **Actions** tab
3. Select a workflow run
4. View test results and coverage

### Adding Status Badge

Add this to your `README.md`:

```markdown
[![Tests](https://github.com/YOUR_USERNAME/YOUR_REPO/workflows/Tests/badge.svg)](https://github.com/YOUR_USERNAME/YOUR_REPO/actions)
```

## Troubleshooting

### Docker Build Fails

```bash
# Clean Docker cache and rebuild
docker system prune -f
docker build --no-cache -f tests/Dockerfile.test -t s0pcm-reader-test .
```

### Volume Mount Issues (Windows)

If you get permission errors on Windows:
1. Open Docker Desktop
2. Go to Settings → Resources → File Sharing
3. Add your project directory
4. Restart Docker Desktop

### Tests Pass Locally but Fail in CI

This usually means:
- Different Python version (CI uses 3.14)
- Different dependencies
- Platform-specific code

Check the GitHub Actions logs for details.

## Development Workflow

```bash
# 1. Make code changes
# 2. Run tests locally
.\tests\docker-test.ps1

# 3. If tests pass, commit
git add .
git commit -m "Your changes"

# 4. Push to GitHub
git push

# 5. GitHub Actions runs tests automatically
# 6. Check the Actions tab for results
```

## Advanced Usage

### Interactive Testing

Run an interactive shell in the test container:

```bash
docker run --rm -it \
  -v "$(pwd)/rootfs:/workspace/rootfs" \
  -v "$(pwd)/tests:/workspace/tests" \
  s0pcm-reader-test \
  sh
```

Then inside the container:
```bash
# Run tests manually
pytest tests/ -v

# Run specific test file
pytest tests/test_serial_reader.py -v

# Debug with pdb
pytest tests/test_serial_reader.py --pdb
```

### Custom Test Container

Modify `tests/Dockerfile.test` to:
- Add debugging tools
- Change Python version
- Install additional dependencies

## Performance

- **First build**: ~2-3 minutes (downloads base image)
- **Subsequent builds**: ~10-30 seconds (uses cache)
- **Test execution**: ~5-10 seconds

## Best Practices

1. ✅ Run tests before every commit
2. ✅ Keep test container lightweight
3. ✅ Use volume mounts (not COPY) for fast iteration
4. ✅ Check GitHub Actions results before merging PRs
5. ✅ Keep tests fast (< 1 second each)

## Further Reading

- [Docker Documentation](https://docs.docker.com/)
- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [pytest Documentation](https://docs.pytest.org/)
