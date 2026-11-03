FROM alpine:3.20

RUN apk add --no-cache iproute2 nftables python3

COPY frame-gate-test.py /usr/local/bin/frame-gate-test.py

ENTRYPOINT ["python3", "/usr/local/bin/frame-gate-test.py"]
