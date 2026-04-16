#!/bin/bash
set -e

# S0PCM Reader Release Script
# Automates the dev -> beta -> main release cycle.

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Starting release process...${NC}"

# 1. Safety Checks
CURRENT_BRANCH=$(git branch --show-current)
if [ "$CURRENT_BRANCH" != "dev" ]; then
    echo -e "${RED}Error: You must be on the 'dev' branch to start a release.${NC}"
    exit 1
fi

if [[ -n $(git status --porcelain) ]]; then
    echo -e "${RED}Error: You have uncommitted changes. Please commit or stash them first.${NC}"
    exit 1
fi

# 2. Version Detection
VERSION=$(grep '^version:' config.yaml | sed 's/version: *"\(.*\)"/\1/' | tr -d '\r')
echo -e "${YELLOW}Detected Version: $VERSION${NC}"

if [[ "$VERSION" == *-b* ]]; then
    IS_BETA=true
    echo -e "${YELLOW}Release Type: BETA${NC}"
else
    IS_BETA=false
    echo -e "${YELLOW}Release Type: STABLE${NC}"
fi

# 3. Push Dev
echo -e "${YELLOW}Pushing latest 'dev' changes to origin...${NC}"
git push origin dev

# 4. Beta Merge
echo -e "${YELLOW}Switching to 'beta' and merging 'dev'...${NC}"
git checkout beta
git pull origin beta
git merge dev --no-edit

# 5. Push Beta
echo -e "${YELLOW}Pushing to 'beta' to trigger CI release...${NC}"
git push origin beta

# 6. Wait for Beta CI
echo -e "${YELLOW}Waiting for GitHub Actions (Beta) release pipeline to start...${NC}"
sleep 10 # Give the API a moment to register the new run

RUN_ID=$(gh run list --branch beta --workflow "Tests" --limit 1 --json databaseId,status --jq 'if .[0].status == "queued" or .[0].status == "in_progress" or .[0].status == "waiting" then .[0].databaseId else empty end')

if [ -z "$RUN_ID" ]; then
    echo -e "${YELLOW}Could not find an active 'Tests' run for beta. It might have finished very quickly or haven't started yet.${NC}"
    echo -e "${YELLOW}Attempting to watch the latest run regardless...${NC}"
    RUN_ID=$(gh run list --branch beta --workflow "Tests" --limit 1 --json databaseId --jq '.[0].databaseId')
fi

echo -e "${GREEN}Watching Beta CI Run: https://github.com/darkrain-nl/home-assistant-addon-s0pcm-reader/actions/runs/$RUN_ID${NC}"
gh run watch "$RUN_ID"

# 7. Stable Release (Main Branch)
if [ "$IS_BETA" = false ]; then
    echo -e "${YELLOW}Proceeding with STABLE release to main...${NC}"
    
    PR_URL=$(gh pr list --base main --head beta --state open --json url --jq '.[0].url')
    if [ -z "$PR_URL" ]; then
        echo -e "${YELLOW}Creating Pull Request from 'beta' to 'main'...${NC}"
        PR_URL=$(gh pr create --base main --head beta --title "Release v$VERSION" --body "Automated stable release PR for version $VERSION. Triggered via release.sh")
    else
        echo -e "${YELLOW}Existing open PR found: $PR_URL${NC}"
    fi
    echo -e "${GREEN}PR Ready: $PR_URL${NC}"

    echo -e "${YELLOW}Merging PR into 'main'...${NC}"
    gh pr merge "$PR_URL" --merge

    echo -e "${YELLOW}Switching to 'main' and pulling...${NC}"
    git checkout main
    git pull origin main

    echo -e "${YELLOW}Waiting for GitHub Actions (Main) release pipeline to start...${NC}"
    sleep 10
    MAIN_RUN_ID=$(gh run list --branch main --workflow "Tests" --limit 1 --json databaseId,status --jq 'if .[0].status == "queued" or .[0].status == "in_progress" or .[0].status == "waiting" then .[0].databaseId else empty end')
    
    if [ -z "$MAIN_RUN_ID" ]; then
        MAIN_RUN_ID=$(gh run list --branch main --workflow "Tests" --limit 1 --json databaseId --jq '.[0].databaseId')
    fi
    echo -e "${GREEN}Watching Main CI Run: https://github.com/darkrain-nl/home-assistant-addon-s0pcm-reader/actions/runs/$MAIN_RUN_ID${NC}"
    gh run watch "$MAIN_RUN_ID"
fi

# 8. Sync Back
echo -e "${YELLOW}Finalizing synchronization...${NC}"
git checkout beta
git pull origin beta

git checkout dev
git pull origin dev

echo -e "${GREEN}Release process complete for v$VERSION!${NC}"
