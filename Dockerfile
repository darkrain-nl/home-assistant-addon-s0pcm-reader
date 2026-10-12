# Default to amd64-base-python to satisfy OpenSSF Scorecard Pinned-Dependencies check.
# The true base image is always injected by builder using build.yaml.
ARG BUILD_FROM="ghcr.io/home-assistant/amd64-base-python:3.14-alpine3.24@sha256:52d3d74deef3b423577ba9993d3e88615962893a7df47ee142c929ed7862c38d"
FROM ${BUILD_FROM}

ENV LD_PRELOAD="/usr/local/lib/libjemalloc.so.2"

WORKDIR /
COPY pyproject.toml uv.lock /tmp/uv/
COPY rootfs /

COPY --from=ghcr.io/astral-sh/uv:0.13.0@sha256:cdc6093146eb3ff6a40107b38f008b789e050e77ad87865e381d9917da55a168 /uv /uvx /bin/

RUN --mount=type=cache,target=/root/.cache/uv \
    cd /tmp/uv && uv export --frozen --no-dev --no-emit-project --no-hashes | \
    uv pip install --link-mode=copy --system -r - && \
    cd / && rm -rf /tmp/uv && \
    chmod a+x /etc/services.d/s0pcm-reader/*

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 /usr/src/healthcheck.py || exit 1
