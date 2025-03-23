#!/bin/zsh

ln -sf $PWD/config.yml /config/config.yml

# create venv
poetry config virtualenvs.in-project true --local

poetry install --no-interaction --no-ansi --quiet

# activate venv
source $(poetry env info --path)/bin/activate

# setup pre-commit hook
pre-commit install
