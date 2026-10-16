# Home Assistant toolkit verification

The integration is in development for the corrected Home Assistant scope of
[toolforest_tools#2197](https://github.com/Toolforest-io/toolforest_tools/issues/2197).
It does not automatically expose an existing Apple Home configuration.

## Checks after the repository split (2026-10-16)

- Standalone integration tests: **26 passed**, including native executor exposure,
  argument/deadline/deduplication checks, actual local async WebSocket contracts,
  revocation/cancellation, concurrent-request rejection and package validation.
- Ruff passed for `custom_components`, `tests` and `scripts`.
- [GitHub CI passed](https://github.com/Toolforest-io/toolforest-home-assistant/actions/runs/38876688299),
  including all 26 tests, lint and the uploaded integration archive.
- `python scripts/package.py --version 0.1.0` built `dist/toolforest.zip`; tests
  confirm it installs without development files and rejects a mismatched version.
- Local Home Assistant **2026.10.1** runs with demo entities and loads the manifest
  from this repository's read-only `custom_components` mount.
- Separate backend gateway checks: **31 passed** in an isolated dependency environment.
- Separate toolkit and worker-enumeration checks: **21 passed**.

## Remaining acceptance gates

Local Home Assistant account onboarding, configuration through its integrations
UI, real device pairing, real dev gateway/MCP discovery and light/switch on/off
state confirmation, live denied/isolation/timeout/reconnect/revocation cases,
clean unload/reload and the portal's status/selection/error states remain pending.
HACS installation has not been verified. No integration release has been published.

Unit and local WebSocket tests do not satisfy the pending real end-to-end gates.
