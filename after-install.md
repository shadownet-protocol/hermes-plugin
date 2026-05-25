# Shadownet plugin installed

Restart the Hermes gateway so the adapter loads:

```sh
hermes gateway restart
```

**First start is slow** — this shim runs `pip install shadownet-hermes-plugin`
into Hermes' venv on first `register()` (~10-30s). Subsequent starts are
instant.

If you haven't already set `SHADOWNET_CONNECT_URL` in `~/.hermes/.env`,
mint one at `<your-sidecar>/connect/hermes-agent` and paste it into your
`.env` before restarting.
