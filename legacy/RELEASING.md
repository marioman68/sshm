# Releasing sshm

The version lives in **one place**: `__version__` in `src/sshm/__init__.py`.
Everything else (pyproject, RPM spec, CHANGELOG, window title, `sshm --version`)
reads it or is checked against it by `tests/test_version.py`.

## Versioning

| Bump | When | Example |
|---|---|---|
| `patch` | bug fixes, small tweaks | 3.2.0 → 3.2.1 |
| `minor` | new features, backwards compatible | 3.2.1 → 3.3.0 |
| `major` | breaking changes (config format, removed commands) | 3.3.0 → 4.0.0 |

## Cutting a release

```bash
make bump BUMP=patch NOTE="Fix tray icon on GNOME"   # updates __init__.py, spec, CHANGELOG
$EDITOR CHANGELOG.md                                  # optional: flesh out the notes
make test lint
git commit -am "Release $(make -s version)"
git tag "v$(make -s version)"
git push && git push --tags
```

Pushing the tag runs `.github/workflows/release.yml`, which:

1. refuses to continue if the tag doesn't match `__version__`,
2. runs the tests,
3. publishes a GitHub release with `sshm-X.Y.Z.tar.gz`, `sshm-X.Y.Z.zip` and the
   CHANGELOG section as release notes,
4. triggers COPR (if the `COPR_WEBHOOK_URL` secret is set).

## COPR setup (one time)

Project: [lucasdunham85/sshm](https://copr.fedorainfracloud.org/coprs/lucasdunham85/sshm/) → **Packages → New package → SCM**:

| Field | Value |
|---|---|
| Clone URL | `https://github.com/marioman68/sshm.git` |
| Committish | `main` (or leave empty) |
| Spec file | `packaging/sshm.spec` |
| SRPM build method | **make_srpm** |

`make_srpm` runs `.copr/Makefile`, which builds the source tarball straight from
the checkout, so builds don't depend on a GitHub release existing first.

Then pick how builds are triggered:

* **Every push** — COPR → *Settings → Integrations* → copy the GitHub webhook
  URL into GitHub → *Settings → Webhooks* (content type `application/json`, push events).
* **Only on release tags** — COPR → *Settings → Integrations* → copy the
  *custom webhook* URL for the package into a GitHub repository secret named
  `COPR_WEBHOOK_URL`. The release workflow calls it after publishing.

The `rpm` job in `.github/workflows/ci.yml` performs the same SRPM → RPM build in
a `fedora:latest` container on every push, so spec problems show up in CI first.

## Upgrades from 2.x RPMs

3.x no longer ships a system-wide `/etc/xdg/autostart` entry; users enable
"Start at login" in Settings. Existing configs (`~/.ssh_servers` etc.) are migrated
automatically on first launch.
