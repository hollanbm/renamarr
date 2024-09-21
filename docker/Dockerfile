ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim-bookworm AS builder

WORKDIR /home/app/renamarr

# install poetry
RUN pip install poetry==1.8.3

COPY pyproject.toml poetry.lock ./

# poetry settings
ENV POETRY_NO_INTERACTION=1 \
  POETRY_VIRTUALENVS_IN_PROJECT=1 \
  POETRY_VIRTUALENVS_CREATE=true \
  POETRY_CACHE_DIR=/tmp/poetry_cache

# build venv
RUN --mount=type=cache,target=/tmp/poetry_cache poetry install --only main --no-root
RUN poetry install

FROM python:3.12-slim-bookworm AS app

# update base os
RUN apt-get update -y -qq && \
  apt-get dist-upgrade -y -qq && \
  apt-get autoremove -y -qq

WORKDIR /home/app/renamarr

# venv
COPY --from=builder /home/app/renamarr/.venv .venv

COPY src src

# setup user, bash default shell
RUN useradd app -m -s /bin/bash
RUN mkdir -p /config && chown -R app /config
SHELL ["/bin/bash", "-c"]

# switch to app user to prevent root usage
USER app

# default logging settings
ENV LOGURU_DIAGNOSE="NO"
ENV LOGURU_LEVEL="INFO"

# "activate" venv
ENV PATH="/home/app/renamarr/.venv/bin:$PATH"

ENTRYPOINT [ "python", "src/main.py"]
