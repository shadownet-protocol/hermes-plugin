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

- **First start is slow** (~10–30s pip install). One-time per install.
- **Requires pip in Hermes' venv.** True for nearly all installs. If
  `HERMES_DISABLE_LAZY_INSTALLS=1` is set, the shim refuses and prints
  the manual `pip install` command instead.
- **Two artifacts to release.** Shim version (`plugin.yaml`) tracks shim
  changes only; the adapter ships independently on PyPI.

## Version policy

The shim pins the PyPI package with a compatible-release specifier
(`~=0.1.1`): patches in the 0.1.x line flow transparently to users on
their next gateway restart, but a 0.2.x release requires bumping the pin
in this repo and cutting a new shim release.

## License

MIT.
