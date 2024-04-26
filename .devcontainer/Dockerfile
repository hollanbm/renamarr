FROM python:3.12-slim-bookworm

# update base
RUN apt-get update -y -qq
RUN apt-get dist-upgrade -y -qq
RUN apt-get install -y -qq zsh
RUN apt-get autoremove -y -qq

# install pipx
RUN pip install pipx
RUN pipx ensurepath

RUN pipx --global install poetry black

# setup user, zsh default shell
RUN useradd poetry -m -s /bin/zsh
USER poetry
