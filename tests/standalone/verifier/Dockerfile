# 3.14-alpine
FROM python:3.14-alpine@sha256:dd4d2bd5b53d9b25a51da13addf2be586beebd5387e289e798e4083d94ca837a
WORKDIR /app

# Install uv
# 0.11.2
COPY --from=ghcr.io/astral-sh/uv@sha256:bca7f6959666f3524e0c42129f9d8bbcfb0c180d847f5187846b98ff06125ead /uv /uvx /bin/

# Use the project's lock file for paho-mqtt version consistency
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --no-cache paho-mqtt

# Install docker-cli to control sibling containers
RUN apk add --no-cache docker-cli

COPY tests/standalone/verifier/verifier.py .
CMD ["python", "-u", "verifier.py"]
