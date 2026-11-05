FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        libc6-dev \
        binutils \
        gdb \
        file \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/repo
