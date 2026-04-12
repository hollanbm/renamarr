ARG UV_VERSION=0.11.6

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

# chainguard secure distroless base image
FROM cgr.dev/chainguard/wolfi-base:latest AS runtime

# Grab python from the builder
COPY --from=builder --chown=nonroot:nonroot /python /python

WORKDIR /renamarr

# Copy the application from the builder
COPY --from=builder --chown=nonroot:nonroot /renamarr /renamarr

# default settings
ENV LOGURU_DIAGNOSE="NO"
ENV LOG_LEVEL="INFO"
ENV CONFIG_DIR="/"
ENV LOG_DIR="/logs"

# Prepare the default config and log directories for the nonroot runtime user.
RUN mkdir -p /config /logs && \
    chown -R nonroot:nonroot /config /logs

RUN apk add --no-cache tzdata
USER nonroot

# activate venv
ENV PATH="/renamarr/.venv/bin:$PATH"

ENTRYPOINT ["python", "src/main.py"]
