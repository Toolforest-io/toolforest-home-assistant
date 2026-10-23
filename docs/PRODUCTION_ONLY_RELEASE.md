# Home Assistant toolkit: production-only release candidate

Prepared on 2026-10-22 for v0.1.1. This candidate is not yet published.
The public v0.1.0 release and existing installations have not been modified.

## Changes

- New setup asks only for the instance name and pairs with Toolforest Production.
- The integration archive contains no alternative service endpoints or labels.
- Existing Production entries keep their credentials, identity and exposure options.
- Unsupported entries stop before network access. Reauthentication also refuses
  them. Removing such an entry does not send its credential to Production; the
  owner must revoke its original remote device in the account where it was paired.
- The internal `environment: prod` field and unique-ID prefix are retained for
  compatibility with existing Production config entries.
- Owned application and WebSocket ping loops and duplicate-history semantics
  are unchanged.

## Local verification

Python 3.14.7 with the existing pinned native Home Assistant test dependencies:

```sh
python -m pytest -q --tb=short
ruff check custom_components tests scripts
python scripts/package.py --version 0.1.1
git diff --check
```

- **90 tests passed**, including the native configuration manager, Production
  pairing, reauthentication, lifecycle/reload, revocation and idle WebSocket tests.
- Additional cases reject unsupported/missing stored service metadata during
  setup and reauthentication without making HTTP or WebSocket connections.
- Native HA rejects forged environment input before making any pairing request.
- Ruff and diff whitespace checks passed.
- Packaging also succeeded on Python 3.12, matching the release job.
- Archive SHA-256: `a364dcfd7fde2f4128d96f0291c7a373fe2a854ab5c30cb60f5ac108ec270f8f`.
- The archive was scanned for alternative service endpoints and setup labels;
  none are present. Translations expose only the instance-name field.
- The companion setup-guide edit builds successfully with Astro (124 pages) and
  renders in Chrome at `http://127.0.0.1:4322/docs/toolkits/home-assistant#setup`.

The network tests use ephemeral loopback servers and synthetic credentials.
These results do not demonstrate fresh HACS installation or real Production
pairing/MCP controls for v0.1.1.

## Before publication

1. Obtain independent review and pass CI, including HACS and hassfest.
2. Verify candidate installation and the setup form in a disposable Home Assistant
   instance. Obtain approval at pairing time for a new persistent Production
   connection; expose only virtual light/switch entities, then verify real MCP
   discovery, reads, controls, reload and idle connectivity.
3. Obtain Gerrit's approval of the exact tag, source, archive hash and release
   notes, as required by `HACS_RELEASE.md`.
4. Merge the reviewed integration, create v0.1.1 through the existing workflow,
   verify the draft artifact, and publish the approved release. Verify an update
   from v0.1.0 through HACS before claiming update coverage.
5. The companion setup guide uses the latest published release link and supports
   both the existing Production selector and the new automatic setup. It can ship
   separately through the normal website review and deployment workflow. Update
   its installation evidence after v0.1.1 is verified.
6. Update the existing HACS catalog submission's release/check links and remove
   its instruction to select Production, since the new setup has no selector.

No toolkit Lambda, gateway, portal, catalog-data or AWS infrastructure change is
required. Do not reuse earlier one-time AWS production-gate approval for this
new release or the companion website publication.
