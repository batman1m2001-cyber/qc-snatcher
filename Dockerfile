FROM dockerhub-proxy.aws.platform.win.dev/nvidia/cuda:12.9.0-cudnn-devel-ubuntu24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

# Create pip config directly
RUN mkdir -p /root/.config/pip
RUN echo "[global]" > /root/.config/pip/pip.conf && \
echo "index = https://registry.aws.platform.win.dev/repository/pypi-proxy/pypi" >> /root/.config/pip/pip.conf && \
echo "index-url = https://registry.aws.platform.win.dev/repository/pypi-proxy/simple" >> /root/.config/pip/pip.conf && \
echo "trusted-host = registry.aws.platform.win.dev" >> /root/.config/pip/pip.conf

RUN mkdir -p /etc/apt/sources.list.d
RUN echo "deb [trusted=yes] https://registry.aws.platform.win.dev/repository/ubuntu-archived-24-proxy/ noble main restricted universe multiverse" > /etc/apt/sources.list.d/nexus-ubuntu.list && \
    echo "deb [trusted=yes] https://registry.aws.platform.win.dev/repository/ubuntu-archived-24-proxy/ noble-updates main restricted universe multiverse" >> /etc/apt/sources.list.d/nexus-ubuntu.list && \
    echo "deb [trusted=yes] https://registry.aws.platform.win.dev/repository/ubuntu-archived-24-proxy/ noble-security main restricted universe multiverse" >> /etc/apt/sources.list.d/nexus-ubuntu.list

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-venv &&\
    apt-get install -y --only-upgrade \
        libc6 \
        libc6-dev \
        libc-bin \
        libc-dev-bin \
        locales \
        libgcrypt20 \
        libgnutls30t64 \
        libgnutls-dane0t64 \
        libgnutls-openssl27t64 \
        gnutls-bin \
        binutils \
        perl \
        libsystemd0 \
        libudev1 \
        systemd \
        libpam0g \
        libpam-modules \
        libpam-modules-bin \
        libpam-runtime \
        libpam-systemd \
        libtasn1-6 \
        openssl \
        libsqlite3-0 \
        libsqlite3-dev \
        gnupg2 \
        gnupg \
        gpg \
        gpg-agent \
        gpgconf \
        gpgsm \
        dirmngr \
        libcap2 \
        dpkg \
        sed \
        gzip \
        tar && \
    python3 -m venv /opt/venv && \
    /opt/venv/bin/pip install --upgrade "pip>=26.1" setuptools==78.1.1 && \
    apt-get purge -y python3-pip python3-pip-whl || true && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY ./deployment/score_sentiment/requirements.txt /app/
RUN python -m pip install -r /app/requirements.txt

# The `COPY ./deployment/pkgs/` + `pip install /app/pkgs/*.whl` pair that
# stood here is gone with the hush wheels. hush was private, so vendoring
# was the only channel; operonx is public and comes from the pypi-proxy
# configured above, as a line in requirements.txt.
#
# `deployment/pkgs/` is kept as an empty slot. If the proxy ever refuses
# to serve operonx, drop a locally-built wheel in there and restore those
# two lines — the two lines are the whole fallback. Leaving them in with
# an empty directory does not degrade gracefully: the shell cannot expand
# `*.whl`, passes it through literally, and pip fails the build on a
# filename.

