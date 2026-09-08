# 3.14-alpine
FROM python:3.14-alpine@sha256:c6ead215bfd31f1e433d968853b7a769989117115b728874824e6c0a27cb96fc
WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.12.11@sha256:79c6f4776b851471cc73b7d21d0cc834bb94383c292e83640d27eff512864df7 /uv /uvx /bin/

# Use the project's lock file for paho-mqtt version consistency
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --no-cache paho-mqtt

# Install docker-cli to control sibling containers
RUN apk add --no-cache docker-cli

COPY tests/standalone/verifier/verifier.py .
CMD ["python", "-u", "verifier.py"]
