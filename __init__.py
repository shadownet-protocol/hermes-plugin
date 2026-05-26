"""Hermes Agent install shim for the Shadownet protocol.

Hermes' ``hermes plugins install owner/repo`` clones the repo and looks
for ``plugin.yaml`` + ``__init__.py`` at the clone root, but does NOT run
pip on the cloned tree. The real adapter ships on PyPI as
``shadownet-hermes-plugin`` (transitive deps: ``mcp``, ``shadownet``).

``register(ctx)`` ensures the PyPI package is importable at the version
this shim pins, then delegates. If the package is missing or stale, we
install it into Hermes' active venv — preferring ``uv pip install`` over
``python -m pip install`` because Hermes' default image ships a venv
built by ``uv venv``, which omits pip. If the install is rejected by
Hermes' ``exclude-newer`` reproducibility lock (the image pins it to its
build date), the shim warns loudly and retries once with the lock
bypassed for this package only. Same algorithm Hermes' bundled
``tools/lazy_deps.py:ensure()`` uses, open-coded here because the
upstream allowlist is closed to third parties.

Source of truth for the adapter:
https://github.com/shadownet-protocol/shadownet/tree/main/integrations/plugins/hermes-agent
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from typing import Any

__all__ = ["register"]

_log = logging.getLogger(__name__)

_PACKAGE_NAME = "shadownet-hermes-plugin"
# Compatible-release: accept 0.2.x patches ≥ 0.2.3 transparently, require
# a shim re-release for 0.3.x so a breaking adapter change can't propagate
# to existing installs without an explicit bump here. Floor raised from
# 0.2.0 to 0.2.3 because 0.2.0–0.2.2 had a split-host MCP URL bug: the
# adapter synthesized `{base}/u/{shadowname}/mcp` from the connect URL's
# `base=` instead of using the bundle's `mcp_endpoint` field. Sidecars
# that serve MCP from a different host than the dashboard (e.g.,
# `api.example.org` for MCP vs `app.example.org` for the bundle endpoint)
# would 405 on the wrong host.
_VERSION_SPECIFIER = "~=0.2.3"
_PACKAGE_SPEC = f"{_PACKAGE_NAME}{_VERSION_SPECIFIER}"
_PIP_TIMEOUT_SECONDS = 300


class _ShimError(RuntimeError):
    """The shim could not bootstrap the real plugin package."""


def _is_satisfied() -> bool:
    """Is ``_PACKAGE_SPEC`` already satisfied in the active venv?

    Checks presence AND version-compatibility so a stale install from a
    previous pin (e.g. legacy 0.1.0 from the manual pip-install era) is
    upgraded instead of silently kept.
    """
    try:
        from importlib.metadata import PackageNotFoundError, version
    except ImportError:
        return False
    try:
        installed = version(_PACKAGE_NAME)
    except PackageNotFoundError:
        return False
    try:
        from packaging.specifiers import SpecifierSet
        from packaging.version import Version
    except ImportError:
        # `packaging` ships with pip; if it's gone, treat presence as enough
        # rather than thrash the install on every register().
        return True
    try:
        return Version(installed) in SpecifierSet(_VERSION_SPECIFIER)
    except Exception:
        return True


def _install_attempts() -> list[list[str]]:
    """Ordered install commands to try, most-likely-to-succeed first."""
    import importlib.util
    import shutil

    attempts: list[list[str]] = []
    uv_bin = shutil.which("uv")
    if uv_bin:
        # uv-created venvs omit pip by default (the NousResearch hermes-agent
        # image's default); `uv pip` works against any venv regardless.
        attempts.append(
            [uv_bin, "pip", "install", "--python", sys.executable, _PACKAGE_SPEC]
        )
    if importlib.util.find_spec("pip") is not None:
        attempts.append([sys.executable, "-m", "pip", "install", _PACKAGE_SPEC])
    return attempts


def _looks_like_exclude_newer_block(stderr: str) -> bool:
    """Best-effort: did uv's resolver reject our package due to an
    ``exclude-newer`` reproducibility lock?

    The NousResearch hermes-agent image sets ``exclude-newer`` in
    ``/opt/hermes/pyproject.toml`` to its image build date; any plugin
    published after that date is invisible to the resolver. uv's error
    doesn't always name the setting, so we also match the canonical
    "only X.Y.Z is available and you require ..." resolver message.
    """
    s = stderr.lower()
    return "exclude-newer" in s or (
        "no solution found" in s and "is available and you require" in s
    )


def _run_install(cmd: list[str]) -> tuple[int, str]:
    """Run one install command. Returns (returncode, captured tail)."""
    _log.info("shadownet shim: %s", " ".join(cmd))
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_PIP_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as e:
        raise _ShimError(
            f"install timed out after {_PIP_TIMEOUT_SECONDS}s. "
            f"Retry manually: {' '.join(cmd)}"
        ) from e
    return result.returncode, (result.stderr or result.stdout or "").strip()[-1500:]


def _clear_metadata_cache() -> None:
    # importlib.metadata caches per-process; clear so the post-install
    # _is_satisfied() check sees the fresh install.
    try:
        import importlib.metadata as _md

        if hasattr(_md, "_cache_clear"):
            _md._cache_clear()  # type: ignore[attr-defined]
    except Exception:
        pass


def _pip_install() -> None:
    """Install ``_PACKAGE_SPEC`` into Hermes' active venv.

    Tries ``uv pip install`` (when ``uv`` is on PATH) before ``python -m pip
    install`` so the shim works on both uv- and pip-managed venvs.

    If every attempt fails AND the failure looks like Hermes' ``exclude-newer``
    reproducibility lock blocking the requested version range, the shim logs
    a WARNING and retries once with ``--exclude-newer 2999-12-31``
    to bypass the lock for this package only. The bypass is loud-on-purpose:
    operators who care about supply-chain hygiene should see in the logs that
    we deviated from the image's reproducibility setting and respond by baking
    the plugin into a custom image at their chosen version.

    Honors ``HERMES_DISABLE_LAZY_INSTALLS=1`` (Hermes' documented opt-out
    for runtime installs) — if the user explicitly disabled lazy installs,
    we refuse rather than bypass their choice.
    """
    if os.environ.get("HERMES_DISABLE_LAZY_INSTALLS") == "1":
        raise _ShimError(
            "Lazy installs disabled (HERMES_DISABLE_LAZY_INSTALLS=1). "
            "Install manually with whichever matches your Hermes venv:\n"
            f"  uv pip install --python {sys.executable} {_PACKAGE_SPEC}\n"
            f"  {sys.executable} -m pip install {_PACKAGE_SPEC}"
        )

    attempts = _install_attempts()
    if not attempts:
        raise _ShimError(
            "No installer available: neither `uv` (on PATH) nor `pip` "
            f"(importable by {sys.executable}) was found in this Hermes venv. "
            f"Install manually: <pip-or-uv> install {_PACKAGE_SPEC}"
        )

    last_error: str | None = None
    last_cmd: list[str] | None = None
    saw_exclude_newer_block = False

    for cmd in attempts:
        rc, err = _run_install(cmd)
        if rc == 0:
            _clear_metadata_cache()
            return
        last_error = err
        last_cmd = cmd
        if _looks_like_exclude_newer_block(err):
            saw_exclude_newer_block = True

    import shutil

    uv_bin = shutil.which("uv")
    if saw_exclude_newer_block and uv_bin:
        _log.warning(
            "shadownet shim: install of `%s` appears blocked by Hermes' uv "
            "`exclude-newer` reproducibility lock (set by the image to its "
            "build date in /opt/hermes/pyproject.toml). Retrying once with "
            "`--exclude-newer 2999-12-31` to bypass the lock for "
            "this package only. To avoid this deviation on every restart, "
            "bake the plugin into a custom Hermes image at your chosen "
            "version (see "
            "https://github.com/shadownet-protocol/hermes-plugin#exclude-newer).",
            _PACKAGE_SPEC,
        )
        cmd = [
            uv_bin,
            "pip",
            "install",
            "--python",
            sys.executable,
            "--exclude-newer",
            "2999-12-31",
            _PACKAGE_SPEC,
        ]
        rc, err = _run_install(cmd)
        if rc == 0:
            _clear_metadata_cache()
            return
        last_error = err
        last_cmd = cmd

    tried = "\n".join(f"  {' '.join(cmd)}" for cmd in attempts)
    if saw_exclude_newer_block and uv_bin:
        tried += "\n  (plus exclude-newer-bypass retry)"
    raise _ShimError(
        f"install failed (last exit nonzero from `{' '.join(last_cmd or [])}`):\n"
        f"{last_error}\n"
        f"Tried in order:\n{tried}"
    )


def register(ctx: Any) -> None:
    """Hermes plugin entry point.

    Ensures ``shadownet-hermes-plugin`` is installed at a compatible
    version, then delegates to its ``register()``.
    """
    if not _is_satisfied():
        _pip_install()
        if not _is_satisfied():
            raise _ShimError(
                f"pip install reported success but {_PACKAGE_NAME} is still "
                "not importable — try restarting Hermes."
            )

    from shadownet_hermes_plugin import register as _real_register

    _real_register(ctx)
