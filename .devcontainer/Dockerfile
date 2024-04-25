FROM python:3.12-slim-bookworm

# update base
RUN apt-get update -y -qq
RUN apt-get dist-upgrade -y -qq

RUN apt-get install -y -qq \
    pipx \
    zsh

RUN apt-get autoremove -y -qq

# setup user, zsh default shell
RUN useradd poetry -m -s /bin/zsh
USER poetry

RUN pipx install poetry

ENV PATH="${PATH}:/home/poetry/.local/bin"