# Clean up unnecessary files
RUN rm -rf /opt/nvidia/nsight-compute/2025.2.0/host/target-linux-x64/python/bin/python 2>/dev/null || true
RUN rm -rf /opt/venv/lib/python3.12/site-packages/setuptools/_vendor/*wheel-0.45.1* 2>/dev/null || true
RUN rm -rf /opt/venv/lib/python3.12/site-packages/thrift-0.22.0.dist-info 2>/dev/null || true
RUN rm -rf /opt/venv/lib/python3.12/site-packages/protobuf-*.dist-info 2>/dev/null || true
# RUN rm -rf /opt/venv/lib/python3.12/site-packages/protobuf-6.33.6.dist-info	2>/dev/null || true

# Copy application files

COPY ./resources.yaml /app/resources.yaml
# Stage routing — src/core/config.py reads it at import; without it nothing starts.
COPY ./models.yaml /app/models.yaml
COPY ./src/ /app/src
# main.py runs the jobs app/main.py declares (preflight, score); operonx-run
# finds them through operonx.toml. Their graphs are in src/jobs/.
COPY ./app/ /app/app
COPY ./operonx.toml /app/operonx.toml
COPY ./knowledge /app/knowledge
COPY ./main.py /app/main.py
COPY ./tests/sample/fixtures/ /app/tests/sample/fixtures
COPY ./deployment/score_sentiment/__init__.py /app/__init__.py
COPY ./deployment/score_sentiment/settings.py /app/settings.py
COPY ./deployment/score_sentiment/sentiment.py /app/sentiment.py
COPY ./deployment/score_sentiment/helper_funcs.py /app/helper_funcs.py

WORKDIR /app
ENTRYPOINT []


# FROM dockerhub-proxy.aws.platform.win.dev/python:3.12.13-slim

# # Create pip config directly
# RUN mkdir -p /root/.config/pip
# # Pip proxy
# RUN echo "[global]" > /root/.config/pip/pip.conf && \
# echo "index = https://registry.aws.platform.win.dev/repository/pypi-proxy/pypi" >> /root/.config/pip/pip.conf && \
# echo "index-url = https://registry.aws.platform.win.dev/repository/pypi-proxy/simple" >> /root/.config/pip/pip.conf && \
# echo "trusted-host = registry.aws.platform.win.dev" >> /root/.config/pip/pip.conf
# # Nexus proxy
# RUN mkdir -p /etc/apt/sources.list.d
# RUN echo "deb [trusted=yes] https://registry.aws.platform.win.dev/repository/deb-debian-12-proxy/ bookworm main" > /etc/apt/sources.list.d/nexus.list


# RUN apt-get update && \
#     apt-get install -y ffmpeg libsm6 libxext6 && \
#     apt-get install -y --only-upgrade libc6 libc-bin libc-dev-bin libcap2 && \
#     apt-get clean && rm -rf /var/lib/apt/lists/* && \
#     pip install --upgrade pip && \
#     pip install --upgrade setuptools==78.1.1 "wheel>=0.46.2"

# RUN pip install --no-cache-dir --upgrade "pip>=25.3"

# # Install Python dependencies
# # Copy requirements first for better caching
# RUN pip install torch==2.5.0+cpu --index-url https://registry.aws.platform.win.dev/repository/pytorch-pypi-proxy/simple
# COPY  ./deployment/data_ingestion/requirements.txt /app/

# RUN pip install -r /app/requirements.txt
# COPY ./deployment/data_ingestion/ /app
# # COPY ./deployment/score_sentiment/ /app/score_sentiment/
# # RUN pip install --no-cache-dir /app/pkgs/*.whl
# # Clean up potential vulnerable packages and unnecessary files
# RUN rm -rf /usr/local/lib/python*/site-packages/*torch-2.5.0* 2>/dev/null || true
# RUN rm -rf /usr/local/lib/python3.12/site-packages/setuptools/_vendor/*wheel-0.45.1* 2>/dev/null || true
# RUN rm -rf /usr/local/lib/python3.12/site-packages/thrift-0.22.0.dist-info 2>/dev/null || true
# RUN rm -rf /usr/local/lib/python3.12/site-packages/protobuf-6.33.6.dist-info 2>/dev/null || true
# # Copy application files
# COPY ./metadata.py /app/metadata.py
# # COPY ./.prompts  /app/.prompts

# # Set working directory and user
# WORKDIR /app
# ENV PATH="/venv/bin:$PATH"
# ENTRYPOINT []
