ARG BUILD_FROM
FROM ${BUILD_FROM} 

WORKDIR /
COPY rootfs /

RUN pip install --no-cache-dir -r /usr/src/requirements.txt && \
    chmod a+x /etc/services.d/s0pcm-reader/*

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python3 /usr/src/healthcheck.py || exit 1
