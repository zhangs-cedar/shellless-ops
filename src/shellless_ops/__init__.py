import os
import shutil
import stat
import subprocess
from codecs import lookup
from fnmatch import fnmatchcase
from pathlib import Path

__all__ = ["copy_file", "find_files", "mkdir", "read_text", "run", "search_text", "write_text"]

_SEARCH_EXCLUDES = {".git", ".hg", ".svn", ".venv"}


def mkdir(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_text(path, *, encoding="utf-8"):
    with Path(path).open(encoding=encoding, newline="") as stream:
        return stream.read()


def write_text(path, text, *, encoding="utf-8"):
    path = Path(path)
    with path.open("w", encoding=encoding, newline="") as stream:
        stream.write(text)
    return path


def copy_file(source, target):
    """Copy file contents to a new path without overwriting."""
    target = Path(target)
    with Path(source).open("rb") as reader, target.open("xb") as writer:
        shutil.copyfileobj(reader, writer)
    return target


def find_files(root, pattern="*"):
    """Match file basenames recursively without following directory links."""
    return list(_matching_files(Path(root), pattern))


def _matching_files(root, pattern, *, exclude=()):
    pending = [(root, True)]
    while pending:
        path, directory = pending.pop()
        if not directory:
            yield path
            continue
        children = []
        with os.scandir(path) as entries:
            for entry in entries:
                if exclude and entry.name.casefold() in exclude:
                    continue
                if entry.is_dir(follow_symlinks=False):
                    # Windows junctions are not always reported as symlinks.
                    if os.name == "nt" and (
                        entry.stat(follow_symlinks=False).st_file_attributes
                        & stat.FILE_ATTRIBUTE_REPARSE_POINT
                    ):
                        continue
                    children.append((Path(entry.path), True))
                elif fnmatchcase(entry.name, pattern) and entry.is_file(follow_symlinks=False):
                    children.append((Path(entry.path), False))
        # Include the separator in the sort key so descendants keep path order.
        children.sort(key=lambda item: item[0].name + ("/" if item[1] else ""), reverse=True)
        pending.extend(children)


def search_text(
    root, query, *, pattern="*", limit=50, max_line_chars=240, max_files=1000, encoding="utf-8-sig"
):
    """Return bounded, case-sensitive literal matches, one per line."""
    if not query or "\n" in query or "\r" in query:
        raise ValueError("query must be nonempty and single-line")
    for name, value in (
        ("limit", limit), ("max_line_chars", max_line_chars), ("max_files", max_files)
    ):
        if type(value) is not int or value < 1:
            raise ValueError(f"{name} must be a positive integer")
    try:
        lookup(encoding)
    except LookupError as error:
        raise ValueError(str(error)) from error

    root = Path(root)
    single_file = stat.S_ISREG(root.stat().st_mode)
    paths = [root] if single_file else _matching_files(root, pattern, exclude=_SEARCH_EXCLUDES)
    matches = []
    report = {"matches": matches, "truncated": False, "scan_limited": False, "skipped_decode": 0}
    for file_number, path in enumerate(paths, 1):
        if file_number > max_files:
            report["scan_limited"] = True
            break
        checkpoint = len(matches)
        try:
            with path.open(encoding=encoding) as stream:
                for line_number, line in enumerate(stream, 1):
                    index = line.find(query)
                    if index < 0:
                        continue
                    if len(matches) == limit:
                        report["truncated"] = True
                        return report

                    text = line.removesuffix("\n")
                    clipped = len(text) > max_line_chars
                    if clipped:
                        context = max(0, (max_line_chars - len(query)) // 2)
                        start = min(max(0, index - context), len(text) - max_line_chars)
                        text = text[start:start + max_line_chars]
                    matches.append({
                        "path": path.as_posix(),
                        "line": line_number,
                        "text": text,
                        "text_truncated": clipped,
                    })
        except UnicodeDecodeError as error:
            if single_file:
                raise ValueError(f"{path}: {error}") from error
            del matches[checkpoint:]
            report["skipped_decode"] += 1
        except LookupError as error:
            raise ValueError(f"{path}: {error}") from error
    return report


def run(argv, *, cwd=None, timeout=None, check=True, capture=True, encoding="utf-8"):
    if not isinstance(argv, (list, tuple)) or not argv:
        raise TypeError("argv must be a non-empty list or tuple")
    if os.name == "nt":
        executable = os.fsdecode(argv[0]).rstrip(" .").lower()
        if executable.endswith((".bat", ".cmd")):
            raise ValueError("Windows batch files are not supported")
    return subprocess.run(
        argv,
        cwd=cwd,
        timeout=timeout,
        check=check,
        capture_output=capture,
        encoding=encoding,
        shell=False,
    )
