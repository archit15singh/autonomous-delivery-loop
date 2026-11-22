FROM python:3.12-alpine@sha256:c5ba3deef00c7758561a0f03c26f44f10589263d40e732b8748e0d1f38f6dd89
COPY adl-wheels.lock /opt/adl-wheels.lock
RUN pip --isolated install --no-cache-dir --require-hashes --only-binary=:all: --no-deps -r /opt/adl-wheels.lock
WORKDIR /app
COPY app/ .
USER 65534:65534
ENTRYPOINT ["python", "-B", "app.py"]
