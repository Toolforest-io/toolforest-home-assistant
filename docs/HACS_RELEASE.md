# Home Assistant toolkit: HACS validation and release preparation

The Home Assistant toolkit is currently enabled for dev verification only.
Publishing this integration does not deploy or enable the Toolforest gateway,
toolkit Lambda or portal catalog in another environment. It does not
automatically expose an existing Apple Home configuration.

## Distribution

HACS downloads `custom_components/toolforest/` from GitHub source. The repository
can be added as a custom repository of type **Integration**, independently of
acceptance into the HACS default catalog. HACS can use the default branch before
a release exists, and offers published versions when releases are available.

`hacs.json` deliberately does not enable `zip_release`: that option requires a
published release asset and prevents an unreleased source install. The standalone
`toolforest.zip` remains useful for manual installs. Its contents include Python,
JSON, bundled PNG brand assets and the license, with no development checkout
required. The icon is rendered from Toolforest's existing outlined brand mark.

## Automated validation

The existing CI workflow runs three independent checks:

- Native Home Assistant tests, Ruff and versioned ZIP packaging.
- The official Home Assistant `hassfest` action.
- The official HACS action, category `integration`, without ignored checks.

The release job depends on all three checks and creates a **draft** release only.
Neither a passing workflow nor creating a draft authorizes public publication.

Local checks from this repository:

```sh
python -m pip install -r requirements-test.txt
ruff check custom_components tests scripts
python -m pytest -q
python scripts/package.py --version 0.1.0
git diff --check
```

Use Python 3.14 for the native HA suite. The packaging script also supports
Python 3.12, the release job's existing runtime.

## Isolated HACS installation verification

Use a disposable HA instance with writable `custom_components`, not the paired
dev instance whose integration mount is read-only. On the Mac mini the prepared
instance is `http://127.0.0.1:8124`, container `toolforest-hacs-readiness`, with
configuration at
`/Volumes/Postgresql/toolforest-ha/ha-data/hacs-readiness`. It uses the same pinned
HA 2026.10.1 image as the existing dev instance. No paired credentials or config
entries are copied into it.

1. Install the official HACS release and complete native HA onboarding.
2. Add HACS through **Settings → Devices & services → Add integration** and
   complete its actual GitHub device authorization.
3. In HACS, add
   `https://github.com/Toolforest-io/toolforest-home-assistant` as a custom
   repository of type **Integration**.
4. Download the reviewed source revision, restart this disposable instance and
   compare every installed integration file to that revision, including icons.
5. Confirm **Home Assistant toolkit** appears in native **Add integration**, with
   the bundled icon and configuration flow. Additional Toolforest pairing is
   separate from this distribution test and is not required to check installation.
6. Exercise HACS re-download/update on a subsequent reviewed source revision.
   Compare the installed files again. Do not claim published-release update
   coverage from a source-branch download.

Resume the prepared instance with `docker start toolforest-hacs-readiness`.
Stop only this test instance with `docker stop toolforest-hacs-readiness`.
Do not change or restart `toolforest-home-assistant-dev` on port 8123.

Installation/update results and exact revisions must be recorded after the live
checks; this preparation document alone is not evidence that they passed.

## Separate release and default-catalog decisions

Before publishing, review the final source diff and CI results, choose the public
service availability and release audience, and obtain Gerrit's approval of the
exact tag, source revision, artifact hash and release notes. Version tags must
match `custom_components/toolforest/manifest.json`. The existing tag workflow
builds `toolforest.zip` and prepares a draft GitHub release.

After successful validation, publish a full GitHub release, not just a tag.
Verify installation and an update from the published version through HACS before
claiming release-distribution coverage. The public catalog submission must link
the release and successful HACS/hassfest runs, with all checklist claims true.

Prepare the HACS catalog change in a personal fork of `hacs/default`, on a new
branch based on `master`. Add `Toolforest-io/toolforest-home-assistant` to the
alphabetically sorted `integration` list. Keep the PR editable by maintainers.
Submit only after Gerrit approves the exact catalog PR and public release.

Bundled `custom_components/toolforest/brand/icon.png` is supported by current
HACS validation and HA versions supported by this integration. No separate
legacy Home Assistant brands-repository submission is needed for this path.

See the official [HACS inclusion requirements](https://github.com/hacs/documentation/blob/main/source/docs/publish/include.md)
and [HACS integration requirements](https://github.com/hacs/documentation/blob/main/source/docs/publish/integration.md).
