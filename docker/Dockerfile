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
RUN mkdir -p /config && chown -R app /config

USER app
SHELL ["/bin/bash", "-c"]

WORKDIR /home/app/series_scanner

# See .dockerignore for files whitelist
COPY --chown=app . . 

# install app dependencies
RUN poetry install --no-interaction --no-ansi --no-cache --quiet

ENV LOGURU_DIAGNOSE="NO"
ENV LOG_LEVEL="INFO"

# activate venv
RUN source $(poetry env info --path)/bin/activate

ENTRYPOINT [ "poetry", "run", "python", "src/main.py"]
