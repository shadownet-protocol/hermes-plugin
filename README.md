# shadownet-protocol/hermes-plugin

One-line install shim for the [Shadownet protocol](https://github.com/shadownet-protocol/shadownet-specs)
on [Hermes Agent](https://hermes-agent.nousresearch.com/).

## Install

Mint your `SHADOWNET_CONNECT_URL` at `<your-sidecar>/connect/hermes-agent`,
then paste:

```sh
echo 'SHADOWNET_CONNECT_URL=shadownet://connect?base=<sidecar>&token=<token>' >> ~/.hermes/.env \
  && hermes plugins install shadownet-protocol/hermes-plugin --enable \
  && hermes gateway restart
```

One paste — no `pip` command, no interactive prompts, no manual `mcp_servers`
YAML edit.

## What this repo is

A 60-line install shim. The real adapter — the platform plugin that opens
an MCP session to your Shadownet sidecar and long-polls for inbound
agent-to-agent messages — lives at:

- **Source:** [shadownet-protocol/shadownet/integrations/plugins/hermes-agent](https://github.com/shadownet-protocol/shadownet/tree/main/integrations/plugins/hermes-agent)
- **PyPI:** [`shadownet-hermes-plugin`](https://pypi.org/project/shadownet-hermes-plugin/)

This repo exists because Hermes' `hermes plugins install owner/repo`
flow requires `plugin.yaml` + `__init__.py` at the cloned repo root and
does not run pip on the cloned tree. The shim's `register(ctx)`
bootstraps the PyPI package into Hermes' active venv on first call, then
delegates to the real `register()`. Same algorithm Hermes' bundled
`tools/lazy_deps.ensure()` uses for its own backends — open-coded here
because the upstream allowlist is closed to third parties.

## Tradeoffs

- **First start is slow** (~10–30s install). One-time per install.
- **Requires `uv` or `pip` in the Hermes container.** The shim tries
  `uv pip install` first (matches the NousResearch image, whose venv is
  built by `uv venv` and omits pip), then falls back to `python -m pip
  install`. If `HERMES_DISABLE_LAZY_INSTALLS=1` is set, the shim refuses
  and prints both manual install commands instead.
- **Bypasses `exclude-newer` only if needed.** See
  [the section below](#exclude-newer).
- **Two artifacts to release.** Shim version (`plugin.yaml`) tracks shim
  changes only; the adapter ships independently on PyPI.

## exclude-newer

The NousResearch `hermes-agent` image sets uv's
[`exclude-newer`](https://docs.astral.sh/uv/reference/settings/#exclude-newer)
in `/opt/hermes/pyproject.toml` to its image build date. uv reads that
when invoked from `/opt/hermes` (where the gateway runs), and treats it
as "pretend PyPI has no releases newer than this date." It's a legitimate
reproducibility / supply-chain defense for Hermes' own deps.

The side-effect: any plugin released after the image was built — like
ours, every time we ship a new version — is invisible to uv inside the
container. The shim's `uv pip install` will fail with `No solution
found … only <old-version> is available`.

When the shim detects that failure pattern, it logs a `WARNING` line
naming the bypass and retries the install with
`--exclude-newer 2999-12-31` (effectively disabling the lock
for this one package). Install succeeds; operators see the deviation
in the logs.

If you'd rather not have the shim deviate from `exclude-newer` at all,
the recommended pattern is to **bake the adapter into a custom Hermes
image at your chosen version** so it's installed at *your* build time
(under your own reproducibility constraints) and the shim's runtime
install short-circuits via `_is_satisfied()`:

```dockerfile
FROM nousresearch/hermes-agent:latest
USER hermes
RUN uv pip install \
      --python /opt/hermes/.venv/bin/python3 \
      --exclude-newer 2999-12-31 \
      'shadownet-hermes-plugin~=0.2.0'
```

(The `--exclude-newer` override is needed at build time too — same
reason, same fix.)

## Version policy

The shim pins the PyPI package with a compatible-release specifier
(`~=0.2.4`): patches in the 0.2.x line ≥ 0.2.4 flow transparently to
users on their next gateway restart, but a 0.3.x release requires
bumping the pin in this repo and cutting a new shim release. The floor
has been raised twice — first to 0.2.3 (split-host MCP URL bug in
0.2.0–0.2.2) and then to 0.2.4 (0.2.3 registered skills via
`ctx.register_skill` but did not materialize the SKILL.md files into
`~/.hermes/skills/`, so the agent's skill-loader did not surface them).
The shim forces a re-install on existing installs that still have a
buggy version in the venv.

## License

MIT.
