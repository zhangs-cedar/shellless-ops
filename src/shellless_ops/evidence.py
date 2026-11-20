"""Bounded failure evidence for trusted Python runs."""

from collections import deque
from math import isfinite
from pathlib import Path
from tokenize import open as open_source

__all__ = ["capture"]

_TYPE_NAME = type.__dict__["__name__"]
_MAX_FRAMES = 8
_MAX_TEXT = 160


def _type_name(kind):
    # A class name can be a str subclass with its own __getitem__.
    return str.__getitem__(_TYPE_NAME.__get__(kind), slice(80))


def _summary(value):
    kind = type(value)
    if value is None or kind is bool:
        return value
    if kind is int and value.bit_length() <= 53:
        return value
    if kind is float and isfinite(value):
        return value
    if kind is str:
        if len(value) <= _MAX_TEXT:
            return value
        return {"type": "str", "text": value[:_MAX_TEXT], "length": len(value)}
    if any(kind is container for container in (bytes, dict, list, tuple, set, frozenset)):
        return {"type": _type_name(kind), "length": len(value)}
    if kind is int:
        return {"type": "int", "bits": value.bit_length()}
    return {"type": _type_name(kind)}


def _local_values(frame, names):
    namespace = frame.f_locals
    # Function locals use a native frame-locals proxy on newer CPython.
    if issubclass(type(namespace), dict):
        items = dict.items(namespace)
    elif type(namespace) is _FUNCTION_LOCALS:
        items = namespace.items()
    else:
        return {}
    wanted = set(names)
    values = {}
    for key, value in items:
        if type(key) is str and key in wanted:
            values[key] = _summary(value)
            wanted.remove(key)
            if not wanted:
                break
    return values


def _function_locals_type():
    from sys import _getframe

    return type(_getframe().f_locals)


_FUNCTION_LOCALS = _function_locals_type()


def _source_excerpt(filename, line, root):
    if filename.startswith("<"):
        return None
    try:
        path = Path(filename).resolve()
        if (path != root and root not in path.parents) or not path.is_file():
            return None
        with open_source(path) as stream:
            return [
                {"line": number, "text": text.rstrip("\r\n")[:240]}
                for number, text in zip(range(1, line + 3), stream)
                if number >= line - 2
            ] or None
    except (OSError, RuntimeError, ValueError, SyntaxError):
        return None


def _failure(kind, tb, names, source_root):
    frames = deque(maxlen=_MAX_FRAMES)
    while tb is not None:
        frames.append(tb)
        tb = tb.tb_next
    locations = []
    for item in frames:
        code = item.tb_frame.f_code
        locations.append({
            "path": code.co_filename[:512],
            "line": item.tb_lineno,
            "function": code.co_name[:80],
        })
    values = {}
    source = None
    if frames:
        innermost = frames[-1]
        frame = innermost.tb_frame
        if names:
            values = _local_values(frame, names)
        if source_root is not None:
            source = _source_excerpt(frame.f_code.co_filename, innermost.tb_lineno, source_root)
    return {
        "type": _type_name(kind),
        "frames": locations,
        "values": values,
        "missing": [name for name in names if name not in values],
        "source": source,
    }


class _Capture:
    def __init__(self, names, source_root):
        self.names = names
        self.source_root = source_root

    def __enter__(self):
        self.report = {"failure": None}
        return self.report

    def __exit__(self, kind, error, tb):
        if error is None or not issubclass(kind, Exception):
            return
        try:
            self.report["failure"] = _failure(kind, tb, self.names, self.source_root)
        except Exception as capture_error:
            # Optional diagnostics must never replace the original failure.
            self.report["capture_error"] = _type_name(type(capture_error))


def capture(*, names=(), source_root=None):
    """Collect opt-in evidence when an exception escapes the block, without suppressing it."""
    if not isinstance(names, (list, tuple)) or len(names) > 8 or any(
        type(name) is not str or len(name) > 128 or not name.isidentifier() for name in names
    ):
        raise ValueError("names must contain at most eight Python identifiers of up to 128 characters")
    root = None if source_root is None else Path(source_root).resolve()
    return _Capture(tuple(names), root)
