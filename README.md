# Mackup

This fork is a read-only index of configuration drift. It uses Mackup's
application database to map reference paths to their live locations without
backing up, restoring, linking, or printing configuration contents.

## Install

The dotfiles repository pins and runs this fork directly with uv. For local
development:

```bash
uv sync --locked
uv run mackup --help
```

## Inspect

The configured storage directory is the reference side. `$HOME` is the live
side.

```bash
mackup diff
mackup diff git
mackup --json diff
mackup --applications-dir ./applications --json diff
```

Reports contain application names, paths, drift kinds, file kinds, and
inspection errors. They never contain file contents or hashes. Ordinary drift
returns status `0`; unreadable paths return status `1`; malformed invocations
return status `2`.

`--applications-dir` loads custom application mappings from an explicit
directory instead of requiring an installed `~/.mackup` directory. The normal
stock application database remains available for mappings that are not
overridden there.

## Development

```bash
uv run --locked ruff check .
uv run --locked mypy src/mackup
uv run --locked ty check
uv run --locked pytest
```

The original project is [lra/mackup](https://github.com/lra/mackup). This fork
keeps its GPL-3.0-or-later license.
