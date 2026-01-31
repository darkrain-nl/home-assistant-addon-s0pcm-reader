#!/bin/bash
# Helper script to run tests in Docker
# Usage: ./tests/docker-test.sh [pytest arguments]

set -e

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}Building test container...${NC}"
docker build -f tests/Dockerfile.test -t s0pcm-reader-test .

echo -e "${BLUE}Running tests...${NC}"
docker run --rm \
  -v "$(pwd)/rootfs:/workspace/rootfs:ro" \
  -v "$(pwd)/tests:/workspace/tests:ro" \
  s0pcm-reader-test "$@"

echo -e "${GREEN}Unit Tests completed!${NC}"

echo -e "${BLUE}Running Standalone Integration Tests...${NC}"
docker compose -f tests/standalone/docker-compose.yml up -d --build
sleep 10
APP_STATE=$(docker inspect -f '{{.State.Running}}' standalone-app-1)

if [ "$APP_STATE" == "true" ]; then
    echo -e "${GREEN}Standalone Verification: App is RUNNING${NC}"
    docker compose -f tests/standalone/docker-compose.yml down
else
    echo -e "${RED}Standalone Verification: App FAILED to start${NC}"
    docker compose -f tests/standalone/docker-compose.yml logs
    docker compose -f tests/standalone/docker-compose.yml down
    exit 1
fi
