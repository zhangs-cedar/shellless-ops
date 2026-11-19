"""In-kernel snapshots for diagnostics, not an isolation boundary.

Per request: at most 8 names (128 characters each), 80 characters per
text preview, 24 bytes per bytes preview, and 3 entries per container.
Small exact built-in JSON scalars are returned unchanged. Larger or non-JSON
values use metadata; exact list, tuple and dict previews do not recurse.
Exact sets report size only; other values expose only a type name.
Failures expose at most 8 frames with 240 characters per location field.
"""

from collections import deque
from itertools import islice
from math import isfinite
import sys

_MAX_NAMES = 8
_MAX_NAME = 128
_MAX_TEXT = 80
_MAX_BYTES = 24
_MAX_ITEMS = 3
_MAX_FRAMES = 8
_MAX_LOCATION = 240
_TYPE_NAME = type.__dict__["__name__"]
_TRACEBACK = BaseException.__dict__["__traceback__"]
_SHELL_ATTR = "_shellless_ops_session_probe"


def _optimized_locals_type():
    # On CPython 3.13+, optimized frames use a native frame-locals proxy.
    return type(sys._getframe().f_locals)


_OPTIMIZED_LOCALS_TYPE = _optimized_locals_type()


def _clip(text, limit):
    return str.__getitem__(text, slice(limit))


def _summary(value, *, preview=True):
    kind = type(value)
    if value is None or kind is bool:
        return value
    if kind is int and value.bit_length() <= 53:
        return value
    if kind is float and isfinite(value):
        return value
    if kind is str and len(value) <= _MAX_TEXT:
        return value

    out = {"type": _clip(_TYPE_NAME.__get__(kind), _MAX_TEXT)}
    if kind is int:
        out["bits"] = value.bit_length()
    elif kind is float:
        out["value"] = str(value)
    elif kind is str:
        out.update(value=_clip(value, _MAX_TEXT), length=len(value))
    elif kind is bytes:
        out.update(hex=value[:_MAX_BYTES].hex(), length=len(value))
    elif kind is list or kind is tuple:
        out["length"] = len(value)
        if preview:
            out["preview"] = [_summary(item, preview=False) for item in value[:_MAX_ITEMS]]
    elif kind is dict:
        out["length"] = len(value)
        if preview:
            out["preview"] = [
                [_summary(key, preview=False), _summary(item, preview=False)]
                for key, item in islice(dict.items(value), _MAX_ITEMS)
            ]
    elif kind is set or kind is frozenset:
        out["length"] = len(value)
    return out


class _Probe:
    def __init__(self, shell):
        self._shell = shell
        self.clear()

    def clear(self):
        """Release this probe's references without mutating Python frames."""
        self._last = None
        self._frames = ()

    def _before(self, info):
        self.clear()

    def _after(self, result):
        # Also replace stale state if this execution reached only the post hook.
        self.clear()
        if result is None:
            return
        error = result.error_in_exec
        if error is None:
            error = result.error_before_exec
        if error is None:
            return

        kept = deque(maxlen=_MAX_FRAMES)
        tb = _TRACEBACK.__get__(error)
        while tb is not None and tb.tb_frame.f_globals.get("__name__") in (
            "IPython.core.interactiveshell",
            "IPython.core.compilerop",
        ):
            tb = tb.tb_next
        while tb is not None:
            kept.append((tb.tb_frame, tb.tb_lineno))
            tb = tb.tb_next
        self._frames = tuple(kept)
        self._last = _clip(_TYPE_NAME.__get__(type(error)), _MAX_TEXT)

    def failure(self):
        """Return the last non-silent failure; retained frames are outer-to-inner."""
        if self._last is None:
            return None
        return {
            "type": self._last,
            "frames": [
                {
                    "index": index,
                    "file": _clip(frame.f_code.co_filename, _MAX_LOCATION),
                    "line": line,
                    "function": _clip(frame.f_code.co_name, _MAX_LOCATION),
                }
                for index, (frame, line) in enumerate(self._frames)
            ],
        }

    def inspect(self, names, frame=None):
        """Look up literal names in user_ns or the selected frame's locals only."""
        if (
            (type(names) is not list and type(names) is not tuple)
            or len(names) > _MAX_NAMES
            or any(type(name) is not str or len(name) > _MAX_NAME for name in names)
        ):
            raise ValueError("expected up to eight strings of at most 128 characters")
        if frame is None:
            namespace = self._shell.user_ns
        elif type(frame) is int and 0 <= frame < len(self._frames):
            namespace = self._frames[frame][0].f_locals
        else:
            raise ValueError("invalid failure frame index")

        values = {}
        pending = set(names)
        if pending:
            if issubclass(type(namespace), dict):
                entries = dict.items(namespace)
            elif type(namespace) is _OPTIMIZED_LOCALS_TYPE:
                entries = namespace.items()
            else:
                raise TypeError("unsupported namespace type")
            # Direct dict lookup can invoke equality on a colliding user key.
            for key, value in entries:
                if type(key) is str and key in pending:
                    values[key] = _summary(value)
                    pending.remove(key)
                    if not pending:
                        break
        return {
            "values": values,
            "missing": [name for name in names if name in pending],
            "frame": frame,
        }


def install(shell):
    """Register once on an IPython shell; silent diagnostic calls preserve state."""
    probe = getattr(shell, _SHELL_ATTR, None)
    if probe is None:
        probe = _Probe(shell)
        shell.events.register("pre_run_cell", probe._before)
        shell.events.register("post_run_cell", probe._after)
        setattr(shell, _SHELL_ATTR, probe)
    return probe
