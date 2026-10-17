# Home Assistant toolkit verification

Verified on 2026-10-17 against the corrected Home Assistant scope of
[toolforest_tools#2197](https://github.com/Toolforest-io/toolforest_tools/issues/2197#issuecomment-6163254252).
The Home Assistant toolkit does not automatically expose an existing Apple Home configuration.

## Components and environment

- Native integration: `main` merge `9f063c0`, with environment-label fix from
  [PR #2](https://github.com/Toolforest-io/toolforest-home-assistant/pull/2).
- Built ZIP installed in local Home Assistant **2026.10.1**, using the official
  image and pinned digest documented in README. Installed files matched the
  10-file archive; SHA-256
  `136978bb0e90f4d18e34da6d3159bd869125c2f515c0eb5969aa562017c2220e`.
- Actual Toolforest **dev** gateway and toolkit Lambda, through the existing
  Toolforest router MCP client. No mocked MCP server or gateway substituted.
- Portal ran locally in Vite against the existing shared Amplify sandbox.
  Chrome was used for portal and Home Assistant UI checks.
- Only virtual `light.bed_light` and `switch.decorative_lights` were exposed.
  No physical devices were tested. No test/production promotion was performed.

## Automated checks

- Standalone integration tests: **26 passed**, including native executor exposure,
  argument/deadline/deduplication checks, actual local async WebSocket contracts,
  revocation/cancellation, concurrent-request rejection and package validation.
- Ruff passed for `custom_components`, `tests` and `scripts`.
- [GitHub CI passed](https://github.com/Toolforest-io/toolforest-home-assistant/actions/runs/38881332356),
  including all 26 tests, lint and the uploaded integration archive.
- `python scripts/package.py --version 0.1.0` built `dist/toolforest.zip`; tests
  confirm it installs without development files and rejects a mismatched version.
- Local Home Assistant **2026.10.1** runs with demo entities and loads the built
  archive's installed files from a read-only `custom_components` mount.
- Separate backend gateway checks: **31 passed** in an isolated dependency environment.
- Separate toolkit and worker-enumeration checks: **21 passed**.
- Portal after the compact-row/help-link update: **502 passed**; TypeScript/Vite
  build passed. The existing integrity plugin needs outbound access during builds.
- Astro connection-guide build passed. The guide and portal link are tracked in
  [landing issue #630](https://github.com/Toolforest-io/toolforest_landing/issues/630).

## Real Home Assistant, gateway and MCP checks

1. Installed/configured the custom integration through Home Assistant's UI.
   Approved its actual dev device flow; selected the two virtual entities and
   separate read/on/off permissions. Discovery returned exactly those targets.
2. Read both states through the real router. Turned the light on/off and switch
   off/on through MCP; confirmed both directions in Home Assistant's entity UI.
   Final state was light off, switch on.
3. An unexposed light returned `NOT_EXPOSED`; brightness without its separate
   permission returned `ACTION_NOT_ALLOWED`; unknown instances were denied.
   Invalid brightness, action, restricted lock domain and forged account arguments
   were rejected by the published schemas.
4. Removed only switch turn-off permission through the options UI. Discovery
   reflected the change and that action was denied. Restored and verified permissions.
5. Disabled the integration through its UI: MCP reported offline and the portal
   showed Paired · Offline. Re-enabled/reloaded it successfully. Graceful
   container stop/start also disconnected/reconnected the same instance.
6. Paused the local container during a light-on request. MCP returned
   `BRIDGE_TIMEOUT` with uncertain execution after about 19 seconds total client
   wall time, including transport overhead beyond the 15-second bridge ceiling.
   After resuming, the light remained off: the expired write was not replayed.
7. Closed only the task-owned gateway connection. The integration reconnected
   with a new connection ID in **2.41 seconds**, without credential changes.
8. Eight live bridge-contract cases passed through the actual gateway/native
   executor: valid read, mismatched instance, expired deadline, arbitrary action,
   response-account mismatch, response-connection mismatch, initial correlation,
   and duplicate correlation. All seven temporary pending rows were deleted.
9. Tested the account boundary with isolated, non-authenticatable foreign-account
   device metadata: the real MCP caller could neither discover nor target it.
   Deleted the fixture afterward. This was not a second signed-in user session.
10. Using a Home Assistant credential with the Anki capability was rejected with
    HTTP 403 without affecting the legitimate connection.
11. Portal Disconnect revoked the selected old instance. MCP immediately denied
    it, its old WebSocket credential returned HTTP 401, and Home Assistant showed
    native reauthentication. Re-pairing created a new instance, retained selected
    exposure, and left the old instance denied.
12. Six concurrent real MCP reads returned the correct alternating entity targets
    and states. Native WebSocket unit tests separately cover BUSY rejection.
13. Portal checks covered connected, paired/offline, disconnected after revocation,
    reconnected after pairing, and browser-offline/status-unavailable states.
    Temporary non-authenticatable offline metadata exercised multiple-instance
    selection and was deleted afterward. Only one real Home Assistant host was used.

No relevant native blocking-call, unclosed-session or pending-task warnings were
observed during lifecycle checks.

## Reproduce and resume

Use README's hardware-free Docker/Colima setup, UI pairing steps and separate
backend test commands. Use the portal's `docs/HOME_ASSISTANT_LOCAL.md` for Node
versions, shared-sandbox checks, local Vite/Astro servers and the docs-origin override.
Use an authorized dev MCP client to discover schemas before calling tools.
Keep local Home Assistant configuration and credentials outside Git.

## Remaining limitations

HACS installation is unverified and no integration release has been published.
Install the reviewed source manually. Test and production catalog entries remain
disabled. The guide and compact portal update need their corresponding PRs;
local frontend tests do not publish either website. The docs' checked-in production
schema snapshot does not yet include a generated Home Assistant tool-reference page.

No physical-device, native Apple Home/HomeKit, Matter-controller, camera, climate,
scene/script or event-history verification is claimed. Live isolation checks used
metadata/pending fixtures rather than two independently signed-in accounts or
two actual Home Assistant hosts.

Unit/local WebSocket results and real dev gateway/MCP results are reported separately above.
