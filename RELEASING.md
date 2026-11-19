# Release checklist

1. Check the `shellless-ops` name on PyPI again. An absent project page does not reserve the name.
2. Confirm the CI matrix is green for the exact commit to release. Check both artifacts with `python -m build` and `python -m twine check --strict dist/*` in a development environment.
3. After release approval, add a GitHub Actions publish workflow with a protected `pypi` environment and `id-token: write` scoped to the publish job. On PyPI, set up a [pending Trusted Publisher](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/) for `zhangs-cedar/shellless-ops`, using that workflow's exact filename and environment. Do not store a long-lived PyPI token.
4. Publish the reviewed artifacts only after the publish job's environment approval. Verify the version on PyPI and install it into a clean environment before updating the README's installation instructions.
