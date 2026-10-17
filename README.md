# Home Assistant toolkit

The Home Assistant toolkit connects devices **already managed by Home Assistant**
to Toolforest. It **does not automatically expose an existing Apple Home
configuration**. Direct Apple Home/HomeKit access, Matter controller functionality,
cameras, climate controls, scenes, scripts, and event history are follow-ons.

The custom integration runs inside Home Assistant at
`custom_components/toolforest/`. It opens authenticated outbound WSS to the
existing Toolforest bridge gateway. No Anki installation, AnkiConnect, separate
bridge daemon, inbound Internet endpoint, port forwarding, or HA API token is
required. The Docker container below runs Home Assistant itself, not a daemon.

## Repository and distribution

This repository owns the installable Home Assistant integration, its executor and
transport tests, HACS metadata, and release archive. The Toolforest toolkit Lambda
and shared bridge gateway remain in `Toolforest-io/toolforest_tools`; the portal
remains in `Toolforest-io/curly-octo-computing-machine`. The integration is not a
Home Assistant Supervisor add-on and does not run a separate service.

The repository follows the [HACS integration layout](https://www.hacs.dev/docs/publish/integration/).
It has not been submitted to the HACS default catalog, and no release has been
published yet. During development, install the reviewed `main` branch manually.
After a release is published, users can add
`https://github.com/Toolforest-io/toolforest-home-assistant` as a **custom
repository** of type **Integration** in HACS, then download **Home Assistant
toolkit** and restart Home Assistant. HACS installation has not yet been verified.

## Install and pair

1. Copy this repository's `custom_components/toolforest` directory into your HA
   config directory's `custom_components/` directory. For a release archive,
   extract `toolforest.zip` into `custom_components/toolforest/` (the archive
   contains the integration's files directly). Restart Home Assistant.
2. In **Settings → Devices & services → Add integration**, find
   **Home Assistant toolkit**.
3. Enter an instance name and select the Toolforest environment. Normal users
   select the environment matching their Toolforest account. The toolkit is
   currently enabled only for development verification, so use `dev` there;
   its test and production catalog entries remain disabled.
4. Open the displayed Toolforest activation URL, sign in to the matching
   environment, and approve the displayed device code. Return to the HA setup
   dialog and submit. Codes expire after ten minutes; pending polls are throttled.
5. Select individual light/switch entities for reads. Nothing is selected by
   default. Separately select entities allowed to **turn on**, **turn off**, and
   change **light brightness**. Every action target must also be selected for reads.
6. Finish setup. The diagnostic **Home Assistant toolkit connection** sensor
   reports connecting, connected, reconnecting, revoked or displaced status.

Change exposure later with **Configure** in the integration's entry menu.
Options changes reload the integration. Disable/re-enable or reload the entry to
stop/start its owned WSS/tasks without changing pairing. Revoked credentials
start a reauthentication flow. Removing the integration attempts remote device
revocation; if the network is unavailable, revoke the device in Toolforest too.

The portal update accompanying the connection guide keeps the toolkit row compact:
**Show me how to connect** opens the guide, and **⋮ → Manage connections** lists
paired instances with their status and individual disconnect actions. With multiple
instances, the row's Disconnect button opens that dialog instead of choosing a target.
Inspecting connections does not change an MCP tool's target: every MCP call
explicitly supplies `instance_id` from `list_instances`.
Entity/action exposure is managed inside Home Assistant, never by a cloud
service dispatcher.

## MCP tools

| Tool | Inputs | Effect |
|---|---|---|
| `list_instances` | none | List this account's paired instances, including offline ones |
| `list_entities` | `instance_id`, optional `offset`, `limit` (1–100) | Sorted page of exposed lights/switches |
| `get_entity_state` | `instance_id`, `entity_id` | Current state, allowed actions, limited brightness fields |
| `control_entity` | `instance_id`, `entity_id`, `action` (`turn_on`/`turn_off`), optional `brightness` (0–255) | One explicitly allowed native HA call |

Brightness requires an exposed light with supported color modes and separate
brightness permission, and is valid only with `turn_on`. No toggle or arbitrary
service names/parameters are accepted. Controls against unknown, hidden,
unavailable, or restricted targets fail closed. Responses omit raw HA attributes and friendly names.
The control response is the state observed after the native service call, not
proof that physical hardware reached that state. A selected HA group may itself
control multiple devices; select individual entities when that is undesirable.

## Isolation and failure behavior

- The authenticated MCP account supplies ownership; tool arguments cannot select
  another user. Pairing binds a revocable credential to the HA capability.
- Each paired instance gets an independent connection slot, addressed by its
  gateway-issued device ID. An Anki credential cannot claim an HA connection.
- Pending responses are bound to both account and exact receiving connection.
- Requests carry correlation IDs and an absolute deadline, bounded by the
  existing bridge protocol's 15-second ceiling. HA rejects expired/duplicate
  requests, limits concurrent execution to one, and rechecks current exposure,
  action permission, state and capabilities at execution time.
- Controls are never automatically retried or replayed across reconnects. After
  timeout/disconnect, execution may be uncertain: read state before deciding
  whether to repeat an action. HA automations can give repeated calls side effects.
- Transport tasks use async I/O, heartbeat and capped reconnect backoff. Unload,
  shutdown, revocation and disconnect cancel owned pending work; cancellation
  cannot undo a native action already accepted by Home Assistant.
- Revocation is rechecked against the authoritative device record before cloud
  dispatch. HA sessions expire after missed application heartbeats (120 seconds);
  the normal disconnect handler removes them sooner.
- Only fixed Toolforest environment endpoints are configurable. No arbitrary
  network proxy, lock/alarm/garage/camera domain, or unrestricted HA service
  dispatcher is exposed. Authorized actions are logged by entity ID/action;
  credentials and raw state payloads are not logged.

## Hardware-free local development (Mac)

Tested target: Home Assistant **2026.10.1**, official container digest
`sha256:130241f28d01fa80dfa3b44f7d89781c188d8642ecab9024f079f19f9f82baa0`.

From a workspace containing a `toolforest-home-assistant` checkout:

```bash
colima start --cpu 4 --memory 6 --disk 30
mkdir -p .task-state/home-assistant-config
printf 'default_config:\ndemo:\n' > .task-state/home-assistant-config/configuration.yaml
docker --context colima run -d --name toolforest-home-assistant-dev \
  --restart unless-stopped -p 127.0.0.1:8123:8123 \
  -e TZ=America/Los_Angeles \
  -v "$PWD/.task-state/home-assistant-config:/config" \
  -v "$PWD/toolforest-home-assistant/custom_components:/config/custom_components:ro" \
  ghcr.io/home-assistant/home-assistant@sha256:130241f28d01fa80dfa3b44f7d89781c188d8642ecab9024f079f19f9f82baa0
```

Open `http://127.0.0.1:8123`, create a local test account, then install/configure
the integration through the UI above. `demo:` creates virtual devices; legacy
`light: - platform: demo` configuration is no longer supported in this version.
Expose only a virtual light and switch and allow their on/off actions. Do not
enable physical integrations for this test.

For an existing container, resume with `docker --context colima start
toolforest-home-assistant-dev`; after source changes restart that container.
Inspect logs with `docker --context colima logs --tail 100
toolforest-home-assistant-dev`. Configuration persists in `.task-state`, outside
the repository. Keep its credentials private. Stop this container with `docker
--context colima stop toolforest-home-assistant-dev`; avoid stopping other services.

### Dev compatibility

For a coordinated dev test, the integration, portal account and toolkit must all
use the dev environment. Dev endpoints are `wss://bridge-dev.toolforest.io`,
`https://bridge-api-dev.toolforest.io`, and `https://mcp.dev.toolforest.io/mcp`.
Toolkit, gateway and portal deployments are managed separately; installing this
integration does not deploy those services. Maintainers should follow the backend
and portal repositories' deployment instructions.

## Verification

Run inside this repository:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-test.txt
.venv/bin/python -m pytest -q
.venv/bin/ruff check custom_components tests scripts
.venv/bin/python scripts/package.py
```

`dist/toolforest.zip` contains only the integration and its license. CI runs the
same tests, lint and packaging checks on pull requests and `main`. A `v*` tag also
checks that the manifest version matches the tag and prepares a **draft** GitHub
release. Publish a release only after the corresponding real UI/device-flow and
MCP verification is recorded; creating the feature branch does not release it.

Run the separate backend checks from `toolforest_tools`:

```bash
PYTHONPATH=.:packages/bridge-client/src:packages/mcp-lambda-runtime/src \
  .venv/bin/python -m pytest toolsets/home_assistant/tests \
  services/bridge_gateway/tests \
  packages/mcp-lambda-runtime/tests/test_worker_enumeration.py -q
```

The async transport contract tests open an ephemeral localhost WebSocket server.
They need local socket permission. They supplement real tests; they do not
substitute for pairing, real dev gateway/MCP calls, HA state confirmation,
portal status/selection/errors, revocation and unload/reload in a browser.

See `VERIFICATION.md` for the recorded execution results and remaining gates.
