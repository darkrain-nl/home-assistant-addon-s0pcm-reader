#!/bin/bash
# Helper script to run tests in Docker
# Usage: ./tests/docker-test.sh [pytest arguments]

set -e

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check for 'lint' command
if [ "$1" == "lint" ]; then
    echo -e "${BLUE}Building test container for linting...${NC}"
    docker build -f tests/Dockerfile.test -t s0pcm-reader-test .

    echo -e "${BLUE}Starting temporary container...${NC}"
    CONTAINER_ID=$(docker run -d -it --entrypoint sh s0pcm-reader-test)

    # Clean up on exit
    trap 'docker rm -f $CONTAINER_ID > /dev/null' EXIT

    echo -e "${YELLOW}Running Ruff Check --fix...${NC}"
    docker exec "$CONTAINER_ID" ruff check . --fix

    echo -e "${YELLOW}Running Ruff Format...${NC}"
    docker exec "$CONTAINER_ID" ruff format .

    echo -e "${GREEN}Copying patched files back to host...${NC}"
    docker cp "${CONTAINER_ID}:/workspace/rootfs" .
    docker cp "${CONTAINER_ID}:/workspace/tests" .

    echo -e "${GREEN}Linting and formatting complete!${NC}"
    exit 0
fi

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

echo -e "${BLUE}Waiting for Verification (approx 45s)...${NC}"
VERIFIER_ID=$(docker compose -f tests/standalone/docker-compose.yml ps -q verifier)

if [ -z "$VERIFIER_ID" ]; then
    echo -e "${RED}Error: Verifier container not found.${NC}"
    exit 1
fi

EXIT_CODE=$(docker wait $VERIFIER_ID)

if [ "$EXIT_CODE" -eq 0 ]; then
    echo -e "${GREEN}Standalone Verification: PASSED${NC}"
    docker compose -f tests/standalone/docker-compose.yml down
else
    echo -e "${RED}Standalone Verification: FAILED${NC}"
    echo -e "${BLUE}--- Verifier Logs ---${NC}"
    docker compose -f tests/standalone/docker-compose.yml logs verifier
    echo -e "${BLUE}--- App Logs ---${NC}"
    docker compose -f tests/standalone/docker-compose.yml logs app
    docker compose -f tests/standalone/docker-compose.yml down
    exit $EXIT_CODE
fi
