ARG BUILD_FROM
FROM ${BUILD_FROM}

WORKDIR /
COPY pyproject.toml uv.lock /tmp/uv/
COPY rootfs /

COPY --from=ghcr.io/astral-sh/uv:0.10.9 /uv /uvx /bin/

RUN cd /tmp/uv && uv export --frozen --no-dev --no-emit-project --no-hashes | \
    uv pip install --system --no-cache -r - && \
    cd / && rm -rf /tmp/uv && \
    chmod a+x /etc/services.d/s0pcm-reader/*

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 /usr/src/healthcheck.py || exit 1
