import argparse
import json
import runpy
import subprocess
import sys
from pathlib import Path

from . import copy_file, find_files, mkdir, read_text, run, search_text, write_text
from .evidence import capture


def _run_evidence(args, parser):
    if args.script[:1] == ["--"]:
        args.script.pop(0)
    if not args.script:
        parser.error("a Python script is required")

    try:
        script = Path(args.script[0]).resolve()
        manager = capture(names=args.var, source_root=args.source_root)
        if not script.is_file():
            parser.error(f"script is not a file: {script}")
        command = [sys.executable, str(script), *args.script[1:]]
        repro = {"argv": command if args.record_args else command[:2], "cwd": str(Path.cwd())}
        if not args.record_args and len(command) > 2:
            repro["omitted_args"] = len(command) - 2
        if args.code_version is not None:
            repro["code_version"] = args.code_version
        stream = Path(args.output).open("x", encoding="utf-8", errors="backslashreplace")
    except (OSError, ValueError) as error:
        parser.exit(1, f"shellless-ops: {error}\n")

    argv, path = sys.argv, sys.path
    sys.argv = command[1:]
    sys.path = [str(script.parent), *path]
    try:
        with manager as report:
            runpy.run_path(str(script), run_name="__main__")
    finally:
        sys.argv, sys.path = argv, path
        # Finalization errors must not change an active script exception.
        active_error = sys.exc_info()[1]
        try:
            with stream:
                json.dump(
                    {"repro": repro, **report}, stream, ensure_ascii=False, separators=(",", ":")
                )
                stream.write("\n")
        except OSError:
            if active_error is None:
                raise
            print("shellless-ops: could not write evidence report", file=sys.stderr)
    return 0


def main():
    parser = argparse.ArgumentParser(
        prog="shellless-ops", description="Common file and process operations"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("mkdir", help="create a directory and its parents").add_argument("path")
    commands.add_parser("read", help="read UTF-8 text").add_argument("path")
    write = commands.add_parser("write", help="write UTF-8 text")
    write.add_argument("path")
    write.add_argument("text", help="use -- before the path if text starts with a dash")
    copy = commands.add_parser("copy", help="copy a file without overwriting")
    copy.add_argument("source")
    copy.add_argument("target")
    find = commands.add_parser("find", help="return matching file paths as JSON")
    find.add_argument("root")
    find.add_argument("--pattern", default="*")
    search = commands.add_parser("search", help="return bounded literal text matches as JSON")
    search.add_argument("root")
    search.add_argument("query")
    search.add_argument("--pattern", default="*")
    search.add_argument("--limit", type=int, default=50)
    search.add_argument("--max-line-chars", type=int, default=240)
    search.add_argument("--max-files", type=int, default=1000)
    search.add_argument("--encoding", default="utf-8-sig")
    execute = commands.add_parser("run", help="invoke an executable with separate arguments")
    execute.add_argument("--cwd")
    execute.add_argument("--timeout", type=float)
    execute.add_argument("argv", nargs=argparse.REMAINDER)
    evidence = commands.add_parser("evidence", help="run a Python script and write failure evidence")
    evidence.add_argument("--output", required=True, help="new JSON report file")
    evidence.add_argument("--var", action="append", default=[], help="local name to include on failure")
    evidence.add_argument("--source-root", help="include a source excerpt inside this directory")
    evidence.add_argument("--code-version", help="caller-supplied revision for reproduction")
    evidence.add_argument("--record-args", action="store_true", help="include script arguments in the report")
    evidence.add_argument("script", nargs=argparse.REMAINDER, help="script file and its arguments")
    args = parser.parse_args()
    if args.command == "evidence":
        return _run_evidence(args, evidence)
    if args.command == "run":
        if args.argv[:1] == ["--"]:
            args.argv.pop(0)
        if not args.argv:
            execute.error("an executable is required")
    try:
        if args.command == "mkdir":
            mkdir(args.path)
        elif args.command == "read":
            sys.stdout.buffer.write(read_text(args.path).encode("utf-8"))
        elif args.command == "write":
            write_text(args.path, args.text)
        elif args.command == "copy":
            copy_file(args.source, args.target)
        elif args.command == "find":
            print(json.dumps([path.as_posix() for path in find_files(args.root, args.pattern)]))
        elif args.command == "search":
            result = search_text(
                args.root, args.query, pattern=args.pattern, limit=args.limit,
                max_line_chars=args.max_line_chars, max_files=args.max_files, encoding=args.encoding,
            )
            data = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
            sys.stdout.buffer.write((data + "\n").encode("utf-8", "backslashreplace"))
        else:
            result = run(
                args.argv, cwd=args.cwd, timeout=args.timeout, check=False, capture=False
            )
            code = result.returncode
            return 128 - code if code < 0 else code
    except subprocess.TimeoutExpired as error:
        parser.exit(124, f"{parser.prog}: {error}\n")
    except (OSError, ValueError) as error:
        parser.exit(1, f"{parser.prog}: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
