FROM mcr.microsoft.com/devcontainers/python:3.12

# update base
RUN apt-get update -y -qq
RUN apt-get dist-upgrade -y -qq
RUN apt-get autoremove -y -qq

# install pipx
RUN pip install pipx
RUN pipx ensurepath
RUN pipx install poetry ruff pre-commit pytest
