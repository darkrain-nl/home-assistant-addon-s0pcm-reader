ARG BUILD_FROM
FROM ${BUILD_FROM} 

WORKDIR /
COPY rootfs /

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

RUN uv pip install --system --no-cache --index-strategy unsafe-best-match -r /usr/src/requirements.lock && \
    chmod a+x /etc/services.d/s0pcm-reader/*

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 /usr/src/healthcheck.py || exit 1
