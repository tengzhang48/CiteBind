"""Command-line entry point: ``python -m citebind <command>``."""

import argparse
import errno
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

from .recovery_model import RecoveryError
from .reference_export import ExportError, FORMATS, export_references
from .spike import check_spike, make_spike, render_spike_report
from .verify import diff, inspect, render_diff, render_report
from .xmlsafe import UnsafeXML


def _write_new_output(output: Path, text: str) -> None:
    """Publish a complete output, with exclusive creation on all filesystems."""
    with tempfile.TemporaryDirectory(dir=output.parent, prefix=".citebind-export-") as directory:
        temporary = Path(directory) / "output"
        with temporary.open("xb") as stream:
            stream.write(text.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, output)
            return
        except OSError as error:
            unsupported = {errno.EPERM, errno.EACCES, errno.EOPNOTSUPP, errno.EINVAL, errno.EXDEV, errno.ENOSYS}
            if error.errno not in unsupported:
                raise
        # FAT/exFAT and some Windows network shares do not support hard
        # links. Exclusive creation still prevents overwriting saved work.
        # Remove our own incomplete output if the copy fails.
        created = None
        try:
            with output.open("xb") as stream, temporary.open("rb") as source:
                created = os.fstat(stream.fileno())
                shutil.copyfileobj(source, stream)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            if created is not None:
                try:
                    current = output.lstat()
                    if (current.st_dev, current.st_ino) == (created.st_dev, created.st_ino):
                        output.unlink()
                except OSError:
                    pass
            raise


def _write_stdout(text: str) -> None:
    """Avoid the Windows redirected-console code page for Unicode exports."""
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        sys.stdout.write(text)
    else:
        sys.stdout.flush()
        buffer.write(text.encode("utf-8"))
        buffer.flush()


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
    check_parser.add_argument(
        "files",
        nargs="+",
        help=(
            "returned files, named as the instructions promise: spike_v1.docx, "
            "step1_reopened.docx, pasted.docx, spike_renamed.docx"
        ),
    )

    recover_parser = subparsers.add_parser(
        "recover-references",
        help="read embedded EndNote/Zotero references without modifying the DOCX",
    )
    recover_parser.add_argument("docx")
    recover_parser.add_argument(
        "--format", choices=FORMATS, default="report",
        help="report retains raw metadata and citation links; library exports do not relink Word citations",
    )
    recover_parser.add_argument("--out", help="create a new UTF-8 output file (existing files are never overwritten)")

    args = parser.parse_args(argv)

    # File-level input problems get a clean message, not a traceback. This
    # includes UnsafeXML: a document whose XML the hardened parser refuses is
    # a bad-input condition, not a library bug. Logic errors (SchemaError,
    # PayloadError, anything else) still propagate: this guard must never
    # mask a bug in the library.
    try:
        return _run(args, parser)
    except (OSError, zipfile.BadZipFile, KeyError, UnsafeXML, RecoveryError) as error:
        if args.command == "make-spike":
            target = args.out
        else:
            target = getattr(args, "docx", None) or getattr(args, "before", None) or (
                args.files if args.command == "check-spike" else None
            )
        print(f"error: {target}: {error}", file=sys.stderr)
        return 2


def _run(args, parser):
    if args.command == "recover-references":
        from .foreign import recover_references

        report = recover_references(args.docx)
        for finding in report.findings:
            print(f"[{finding.severity}] {finding.code}: {finding.message}", file=sys.stderr)
        try:
            exported = export_references(report, args.format)
        except ExportError as error:
            print(str(error), file=sys.stderr)
            return 1
        for finding in exported.findings:
            print(f"[{finding.severity}] {finding.code}: {finding.message}", file=sys.stderr)
        if args.out:
            output = Path(args.out)
            try:
                _write_new_output(output, exported.text)
            except FileExistsError:
                print(f"error: {output}: already exists; choose another --out path", file=sys.stderr)
                return 2
            except OSError as error:
                print(f"error: {output}: {error.strerror or str(error)}", file=sys.stderr)
                return 2
            _write_stdout(f"wrote {output}\n")
        else:
            _write_stdout(exported.text)
        return 1 if report.has_errors else 0

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
        print("next: follow https://github.com/tengzhang48/CiteBind/blob/main/spike/SPIKE_INSTRUCTIONS.md, then run:")
        print("  python -m citebind check-spike <returned files...>")
        return 0

    if args.command == "check-spike":
        report = check_spike(args.files)
        print(render_spike_report(report))
        return 0 if report.all_passed else 1

    parser.error(f"unknown command: {args.command}")


if __name__ == "__main__":
    sys.exit(main())
