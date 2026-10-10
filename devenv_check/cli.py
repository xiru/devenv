"""Command line entry point: python -m devenv_check"""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .checks import ENVIRONMENTS, SETTINGS, Status, run_checks
from .platform_info import detect
from .report import make_style, render_json, render_text


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="devenv_check",
        description="Check whether this computer is ready to develop, test and run "
        "Java/Gradle, Go, Node/TypeScript, C/C++, C#/.NET, Docker and Kubernetes projects, "
        "with Git and Visual Studio Code.",
    )
    parser.add_argument("--only", metavar="ENV[,ENV...]",
                        help=f"check only these environments: {', '.join(ENVIRONMENTS)}")
    parser.add_argument("--deep", action="store_true",
                        help="also build and run a hello world program in every environment (slower; "
                             "Docker/Kubernetes tests pull small public images)")
    parser.add_argument("--offline", action="store_true",
                        help="skip checks that need the internet (VS Code and extension update checks)")
    parser.add_argument("--json", action="store_true", help="print machine readable JSON")
    parser.add_argument("-v", "--verbose", action="store_true", help="also show where each tool was found")
    parser.add_argument("--no-hints", action="store_true", help="do not print installation suggestions")
    parser.add_argument("--no-color", action="store_true", help="disable colored output (NO_COLOR is honored too)")
    parser.add_argument("--strict", action="store_true", help="exit non-zero on warnings as well")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

    if args.only:
        keys = [key.strip().lower() for key in args.only.split(",") if key.strip()]
        unknown = [key for key in keys if key not in ENVIRONMENTS]
        if unknown:
            parser.error(f"unknown environment(s): {', '.join(unknown)}; choose from {', '.join(ENVIRONMENTS)}")
        args.only = keys
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    SETTINGS.offline = args.offline
    platform = detect()
    if args.deep and not args.json:
        print("Building and running hello world programs, this can take a few minutes...", file=sys.stderr, flush=True)
    results = run_checks(platform, args.only, deep=args.deep)

    if args.json:
        print(render_json(platform, results))
    else:
        style = make_style(args.no_color)
        print(render_text(platform, results, style, verbose=args.verbose, hints=not args.no_hints))

    failing = {Status.MISSING, Status.WARN} if args.strict else {Status.MISSING}
    return 1 if any(env.status in failing for env in results) else 0
