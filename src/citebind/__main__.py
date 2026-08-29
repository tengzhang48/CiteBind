"""Command-line entry point: ``python -m citebind <command>``."""

import argparse
import sys

from .spike import check_spike, make_spike, render_spike_report
from .verify import diff, inspect, render_diff, render_report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="citebind")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="inspect a DOCX's CiteBind structures")
    inspect_parser.add_argument("docx")

    diff_parser = subparsers.add_parser("diff", help="diff CiteBind structures between two DOCX files")
    diff_parser.add_argument("before")
    diff_parser.add_argument("after")

    make_parser = subparsers.add_parser(
        "make-spike", help="generate the Phase 1 spike fixture (spike/spike_v1.docx)"
    )
    make_parser.add_argument("--out", default="spike", help="output directory")

    check_parser = subparsers.add_parser(
        "check-spike", help="grade returned spike files, one verdict per probe"
    )
    check_parser.add_argument("docx", help="the returned main spike document")
    check_parser.add_argument(
        "extras", nargs="*", help="other returned files (pasted copy, save-as copy)"
    )

    args = parser.parse_args(argv)

    if args.command == "inspect":
        report = inspect(args.docx)
        print(render_report(report, args.docx))
        return 0 if report.is_clean else 1

    if args.command == "diff":
        report = diff(args.before, args.after)
        print(render_diff(report, args.before, args.after))
        return 0 if report.is_clean else 1

    if args.command == "make-spike":
        path = make_spike(args.out)
        print(f"wrote {path}")
        print("next: follow spike/SPIKE_INSTRUCTIONS.md, then run:")
        print("  python -m citebind check-spike <returned files...>")
        return 0

    if args.command == "check-spike":
        report = check_spike(args.docx, args.extras)
        print(render_spike_report(report))
        return 0 if report.all_passed else 1

    parser.error(f"unknown command: {args.command}")


if __name__ == "__main__":
    sys.exit(main())
