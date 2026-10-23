# Home Assistant toolkit verification

The results below are historical records for earlier revisions. The v0.1.1
release candidate connects only to Toolforest Production; earlier environment
references do not describe its setup options. Its new verification results are
recorded separately in `docs/PRODUCTION_ONLY_RELEASE.md`.

Verification records for the corrected Home Assistant scope of
[toolforest_tools#2197](https://github.com/Toolforest-io/toolforest_tools/issues/2197#issuecomment-6163254252).
The Home Assistant toolkit does not automatically expose an existing Apple Home configuration.

## Reviewed fixes and latest local/dev verification

On 2026-10-17 Pacific (2026-10-18 UTC), installed reviewed integration commit
`0409abc5d0c9ae6e132e8bda11a440142c97f356` from
[PR #9](https://github.com/Toolforest-io/toolforest-home-assistant/pull/9) into the
existing local Home Assistant **2026.10.1** container. PR #9 was still unmerged;
this documentation update depends on it. No backend deployment or frontend
publication was performed for this check.

The package SHA-256 was
`09b00e70294d57302de613b5971eec0c837ff31db3763bdc7c68976ca6f8c710`.
All **11 installed files** matched the reviewed archive. The existing pairing,
configuration-entry identity, and entity/action permissions were unchanged.
The pre-update integration code was backed up locally before the container restart.

### Automated coverage for PR #9

- **78 tests passed** locally using Python **3.14.7**, followed by Ruff and
  `python scripts/package.py`. The same reviewed head's
  [CI test job passed](https://github.com/Toolforest-io/toolforest-home-assistant/actions/runs/39082343963);
  its release job was skipped, and no release was published.
- `pytest-homeassistant-custom-component==0.13.372` pins Home Assistant
  **2026.10.1** and its compatible pytest dependencies. It requires Python
  **3.14.2+**. The integration is imported normally, with no fake-package shim
  bypassing HA setup, configuration flows or sensors.
- Native HA tests cover pairing pending/expiry/denial/network errors, exposure
  validation, options reload, reauth after a transient connection error,
  reauth from a revoked frame or HTTP 401 handshake, setup-failure cleanup,
  unload ordering, shutdown, socket reconnect, removal, and diagnostic sensor
  state/attributes.
- Abandoned-pairing tests cover abort before token issuance, after issuance,
  while the token request is in flight, and on a duplicate-entry abort. Successful
  entry creation retains its credential. Revocation failures are bounded and
  logged without the token; cleanup remains best-effort while offline.
- Executor regressions cover brightness **1–255**, denial of zero without native
  service dispatch, strict argument validation, and gateway-shaped deadlines with
  up to five seconds of HA clock lag. They also cover local expiry, relative
  execution timeout, uncertain outcomes, duplicate IDs, and a full duplicate cache.
  HA's actual light service implementation is exercised with a virtual light.
- The loaded-entry reauth regression checks that exactly one replacement socket
  connects: the existing update listener performs the reload rather than racing
  a second explicit reload. Reauth preserves the stored environment/name/options
  and updates the entry's unique ID to the new device identity.
- Time-scaled loopback tests cover idle connections beyond the receive timeout.
  Both application and WebSocket pings run under the owned heartbeat task. HA's
  lingering-task/timer cleanup checks stay enabled, including revocation tests.

These automated tests use synthetic credentials and loopback gateways. They are
separate from the actual dev gateway/MCP observations below.

### Five-minute idle check against the actual dev gateway

Left instance `Gw2PSOAyy-g` idle for **300.06 seconds**, from
**2026-10-18 03:49:38.116 to 03:54:38.170 UTC**, without MCP requests or application
messages sent to HA. Read only its dev connection metadata every 30 seconds:

- All **11 samples** retained connection ID `gd4q7k9F2eO4KEiYeA==`.
- Every sample's connection TTL remained live. The application-heartbeat expiry
  advanced from `1792295481` to `1792295779` (298 seconds).
- Home Assistant's native diagnostic sensor showed **connected**, environment dev.
- The same connection persisted after the subsequent MCP smoke test.

The gateway does not reply to application pings. The reviewed transport sends
application pings every 60 seconds for the gateway TTL and WebSocket pings every
30 seconds for pongs, with a 90-second receive timeout. It does not use aiohttp's
`heartbeat=` timer, which can linger after close on the pinned aiohttp 3.14.4
runtime. Surviving more
than three receive-timeout intervals without MCP traffic verifies the keepalive
operationally against API Gateway; no separate packet capture is claimed.

### Real MCP and native UI smoke after the idle check

Used the existing Toolforest router at `https://mcp.dev.toolforest.io/mcp`, after
discovering tool names and their input schemas. All **nine MCP calls passed**:

1. `list_instances` returned the single connected instance `Gw2PSOAyy-g`.
2. `list_entities` returned exactly `light.bed_light` and
   `switch.decorative_lights`, each allowing on/off, with brightness not allowed.
3. `get_entity_state` read both initial states: light off, switch on (two calls).
4. `control_entity` turned the light on and switch off, then restored light off
   and switch on (four calls). Chrome's native HA state table confirmed all four
   resulting states independently of the MCP response.
5. Final `list_entities` confirmed only the same two entities and restored states.

This smoke did not repeat pairing, revocation, isolation, permission changes or
timeout injection on the new build. Brightness permission remained disabled;
the new zero-brightness and clock-lag regressions are covered by the automated
tests, not claimed as additional live scenarios. No physical device was tested.

Maintainer evidence is retained outside Git in the workspace `.task-state/`:
`ha-pr9-idle-check.json`, `ha-pr9-real-mcp-results.json`, `ha-pr9-install.json`,
and native Chrome state screenshots. No credentials or private HA configuration
are included in this repository.

## Original MVP verification before PR #9

The following checks were performed on 2026-10-17 against the earlier integration
build. They are historical evidence, not a claim that every scenario was rerun
after the review fixes.

### Components and environment

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

### Automated checks on the earlier build

- Standalone tests: **26 passed**, including isolated executor exposure,
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

### Real Home Assistant, gateway and MCP checks on the earlier build

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
observed during those manual lifecycle checks. They did not provide automated
coverage of HA configuration/lifecycle modules; the later native harness added
that coverage and exposed the reauth reload race and heartbeat timer cleanup issue.

## Reproduce and resume

Use README's hardware-free Docker/Colima setup, UI pairing steps and separate
backend test commands. Use the portal's `docs/HOME_ASSISTANT_LOCAL.md` for Node
versions, shared-sandbox checks, local Vite/Astro servers and the docs-origin override.
Use an authorized dev MCP client to discover schemas before calling tools.
Keep local Home Assistant configuration and credentials outside Git.

## Remaining limitations

The backend change raising minimum brightness to 1, its tests, and its README
have been prepared locally but are not deployed. The live dev schema still
advertises a minimum of 0; the reviewed integration independently rejects zero.
The five-minute idle and nine-call smoke above used that existing backend and did
not test brightness. Those results do not validate the undeployed backend change.

Duplicate history belongs to one executor and resets on config-entry reload;
transport reconnect alone preserves it. This behavior is unchanged. The gateway
uses fresh correlation IDs rather than replaying uncertain writes. Reauth retains
exposure options and binds to the Toolforest account that approves the new code;
no account-ID protocol expansion is included in these fixes.

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
