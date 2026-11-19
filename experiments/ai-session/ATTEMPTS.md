# Prototype build attempts

| Attempt | Command | Result |
| --- | --- | --- |
| Prepare an isolated editable install | `python3.11 -m venv .venv && .venv/bin/python -m pip install -e .` | The build backend reported that `src` did not exist yet. Retry after adding the package entry point. |
| Install after adding the source tree | `.venv/bin/python -m pip install -e '.[mcp]'`; `.venv/bin/python -m pip check` | Installed the package, IPython kernel and optional MCP SDK. No broken requirements reported. |
| Default kernel transport | `.venv/bin/python -m unittest discover -s tests -p test_session.py -v` | The first integration run worked, and ipykernel reported plaintext TCP. Require CurveZMQ and bind to loopback; the subsequent run passed without the warning. |
