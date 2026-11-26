# Default to amd64-base-python to satisfy OpenSSF Scorecard Pinned-Dependencies check.
# The true base image is always injected by builder using build.yaml.
ARG BUILD_FROM="ghcr.io/home-assistant/amd64-base-python:3.15-alpine3.24@sha256:b0e123122cfddad4265a96f9fa97433ba6368794ca2163b58043494ef7492ba8"
FROM ${BUILD_FROM}

ENV LD_PRELOAD="/usr/local/lib/libjemalloc.so.2"

WORKDIR /
COPY pyproject.toml uv.lock /tmp/uv/
COPY rootfs /

COPY --from=ghcr.io/astral-sh/uv:0.13.10@sha256:a3ea1357342c1a4bf9a0c53a3deb1b55379aefa037338d8113d5771efa01774f /uv /uvx /bin/

RUN --mount=type=cache,target=/root/.cache/uv \
    cd /tmp/uv && uv export --frozen --no-dev --no-emit-project --no-hashes | \
    uv pip install --link-mode=copy --system -r - && \
    cd / && rm -rf /tmp/uv && \
    chmod a+x /etc/services.d/s0pcm-reader/*

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 /usr/src/healthcheck.py || exit 1
