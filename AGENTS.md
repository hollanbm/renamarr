# Coding Agent Instructions

Guidance on how to navigate and modify this codebase.

## Code Change Requirements

- Use the uv CLI for all dependency and project changes. Do not edit
  `pyproject.toml` or `uv.lock` directly.
- Whenever code is changed:
    * ensure all prek checks pass (`prek run --all-files`)
    * Newly added code must keep 100% line and branch coverage.
- When running ad-hoc Python (inspecting objects, small scripts, etc.), use
  `uv run python` so the project venv and pinned dependencies are active.
- Update README.md whenever behaviour or feature changes are introduced.
- Diagnose bugs before patching: avoid speculative “symptom” fixes. When behaviour is
  unclear, instrument or reproduce minimally to identify the exact cause before
  landing code changes; prefer root-cause fixes over defensive clean-ups.

## Project Structure

- **src/** – All application code lives here.
- **tests/** – Unit tests; uses pytest (tests sub-directory structure stays in sync with the src directory). Test modules (in most cases) are namedaccording to the src module they are testing (just with a `test_` prefix)
- **coverage.xml** - code coverage analysis
- **pyproject.toml** - Package configuration
- **.pre-commit-config.yaml** - Pre-commit linters and some configuration
- **uv-secure.toml** - uv dependency vulnerability scanner configuration
- **.yamllint.yaml** - Yaml linter configuration
- **.envrc** - environment variables useful for development purposes

## Code Style

- Run `uv run ruff format` after every meaningful edit
- Follow the
  [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html)
  for all code contributions, including Google-style docstrings.
- Use **type hinting** consistently throughout the codebase with the strongest most
  specific type hints possible. Type casting is forbidden and Any types should be kept
  to a minimum. Type ignores should almost never be used, other than for third party
  packages with no typing or dynamic typing.
- Don't create sub-packages (no `__init__.py` files) in the test directories, a
  consequence of this test strategy is no duplicate module (.py file) names are allowed
  anywhere in this repo (with the exception of `__init__.py` and `conftest.py` files)
  since pytest can't support duplicate test file names without sub-packages.
- Use the most modern Python idioms and syntax allowed by the minimum supported Python
  version (currently this is Python 3.14).
- Comments should be kept to an absolute minimum, try to achieve code readability
  through meaningful class, function, and variable names. Public functions should have
  Google-style docstrings; parameters only need to be documented if the name and type
  hint don't convey the full semantics. Private functions used within a module don't
  need docstrings (unless their names and type hints aren't sufficient to convey their
  semantics).
- Comments should only be used to explain unavoidable code smells (arising from third
  party package use), or the reason for temporary dependency version pinning (e.g.
  linking an unresolved GitHub issues) or lastly explaining opaque code or non-obvious
  trade offs or workarounds.
- Please keep all imports at the top of the module unless necessary to avoid circular
  imports

## Development Environment / Terminal

- The repo runs on macOS and Linux. Confirm the shell environment before
  assuming POSIX semantics.
- Being a uv project you never need to activate a virtual environment or call pip
  directly. Use `uv add` for dependencies and `uv run` for scripts or tooling.
- Never `git commit`, `git push`, or open/create pull requests unless the user
  explicitly asks or gives consent for those actions.

## Automated Tests

- Tests treat warnings as errors. Fix warnings raised by this repo.
- Prefer the `pytest-mock` `mocker` fixture for patching and creating mocks in tests.
  Avoid using `pytest.MonkeyPatch` directly when `mocker` can cover the case.
- When test expectations change, ensure the test name still matches the behaviour. If
  semantics change, rename the test or adjust the implementation so the original test
  name remains accurate.
- Skip test docstrings and comments; describe intent through descriptive names and
  param ids.
- Each new test should meaningfully increase coverage. Aim for full branch coverage
  while keeping the ratio of test code to src code lean.

## Docker

- If changes are made to `./Dockerfile` or `docker-compose.yml` validate these changes by building the image with `docker compose build`
