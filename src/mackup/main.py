"""Mackup.

Keep your application settings in sync.
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

By default, Mackup syncs all application data via
Dropbox, but may be configured to exclude applications or use a different
backend with a .mackup.cfg file.

See https://github.com/lra/mackup/tree/master/doc for more information.

"""

import sys
from dataclasses import dataclass
from typing import Any

from docopt import DocoptExit, docopt

from . import utils
from .application import ApplicationProfile
from .appsdb import ApplicationsDatabase
from .constants import MACKUP_APP_NAME, VERSION
from .drift import Drift, drift_has_errors, render_drift, render_drift_json
from .mackup import Mackup
from .restore_plan import (
    RestoreChange,
    render_restore_plan,
    render_restore_plan_json,
    restore_plan_has_blockers,
)

USAGE_ERROR = 2


class ColorFormatCodes:
    BLUE = "\033[34m"
    BOLD = "\033[1m"
    NORMAL = "\033[0m"


def header(text: str) -> str:
    return ColorFormatCodes.BLUE + text + ColorFormatCodes.NORMAL


def bold(text: str) -> str:
    return ColorFormatCodes.BOLD + text + ColorFormatCodes.NORMAL


@dataclass
class _Context:
    """Shared state threaded through the command handlers."""

    config_file: str | None
    mckp: Mackup
    app_db: ApplicationsDatabase
    dry_run: bool
    verbose: bool


def _print_app_header(app_name: str, verbose: bool) -> None:
    if verbose:
        header_str = header("---")
        print(f"\n{header_str} {bold(app_name)} {header_str}")


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
            sys.exit(f"Unsupported application: {app_name}")
        return {app_name}
    return ctx.mckp.get_apps_to_backup()


def _run_action(ctx: _Context, app_names: set[str], action: str) -> None:
    """Run an ApplicationProfile method over each app, in sorted order."""
    for app_name in sorted(app_names):
        app = ApplicationProfile(
            ctx.mckp,
            ctx.app_db.get_files(app_name),
            ctx.dry_run,
            ctx.verbose,
        )
        _print_app_header(app_name, ctx.verbose)
        getattr(app, action)()


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
        sys.exit(f"Unsupported application: {requested_app_name}")
    print(f"Name: {app_db.get_name(requested_app_name)}")
    print("Configuration files:")
    for file in app_db.get_files(requested_app_name):
        print(f" - {file}")


def _cmd_backup(args: dict[str, Any], ctx: _Context) -> None:
    # Resolve and validate the target apps before the env check, so an
    # unknown application name fails cleanly without creating the Mackup
    # folder or prompting first.
    app_names = _resolve_apps(args["<application>"], ctx)
    ctx.mckp.check_for_usable_backup_env()

    # Create a backup of the files of each application
    _run_action(ctx, app_names, "copy_files_to_mackup_folder")


def _cmd_restore(args: dict[str, Any], ctx: _Context) -> None:
    app_names = _resolve_apps(args["<application>"], ctx)
    ctx.mckp.check_for_usable_restore_env()

    if ctx.dry_run:
        changes: list[RestoreChange] = []
        for app_name in sorted(app_names):
            app = ApplicationProfile(
                ctx.mckp,
                ctx.app_db.get_files(app_name),
                ctx.dry_run,
                ctx.verbose,
            )
            changes.extend(app.restore_plan(app_name))
        if args["--json"]:
            render_restore_plan_json(changes)
        else:
            render_restore_plan(changes)
        if restore_plan_has_blockers(changes):
            raise SystemExit(1)
        return

    # Recover a backup of the files of each application
    _run_action(ctx, app_names, "copy_files_from_mackup_folder")


def _cmd_diff(args: dict[str, Any], ctx: _Context) -> None:
    """Inspect configured paths without changing either side."""
    app_names = _resolve_apps(args["<application>"], ctx)
    ctx.mckp.check_for_usable_restore_env()
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


def _cmd_link_install(args: dict[str, Any], ctx: _Context) -> None:
    app_names = _resolve_apps(args["<application>"], ctx)
    # Check the env where the command is being run
    ctx.mckp.check_for_usable_backup_env()

    # Create a link for each application
    _run_action(ctx, app_names, "link_install")


