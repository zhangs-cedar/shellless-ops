import asyncio
import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


@unittest.skipUnless(importlib.util.find_spec("mcp"), "install the optional [mcp] extra")
class MCPStdioTests(unittest.IsolatedAsyncioTestCase):
    def client(self):
        from mcp import Client, StdioServerParameters

        pythonpath = os.environ.get("PYTHONPATH")
        return Client(
            StdioServerParameters(
                command=sys.executable,
                args=["-m", "shellless_ops_session.mcp_server"],
                env=None if pythonpath is None else {"PYTHONPATH": pythonpath},
            ),
            read_timeout_seconds=45,
        )

    async def call_tool(self, client, name, session_id, **arguments):
        result = await client.call_tool(name, {"session_id": session_id, **arguments})
        self.assertFalse(result.is_error, result)
        self.assertIsNone(result.structured_content, result)
        self.assertEqual(len(result.content), 1, result)
        block = result.content[0]
        self.assertEqual(block.type, "text", result)
        payload = json.loads(block.text)
        self.assertIsInstance(payload, dict, result)
        self.assertEqual(block.text, json.dumps(payload, separators=(",", ":")))
        return payload

    async def test_tools_keep_sessions_isolated_and_reset_only_one(self):
        async with self.client() as client:
            tools = await client.list_tools()
            self.assertCountEqual(
                [tool.name for tool in tools.tools], ["execute", "inspect", "reset"],
            )

            for label, value in (("left", 11), ("right", 22)):
                result = await self.call_tool(
                    client, "execute", label, code=f"shared = {value}\nprint(shared)",
                )
                self.assertEqual(result["status"], "ok", result)
                self.assertEqual(result["output"], f"{value}\n")

            failure = await self.call_tool(
                client, "execute", "left",
                code="def fail():\n    local = shared\n    raise ValueError('test')\nfail()",
            )
            self.assertEqual(failure["status"], "error", failure)
            self.assertEqual(failure["failure"]["type"], "ValueError")
            frame = next(
                frame["index"] for frame in failure["failure"]["frames"] if frame["function"] == "fail"
            )
            self.assertEqual(
                await self.call_tool(client, "inspect", "left", names=["local"], frame=frame),
                {"values": {"local": 11}, "missing": [], "frame": frame},
            )
            self.assertEqual(
                await self.call_tool(client, "inspect", "right", names=["shared", "fail"]),
                {"values": {"shared": 22}, "missing": ["fail"], "frame": None},
            )

            self.assertEqual(await self.call_tool(client, "reset", "left"), {"status": "ok"})
            self.assertEqual(
                await self.call_tool(client, "inspect", "left", names=["shared"]),
                {"status": "not_found"},
            )
            result = await self.call_tool(
                client, "execute", "left", code="assert 'shared' not in globals()",
            )
            self.assertEqual(result["status"], "ok", result)
            self.assertEqual(
                await self.call_tool(client, "inspect", "right", names=["shared"]),
                {"values": {"shared": 22}, "missing": [], "frame": None},
            )
            for label in ("left", "right"):
                self.assertEqual(await self.call_tool(client, "reset", label), {"status": "ok"})

    async def test_same_session_is_busy_while_execute_is_running(self):
        with TemporaryDirectory() as directory:
            ready = Path(directory) / "ready"
            release = Path(directory) / "release"
            async with self.client() as client:
                for label in ("active", "independent"):
                    warmed = await self.call_tool(client, "execute", label, code="answer = 41")
                    self.assertEqual(warmed["status"], "ok", warmed)
                # The kernel signals from inside execute, then waits for the test to release it.
                running = asyncio.create_task(
                    self.call_tool(
                        client, "execute", "active",
                        code=(
                            "from pathlib import Path\n"
                            "from time import sleep\n"
                            f"Path({str(ready)!r}).touch()\n"
                            f"while not Path({str(release)!r}).exists():\n"
                            "    sleep(0.01)\n"
                            "answer += 1"
                        ),
                    ),
                )
                try:
                    async with asyncio.timeout(5):
                        while not ready.exists():
                            await asyncio.sleep(0.01)
                    self.assertEqual(
                        await self.call_tool(client, "execute", "active", code="answer = 0"),
                        {"status": "busy"},
                    )
                    self.assertEqual(
                        await self.call_tool(client, "inspect", "active", names=["answer"]),
                        {"status": "busy"},
                    )
                    self.assertEqual(
                        await self.call_tool(client, "reset", "active"), {"status": "busy"},
                    )
                    independent = await self.call_tool(
                        client, "execute", "independent", code="print(answer + 2)",
                    )
                    self.assertEqual(independent["status"], "ok", independent)
                    self.assertEqual(independent["output"], "43\n")
                    self.assertFalse(running.done(), "active finished before release")
                finally:
                    release.touch()
                    completed = await running

                self.assertEqual(completed["status"], "ok", completed)
                self.assertEqual(
                    await self.call_tool(client, "inspect", "active", names=["answer"]),
                    {"values": {"answer": 42}, "missing": [], "frame": None},
                )
                for label in ("active", "independent"):
                    self.assertEqual(await self.call_tool(client, "reset", label), {"status": "ok"})
