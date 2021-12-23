ARG BUILD_FROM
FROM ${BUILD_FROM} 

WORKDIR /
COPY rootfs /

RUN pip install --no-cache-dir -r /usr/src/requirements.txt && \
    chmod a+x /usr/src/run.sh

CMD [ "/usr/src/run.sh" ]
