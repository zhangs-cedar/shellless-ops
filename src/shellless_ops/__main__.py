import argparse
import json
import subprocess
import sys

from . import copy_file, find_files, mkdir, read_text, run, write_text


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
    execute = commands.add_parser("run", help="invoke an executable with separate arguments")
    execute.add_argument("--cwd")
    execute.add_argument("--timeout", type=float)
    execute.add_argument("argv", nargs=argparse.REMAINDER)
    args = parser.parse_args()
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
