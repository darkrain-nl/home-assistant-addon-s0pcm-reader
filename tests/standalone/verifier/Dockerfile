# 3.14-alpine
FROM python:3.14-alpine@sha256:a3de013592ea520507c1f18d880592338bd21abfe706237e68ed4126e21b6900
WORKDIR /app

# Install uv
# 0.11.2
COPY --from=ghcr.io/astral-sh/uv@sha256:1025398289b62de8269e70c45b91ffa37c373f38118d7da036fb8bb8efc85d97 /uv /uvx /bin/

# Use the project's lock file for paho-mqtt version consistency
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --no-cache paho-mqtt

# Install docker-cli to control sibling containers
RUN apk add --no-cache docker-cli

COPY tests/standalone/verifier/verifier.py .
CMD ["python", "-u", "verifier.py"]
