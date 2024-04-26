FROM python:3.12-slim-bookworm

# update base
RUN apt-get update -y -qq
RUN apt-get dist-upgrade -y -qq
RUN apt-get autoremove -y -qq

# install pipx
RUN pip install pipx
RUN pipx ensurepath

# install poetry
RUN pipx --global install poetry

# setup user, bash default shell
RUN useradd app -m -s /bin/bash
USER app

WORKDIR /home/app/series_scanner
COPY --chown=app pyproject.toml poetry.lock src ./

RUN poetry install --no-interaction --no-ansi --no-cache --quiet

ENV HOURLY_JOB="TRUE"
ENV HOURS_BEFORE_AIR="4"
ENV LOGURU_DIAGNOSE="NO"
ENV LOGURU_LEVEL="INFO"

ENTRYPOINT poetry run python src/main.py
