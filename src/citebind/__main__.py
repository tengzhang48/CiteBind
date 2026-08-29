"""Command-line entry point: ``python -m citebind <command>``."""

import argparse
import sys

from .verify import diff, inspect, render_diff, render_report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="citebind")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="inspect a DOCX's CiteBind structures")
    inspect_parser.add_argument("docx")

    diff_parser = subparsers.add_parser("diff", help="diff CiteBind structures between two DOCX files")
    diff_parser.add_argument("before")
    diff_parser.add_argument("after")

    args = parser.parse_args(argv)

    if args.command == "inspect":
        report = inspect(args.docx)
        print(render_report(report, args.docx))
        return 0 if report.is_clean else 1

    if args.command == "diff":
        report = diff(args.before, args.after)
        print(render_diff(report, args.before, args.after))
        return 0 if report.is_clean else 1

    parser.error(f"unknown command: {args.command}")


if __name__ == "__main__":
    sys.exit(main())
