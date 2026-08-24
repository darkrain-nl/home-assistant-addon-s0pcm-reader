# Default to amd64-base-python to satisfy OpenSSF Scorecard Pinned-Dependencies check.
# The true base image is always injected by builder using build.yaml.
ARG BUILD_FROM="ghcr.io/home-assistant/amd64-base-python:3.14-alpine3.24@sha256:2313257a84f90cbc94231d87e0aba100fee14e36ef4d4b0041d5d554b2ecd287"
FROM ${BUILD_FROM}

ENV LD_PRELOAD="/usr/local/lib/libjemalloc.so.2"

WORKDIR /
COPY pyproject.toml uv.lock /tmp/uv/
COPY rootfs /

COPY --from=ghcr.io/astral-sh/uv:0.12.5@sha256:e85be844203885286c60ffad8a858d48afb6c5a5c237ca0e67f12e74b8f174b1 /uv /uvx /bin/

RUN --mount=type=cache,target=/root/.cache/uv \
    cd /tmp/uv && uv export --frozen --no-dev --no-emit-project --no-hashes | \
    uv pip install --link-mode=copy --system -r - && \
    cd / && rm -rf /tmp/uv && \
    chmod a+x /etc/services.d/s0pcm-reader/*

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 /usr/src/healthcheck.py || exit 1
