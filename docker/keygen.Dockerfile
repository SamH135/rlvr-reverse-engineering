FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        libc6-dev \
        binutils \
        gdb \
        file \
        gcc-aarch64-linux-gnu \
        libc6-dev-arm64-cross \
        binutils-aarch64-linux-gnu \
        binutils-multiarch \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/repo
