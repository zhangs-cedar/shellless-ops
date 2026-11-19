# Release checklist

1. Check the `shellless-ops` name on PyPI again. An absent project page does not reserve the name.
2. Confirm the CI matrix is green for the exact commit to release. Check both artifacts with `python -m build` and `python -m twine check --strict dist/*` in a development environment.
3. On PyPI, set up a [pending Trusted Publisher](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/) with project `shellless-ops`, owner `zhangs-cedar`, repository `shellless-ops`, workflow `publish.yml`, and environment `pypi`. No long-lived API token is needed.
4. From [Publish to PyPI](https://github.com/zhangs-cedar/shellless-ops/actions/workflows/publish.yml), dispatch the `main` workflow with `publish` unchecked to build and validate only. Once release is approved and the Trusted Publisher is configured, dispatch it with `publish` checked; the publish job can upload only if that run's build passed.
5. Verify the expected version on PyPI and install it into a clean environment before updating the README's installation instructions.
