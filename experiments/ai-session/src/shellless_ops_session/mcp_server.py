"""Local stdio tools for trusted Python code, not a sandbox."""

import asyncio
import json
import logging
import re
from pathlib import Path

from mcp.server import MCPServer
from mcp.types import TextContent

from . import Session

_MAX_SESSIONS = 4
_SESSION_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_LOG = logging.getLogger(__name__)


def _text(result):
    # Use one compact JSON block, also readable by clients that only display content.
    return TextContent(type="text", text=json.dumps(result, separators=(",", ":")))


def _close_session(session):
    try:
        session.reset()
    except Exception:
        _LOG.exception("Could not shut down a local kernel")


def main():
    cwd = Path.cwd()
    sessions = {}
    pending = {}
    server = MCPServer(
        "shellless-ops-session",
        instructions=(
            "For trusted local Python code only; sessions are separate processes, not a sandbox. "
            "Choose an explicit session_id (1–64 ASCII letters, digits, underscores or hyphens). "
            "Reset unused sessions to free a slot."
        ),
    )

    async def call(session_id, operation, *, create=False, release=False):
        if not _SESSION_ID.fullmatch(session_id):
            return {"status": "invalid_session_id"}
        if session_id in pending:
            return {"status": "busy"}
        session = sessions.get(session_id)
        is_new = session is None
        if session is None:
            if not create:
                return {"status": "not_found"}
            if len(sessions) >= _MAX_SESSIONS:
                return {"status": "session_limit", "limit": _MAX_SESSIONS}
            session = sessions[session_id] = Session(cwd=cwd)

        async def run():
            try:
                result = await asyncio.to_thread(operation, session)
                if release or result.get("status") == "timeout":
                    sessions.pop(session_id)
                return result
            except Exception as error:
                if is_new:
                    # Failed startup must not reserve a slot or let inspect retry it.
                    await asyncio.to_thread(_close_session, session)
                    sessions.pop(session_id)
                elif release or (not create and isinstance(error, TimeoutError)):
                    # Session.reset and a timed-out inspect discard their kernels.
                    sessions.pop(session_id)
                raise
            finally:
                pending.pop(session_id)

        task = pending[session_id] = asyncio.create_task(run())
        # A canceled MCP request must not free the label while its thread still runs.
        task.add_done_callback(lambda finished: None if finished.cancelled() else finished.exception())
        return await asyncio.shield(task)

    @server.tool(structured_output=False)
    async def execute(session_id: str, code: str) -> TextContent:
        """Execute trusted local Python, preserving state under this session label."""
        return _text(await call(session_id, lambda session: session.execute(code), create=True))

    @server.tool(structured_output=False)
    async def inspect(session_id: str, names: list[str], frame: int | None = None) -> TextContent:
        """Inspect named values in an existing session or its selected failure frame."""
        return _text(await call(session_id, lambda session: session.inspect(*names, frame=frame)))

    @server.tool(structured_output=False)
    async def reset(session_id: str) -> TextContent:
        """Release this session and its state; the next execute starts fresh."""

        def stop(session):
            session.reset()
            return {"status": "ok"}

        return _text(await call(session_id, stop, release=True))

    try:
        asyncio.run(server.run_stdio_async())
    finally:
        # asyncio.run drains the worker executor before we touch any remaining sessions.
        for session in sessions.values():
            _close_session(session)


if __name__ == "__main__":
    main()