def _cmd_link_uninstall(args: dict[str, Any], ctx: _Context) -> None:
    # Validate any named application before the env check, so an unknown
    # name fails cleanly before any prompt or side effect.
    named_apps = (
        _resolve_apps(args["<application>"], ctx) if args["<application>"] else None
    )

    # Check the env where the command is being run
    ctx.mckp.check_for_usable_restore_env()

    if named_apps is not None:
        # Unlink only the named application, leaving the rest of Mackup
        # (and the Mackup config itself) in place. No global confirmation
        # is needed since the user explicitly scoped the uninstall.
        _run_action(ctx, named_apps, "link_uninstall")

    elif ctx.dry_run or (
        utils.confirm(
            "You are going to uninstall Mackup.\n"
            "Every configuration file, setting and dotfile"
            " managed by Mackup will be unlinked and copied back"
            " to their original place, in your home folder.\n"
            "Are you sure?",
        )
    ):
        # Uninstall the apps except Mackup, which we'll uninstall last, to
        # keep the settings as long as possible
        app_names = ctx.mckp.get_apps_to_backup()
        app_names.discard(MACKUP_APP_NAME)

        _run_action(ctx, app_names, "link_uninstall")

        # Restore the Mackup config before any other config, as we might
        # need it to know about custom settings
        mackup_app = ApplicationProfile(
            ctx.mckp,
            ctx.app_db.get_files(MACKUP_APP_NAME),
            ctx.dry_run,
            ctx.verbose,
        )
        mackup_app.link_uninstall()

        # Delete the Mackup folder in Dropbox
        # Don't delete this as there might be other Macs that aren't
        # uninstalled yet
        # delete(mckp.mackup_folder)

        print(
            "\n"
            "All your files have been put back into place. You can now"
            " safely uninstall Mackup.\n"
            "\n"
            "Thanks for using Mackup!",
        )


def _cmd_link(args: dict[str, Any], ctx: _Context) -> None:
    # Validate any named application before the env check.
    named_apps = (
        _resolve_apps(args["<application>"], ctx) if args["<application>"] else None
    )

    # Check the env where the command is being run
    ctx.mckp.check_for_usable_restore_env()

    if named_apps is not None:
        # Link only the named application. No need to restore the Mackup
        # config first, as the app set is fixed and config-independent here.
        _run_action(ctx, named_apps, "link")
        return

    # Restore the Mackup config before any other config, as we might
    # need it to know about custom settings
    mackup_app = ApplicationProfile(
        ctx.mckp,
        ctx.app_db.get_files(MACKUP_APP_NAME),
        ctx.dry_run,
        ctx.verbose,
    )
    _print_app_header(MACKUP_APP_NAME, ctx.verbose)
    mackup_app.link()

    # Initialize again the apps db, as the Mackup config might have
    # changed it
    ctx.mckp = Mackup(ctx.config_file)
    ctx.app_db = ApplicationsDatabase()

    # Restore the rest of the app configs, using the restored Mackup config
    app_names = ctx.mckp.get_apps_to_backup()
    # Mackup has already been done
    app_names.discard(MACKUP_APP_NAME)

    _run_action(ctx, app_names, "link")


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
        print(error, file=sys.stderr)
        raise SystemExit(USAGE_ERROR) from error

    if args["--json"] and not args["diff"]:
        sys.exit("Option --json requires diff.")

    config_file: str | None = args.get("--config-file")
    ctx = _Context(
        config_file=config_file,
        mckp=Mackup(config_file),
        app_db=ApplicationsDatabase(args["--applications-dir"]),
        dry_run=True,
        verbose=False,
    )

    if args["list"]:
        ctx.mckp.check_for_usable_environment()
        _cmd_list(ctx.app_db)
    elif args["show"]:
        ctx.mckp.check_for_usable_environment()
        _cmd_show(args, ctx.app_db)
    elif args["diff"]:
        _cmd_diff(args, ctx)
