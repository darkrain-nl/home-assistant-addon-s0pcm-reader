# Quick Start - Docker Testing Setup

## ✅ What's Been Created

Your S0PCM Reader now has a complete Docker-based testing infrastructure:

### Files Created

```
.github/workflows/
└── test.yml                 # GitHub Actions CI/CD workflow

tests/
├── Dockerfile.test          # Docker container for testing
├── docker-test.ps1          # Windows PowerShell test runner
├── docker-test.sh           # Linux/Mac Bash test runner
├── DOCKER_TESTING.md        # Comprehensive Docker testing guide
├── requirements-test.txt    # Python test dependencies
├── pytest.ini               # Pytest configuration
├── conftest.py              # Test fixtures
├── test_serial_reader.py    # Serial port tests
├── test_mqtt_client.py      # MQTT client tests
└── test_config.py           # Configuration tests
```

## 🚀 Next Steps

### 1. Install Docker Desktop

**Download:** https://www.docker.com/products/docker-desktop/

- Windows: Install Docker Desktop for Windows
- After installation, restart your computer
- Verify: Open PowerShell and run `docker --version`

### 2. Run Tests Locally (After Docker is Installed)

```powershell
# Option A: Use the helper script
.\tests\docker-test.ps1

# Option B: Run Docker commands directly
docker build -f tests/Dockerfile.test -t s0pcm-reader-test .
docker run --rm -v "${PWD}/rootfs:/workspace/rootfs:ro" -v "${PWD}/tests:/workspace/tests:ro" s0pcm-reader-test
```

### 3. Set Up GitHub Actions (For Automated Testing)

1. Push your code to GitHub
2. GitHub Actions will automatically run tests on every push
3. View results in the **Actions** tab of your repository

**No additional setup needed!** The workflow file is already created at `.github/workflows/test.yml`

## 📋 Testing Workflow

```
┌─────────────────┐
│  Make Changes   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Run Tests      │ ← .\tests\docker-test.ps1
│  Locally        │
└────────┬────────┘
         │
         ▼
    ┌────────┐
    │ Pass?  │
    └───┬────┘
        │ Yes
        ▼
┌─────────────────┐
│  Commit & Push  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ GitHub Actions  │ ← Runs automatically
│  Runs Tests     │
└────────┬────────┘
         │
         ▼
    ┌────────┐
    │ Pass?  │
    └───┬────┘
        │ Yes
        ▼
┌─────────────────┐
│     Merge!      │
└─────────────────┘
```

## 🎯 Why This Setup?

✅ **Local Testing** - Run tests on your machine before committing
✅ **CI/CD** - Automated testing on every push/PR
✅ **Consistent** - Same environment locally and in CI
✅ **Isolated** - Tests don't affect your system
✅ **No Python Setup** - Docker handles everything

## 📖 Documentation

- **Quick Reference:** `tests/README.md`
- **Docker Guide:** `tests/DOCKER_TESTING.md`
- **Testing Guide:** `tests/TESTING_GUIDE.md`

## 🔧 Troubleshooting

### PowerShell Script Blocked?

If you get a security error running `docker-test.ps1`:

```powershell
# Option 1: Bypass for this session
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

# Option 2: Run Docker directly
docker build -f tests/Dockerfile.test -t s0pcm-reader-test .
docker run --rm -v "${PWD}/rootfs:/workspace/rootfs:ro" -v "${PWD}/tests:/workspace/tests:ro" s0pcm-reader-test
```

### Docker Not Found?

Install Docker Desktop from: https://www.docker.com/products/docker-desktop/

## 🎉 You're Ready!

Once Docker is installed, you can:
1. Run tests locally with confidence
2. Refactor code knowing tests will catch issues
3. Push to GitHub and let CI/CD verify everything works

**Happy Testing!** 🧪
