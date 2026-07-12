"""Mackup read-only configuration inspection.

Copyright (C) 2013-2025 Laurent Raufaste <http://glop.org/>

Usage:
  mackup [options] list
  mackup [options] show <application>
  mackup [options] diff [<application>]
  mackup (-h | --help)

Options:
  -h --help                 Show this screen.
  --json                    Emit a machine-readable inspection report.
  -c --config-file=<path>   Specify custom config file path.
  --applications-dir=<path> Load custom application files from this directory.
  --version                 Show version.

Modes of action:
 - mackup list: display a list of all supported applications.
 - mackup show: display the details for a supported application.
 - mackup diff: report location-only differences without changing files.

diff inspects every configured application by default. Name one application to
limit the report without changing the configured application set.

The configured storage directory is the reference side. The current home
directory is the live side.

See https://github.com/lra/mackup/tree/master/doc for more information.

"""

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from docopt import DocoptExit, docopt

from .application import ApplicationProfile
from .appsdb import ApplicationsDatabase
from .constants import VERSION
from .drift import Drift, drift_has_errors, render_drift, render_drift_json
from .mackup import Mackup

USAGE_ERROR = 2


@dataclass
class _Context:
    """Shared state threaded through the command handlers."""

    mckp: Mackup
    app_db: ApplicationsDatabase


def _usage_error(message: str) -> NoReturn:
    print(message, file=sys.stderr)
    raise SystemExit(USAGE_ERROR)


def _resolve_apps(app_name: str | None, ctx: _Context) -> set[str]:
    """Resolve which apps a per-app command should act on.

    If an application is named, error out when it is not a supported app
    (like the `show` command) and otherwise act on exactly that app,
    overriding the config's applications_to_sync / applications_to_ignore
    lists. If no application is named, fall back to every configured
    application.
    """
    if app_name:
        if app_name not in ctx.app_db.get_app_names():
            _usage_error(f"Unsupported application: {app_name}")
        return {app_name}
    return ctx.mckp.get_apps_to_backup(ctx.app_db)


def _cmd_list(app_db: ApplicationsDatabase) -> None:
    output: str = "Supported applications:\n"
    for app_name in sorted(app_db.get_app_names()):
        output += f" - {app_name}\n"
    output += "\n"
    output += (
        f"{len(app_db.get_app_names())} applications supported in Mackup v{VERSION}"
    )
    print(output)


def _cmd_show(args: dict[str, Any], app_db: ApplicationsDatabase) -> None:
    requested_app_name: str = args["<application>"]

    # Make sure the app exists
    if requested_app_name not in app_db.get_app_names():
        _usage_error(f"Unsupported application: {requested_app_name}")
    print(f"Name: {app_db.get_name(requested_app_name)}")
    print("Configuration files:")
    for file in app_db.get_files(requested_app_name):
        print(f" - {file}")


def _cmd_diff(args: dict[str, Any], ctx: _Context) -> None:
    """Inspect configured paths without changing either side."""
    app_names = _resolve_apps(args["<application>"], ctx)
    ctx.mckp.check_for_usable_inspection_env()
    changes: list[Drift] = []
    for app_name in sorted(app_names):
        app = ApplicationProfile(
            ctx.mckp,
            ctx.app_db.get_files(app_name),
            dry_run=True,
            verbose=False,
        )
        changes.extend(app.drift(app_name))
    if args["--json"]:
        render_drift_json(changes)
    else:
        render_drift(changes)
    if drift_has_errors(changes):
        raise SystemExit(1)


def main() -> None:
    """Main function."""
    # Get the command line arg
    docstring = __doc__
    if not docstring:
        sys.exit(
            "Usage information is not available because __doc__ is None. "
            "This can happen when running Python with optimizations (python -OO). "
            "Please run Mackup without -OO to use the command-line interface.",
        )
    assert docstring is not None  # for type narrowing after sys.exit

    try:
        args: dict[str, Any] = docopt(docstring, version=f"Mackup {VERSION}")
    except DocoptExit as error:
        _usage_error(str(error))

    if args["--json"] and not args["diff"]:
        _usage_error("Option --json requires diff.")

    applications_dir: str | None = args["--applications-dir"]
    if applications_dir and not Path(applications_dir).is_dir():
        _usage_error(
            f"Applications directory is not a directory: {applications_dir}",
        )

    app_db = ApplicationsDatabase(applications_dir)

    if args["list"]:
        _cmd_list(app_db)
    elif args["show"]:
        _cmd_show(args, app_db)
    elif args["diff"]:
        config_file: str | None = args.get("--config-file")
        ctx = _Context(mckp=Mackup(config_file), app_db=app_db)
        _cmd_diff(args, ctx)
