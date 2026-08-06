# Local Setup

## Requirements

- [mise 2026.8.2 or newer](https://mise.jdx.dev/)
- A Docker-compatible runtime for building the container image (optional)
- Dependency locking is configured for macOS and Linux environments only

You will need to create `config.yml` in the [config](../config/) folder in the root of the repo.

```shell
mise install

mise run sync

mise run check

mise run audit

mise run docker-build

uv run python src/main.py
```

## python-dotenv

renamarr automatically loads `.env.local` file at startup when one is present.

The following variables are set in the included `.env.local`.

| Variable        | Value      | Purpose                                                                      |
| --------------- | ---------- | ---------------------------------------------------------------------------- |
| `CONFIG_DIR`    | `./config` | Uses the repo-local `config/` directory so local `config.yml` is discovered. |
| `LOG_LEVEL`     | `DEBUG`    | Enables verbose local logging.                                               |
| `LOG_DIR`       | `./logs`   | Writes local log files to the repo-local `logs/` directory.                  |
| `LOG_ROTATION`  | `00:00`    | Rotates log files daily at midnight.                                         |
| `LOG_RETENTION` | `7 days`   | Retains rotated log files for seven days.                                    |

## direnv

```shell
direnv allow
```

The included `.envrc` sets:

| Variable      | Value                   | Purpose                                                                           |
| ------------- | ----------------------- | --------------------------------------------------------------------------------- |
| `BRANCH_NAME` | current git branch name | used for image tag when building with [docker-compose.yml](../docker-compose.yml) |
