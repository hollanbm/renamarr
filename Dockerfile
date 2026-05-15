ARG UV_VERSION=0.11.14
ARG RUNTIME_IMAGE=dhi.io/debian-base:trixie

FROM ghcr.io/astral-sh/uv:${UV_VERSION}-debian AS builder

# https://docs.astral.sh/uv/reference/environment/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_PREFERENCE=only-managed \
    UV_NO_DEV=1 UV_NO_EDITABLE=1 UV_FROZEN=1

# Configure the Python install directory for use when copying between stages
ENV UV_PYTHON_INSTALL_DIR=/python

WORKDIR /renamarr
# Install dependencies first for better caching
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --no-install-project

# Copy the rest of the app in
COPY . /renamarr
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync

RUN mkdir -p /config /logs

# Docker Hardened Images Debian runtime base image
FROM ${RUNTIME_IMAGE} AS runtime

# Grab python from the builder
COPY --from=builder --chown=nonroot:nonroot /python /python
COPY --from=builder --chown=nonroot:nonroot /config /config
COPY --from=builder --chown=nonroot:nonroot /logs /logs
COPY --from=builder --chown=nonroot:nonroot /renamarr /renamarr

WORKDIR /renamarr

USER nonroot

# default settings
ENV LOGURU_DIAGNOSE="NO"
ENV LOG_LEVEL="INFO"
ENV CONFIG_DIR="/"
ENV LOG_DIR="/logs"

# activate venv
ENV PATH="/renamarr/.venv/bin:$PATH"

ENTRYPOINT ["python", "src/main.py"]
