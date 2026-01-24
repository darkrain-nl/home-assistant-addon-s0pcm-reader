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

echo -e "${GREEN}Tests completed!${NC}"
