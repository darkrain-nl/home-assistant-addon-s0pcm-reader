# Default to scratch to suppress 'InvalidDefaultArgInFrom' warnings.
# The true base image is always injected by builder using build.yaml.
ARG BUILD_FROM="scratch"
FROM ${BUILD_FROM}

WORKDIR /
COPY pyproject.toml uv.lock /tmp/uv/
COPY rootfs /

# 0.11.2
COPY --from=ghcr.io/astral-sh/uv@sha256:1025398289b62de8269e70c45b91ffa37c373f38118d7da036fb8bb8efc85d97 /uv /uvx /bin/

RUN --mount=type=cache,target=/root/.cache/uv \
    cd /tmp/uv && uv export --frozen --no-dev --no-emit-project --no-hashes | \
    uv pip install --link-mode=copy --system -r - && \
    cd / && rm -rf /tmp/uv && \
    chmod a+x /etc/services.d/s0pcm-reader/* && \
    addgroup -S s0pcm && adduser -S -D -H -h /usr/src -s /sbin/nologin -G s0pcm -g s0pcm s0pcm && \
    addgroup s0pcm dialout && \
    chown -R s0pcm:s0pcm /usr/src

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 /usr/src/healthcheck.py || exit 1
