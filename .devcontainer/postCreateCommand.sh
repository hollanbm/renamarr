#!/bin/zsh

# create venv
poetry config virtualenvs.in-project true --local

poetry install --no-interaction --no-ansi --quiet

# activate venv
source $(poetry env info --path)/bin/activate

# setup pre-commit hook
pre-commit install
