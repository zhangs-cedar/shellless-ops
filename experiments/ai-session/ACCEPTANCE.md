# AI session prototype: acceptance

- Run `python -m unittest discover -s tests -v` against an installed package and real Python kernels.
- A second execution can reuse a variable without rerunning the first. After an error, the caller can fetch a named local from the reported frame without rerunning the code. A later execution or reset invalidates the old failure.
- Point inspection at explicit variable names; do not return an entire namespace, run expressions supplied as names or call a user object's representation to summarize it. Keep returned execution output within `max_output` characters.
- Two sessions start independently and can execute in parallel; one session's timeout or reset does not erase the other's state. A timed-out session starts a clean kernel on its next use.
- Install `.[mcp]` and use the official client on a real stdio subprocess. Verify the three tools return one text JSON response, the active label answers `busy`, and another label can run before the blocked work is released.
- Run a repeatable example comparing an identical three-stage diagnostic with and without state reuse. Report elapsed time, repeated setup executions and response bytes. Do not equate response bytes with model tokens.
- Do not publish, push, add a network service, or change the root package.
