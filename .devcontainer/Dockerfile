FROM mcr.microsoft.com/devcontainers/python:3.12

USER root

RUN apt-get update -y -qq && \
    apt-get dist-upgrade -y -qq && \
    apt-get autoremove -y -qq

# git safe directories
RUN git config --global --add safe.directory "*"

RUN apt-get -y -qq install \
    fzf \
    jq \
    yq \
    zsh

RUN mkdir /config
RUN chown vscode:vscode -R /config
RUN chmod 0755 /config

RUN pip install pipx
RUN pipx --global ensurepath
RUN pipx --global install poetry==1.8.3 ruff pre-commit pytest yamale yamllint

USER vscode
