import ast
import json
from pathlib import Path
from queue import Empty
from threading import Lock
from time import monotonic

from jupyter_client import KernelManager
from jupyter_client.kernelspec import KernelSpecManager

__all__ = ["Session"]

_PROBE = "get_ipython()._shellless_ops_session_probe"
_INSTALL = (
    f"{_PROBE} = __import__('shellless_ops_session._probe', "
    "fromlist=['install']).install(get_ipython())"
)


class Session:
    """An isolated namespace in a local kernel for trusted Python code."""

    def __init__(self, *, cwd=None, timeout=10, startup_timeout=20, max_output=2000):
        if not timeout > 0 or not startup_timeout > 0 or max_output < 0:
            raise ValueError("timeouts must be positive and max_output must be nonnegative")
        self.cwd = None if cwd is None else str(Path(cwd).resolve())
        self.timeout = timeout
        self.startup_timeout = startup_timeout
        self.max_output = max_output
        self._lock = Lock()
        self._kernel = None
        self._client = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.reset()

    def reset(self):
        """Discard the kernel. Start a fresh one lazily on the next call."""
        with self._lock:
            self._stop()

    def execute(self, code):
        with self._lock:
            self._start()
            output = []
            remaining = self.max_output
            truncated = False

            def collect(message):
                nonlocal remaining, truncated
                kind = message["msg_type"]
                content = message["content"]
                if kind == "stream":
                    text = content["text"]
                elif kind in ("execute_result", "display_data"):
                    text = content["data"].get("text/plain", "")
                else:
                    return
                truncated |= len(text) > remaining
                if remaining and text:
                    part = text[:remaining]
                    output.append(part)
                    remaining -= len(part)

            failure = None
            try:
                reply = self._request(code, self.timeout, collect=collect)
                status = reply["status"]
                if status == "error":
                    failure = self._query(f"{_PROBE}.failure()")
                    if failure is None:
                        failure = {"type": reply["ename"][:120], "frames": []}
                    failure["message"] = reply["evalue"][:160]
                elif status != "ok":
                    raise RuntimeError(f"Unexpected kernel execution status: {status}")
            except Empty:
                self._stop()
                status = "timeout"
            return {
                "status": status,
                "output": "".join(output),
                "truncated": truncated,
                "failure": failure,
            }

    def inspect(self, *names, frame=None):
        """Inspect explicit identifiers in the namespace or latest failure frame."""
        if len(names) > 8 or any(
            not isinstance(name, str) or len(name) > 128 or not name.isidentifier()
            for name in names
        ):
            raise ValueError("inspect accepts up to eight Python identifiers of at most 128 characters")
        if frame is not None and (type(frame) is not int or not 0 <= frame <= 2**31 - 1):
            raise ValueError("frame must be a nonnegative integer or None")
        with self._lock:
            self._start()
            try:
                return self._query(f"{_PROBE}.inspect({names!r}, {frame!r})")
            except Empty:
                self._stop()
                raise TimeoutError("kernel inspection timed out; the session was reset") from None

    def _start(self):
        if self._kernel is not None:
            return
        # Use IPython's bundled Python kernel, not a user-installed python3 spec.
        self._kernel = KernelManager(
            kernel_name="python3",
            kernel_spec_manager=KernelSpecManager(kernel_dirs=[]),
            ip="127.0.0.1",
            transport_encryption="required",
        )
        try:
            self._kernel.start_kernel(cwd=self.cwd)
            self._client = self._kernel.client()
            self._client.start_channels()
            self._client.wait_for_ready(timeout=self.startup_timeout)
            reply = self._request(_INSTALL, self.startup_timeout, silent=True)
            if reply["status"] != "ok":
                raise RuntimeError(f"Kernel probe installation failed: {reply.get('ename')}")
        except BaseException:
            self._stop()
            raise

    def _stop(self):
        kernel, client = self._kernel, self._client
        self._kernel = self._client = None
        try:
            if client is not None:
                client.stop_channels()
        finally:
            if kernel is not None:
                kernel.shutdown_kernel(now=True)

    def _query(self, expression):
        serializer = "__import__('json').dumps"
        reply = self._request(
            "", self.timeout, silent=True, expressions={"result": f"{serializer}({expression})"}
        )
        result = reply["user_expressions"]["result"]
        if result["status"] != "ok":
            raise ValueError(f"Kernel inspection failed: {result['ename']}")
        return json.loads(ast.literal_eval(result["data"]["text/plain"]))

    def _request(self, code, timeout, *, silent=False, expressions=None, collect=None):
        deadline = monotonic() + timeout
        msg_id = self._client.execute(
            code, silent=silent, store_history=False, user_expressions=expressions, allow_stdin=False
        )

        def receive(get):
            while (seconds := deadline - monotonic()) > 0:
                message = get(timeout=seconds)
                if message["parent_header"].get("msg_id") == msg_id:
                    return message
            raise Empty

        while True:
            message = receive(self._client.get_iopub_msg)
            if (
                message["msg_type"] == "status"
                and message["content"]["execution_state"] == "idle"
            ):
                break
            if collect is not None:
                collect(message)
        return receive(self._client.get_shell_msg)["content"]
