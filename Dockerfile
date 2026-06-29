# Default to amd64-base-python to satisfy OpenSSF Scorecard Pinned-Dependencies check.
# The true base image is always injected by builder using build.yaml.
ARG BUILD_FROM="ghcr.io/home-assistant/amd64-base-python:3.14-alpine3.24@sha256:f59ecbbc63f781bf1215dd6b70f890a0487ff434ffc0fa721b368a5f4613d176"
FROM ${BUILD_FROM}

ENV LD_PRELOAD="/usr/local/lib/libjemalloc.so.2"

WORKDIR /
COPY pyproject.toml uv.lock /tmp/uv/
COPY rootfs /

# 0.11.2
COPY --from=ghcr.io/astral-sh/uv@sha256:1e3808aa9023d0980e7c15b1fa7c1ac16ff35925780cf5c459858b2d693f01a9 /uv /uvx /bin/

RUN --mount=type=cache,target=/root/.cache/uv \
    cd /tmp/uv && uv export --frozen --no-dev --no-emit-project --no-hashes | \
    uv pip install --link-mode=copy --system -r - && \
    cd / && rm -rf /tmp/uv && \
    chmod a+x /etc/services.d/s0pcm-reader/*

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 /usr/src/healthcheck.py || exit 1
