import os
import shutil
import stat
import subprocess
from fnmatch import fnmatchcase
from pathlib import Path

__all__ = ["copy_file", "find_files", "mkdir", "read_text", "run", "write_text"]


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
    root = Path(root)
    files = []
    pending = [root]
    while pending:
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                if entry.is_dir(follow_symlinks=False):
                    # Windows junctions are not always reported as symlinks.
                    if os.name == "nt" and (
                        entry.stat(follow_symlinks=False).st_file_attributes
                        & stat.FILE_ATTRIBUTE_REPARSE_POINT
                    ):
                        continue
                    pending.append(Path(entry.path))
                elif fnmatchcase(entry.name, pattern) and entry.is_file(follow_symlinks=False):
                    files.append(Path(entry.path))
    return sorted(files, key=lambda path: path.relative_to(root).as_posix())


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
