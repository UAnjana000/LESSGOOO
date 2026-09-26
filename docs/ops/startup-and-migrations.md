# Host preparation, start-up, migrations and upgrades [PROD]

All commands are PowerShell, run from `deploy\production` unless stated otherwise. To keep them short, define once per session:

```powershell
cd <repo>\deploy\production
function dc { docker compose --env-file .env -f compose.yaml @args }
```

The literal command is always `docker compose --env-file .env -f compose.yaml <subcommand>`.

## 1. Windows host preparation (once)

| Item | Requirement |
| --- | --- |
| Container runtime | Docker Desktop with the WSL2 backend, or Docker Engine inside a WSL2 distribution. Docker Desktop starts only after a user signs in: enable "Start Docker Desktop when you sign in" and use a dedicated, locked-down service account with automatic sign-in, or run Docker Engine in WSL2 started by a boot-time scheduled task. Check Docker Desktop's subscription terms for the institution. A Linux host is the conventional alternative and runs the same compose file |
| Docker disk image | Move it off the system drive (Settings > Resources > Advanced > Disk image location). `pgdata` and the other named volumes live there |
| Preservation disk | Dedicated volume, e.g. `P:`. Not the system drive, not the backup disk. BitLocker on. Snapshots or versioning at the storage layer if available |
| Backup disk | A different physical disk, e.g. `B:`. BitLocker on |
| Intake folder | Where the digitisation station drops capture batches, e.g. `D:\capture-intake` |
| Power and time | UPS for the server and network gear. Windows time sync on (JWT expiry and log timestamps depend on it) |
| Network | Two NICs (gallery VLAN, staff VLAN) or one NIC plus firewall scoping. See [https-and-access.md](https-and-access.md) |
| Access | Membership of `docker-users` equals administrator access to the archive; keep it to the operators |

```powershell
New-Item -ItemType Directory P:\archive\preservation, B:\archive-backups, B:\archive-restore-staging, D:\capture-intake
Set-Content P:\archive\preservation\.archive-preservation-volume 'Ambedkar archive preservation volume - do not delete'
```

## 2. First start

```powershell
Copy-Item .env.example .env
notepad .env                                   # sites, bind IPs, paths, non-secret ARCHIVE_* settings
.\scripts\New-ProductionSecrets.ps1            # creates secrets\* (see secrets.md)
# fill secrets\sarvam_api_key, secrets\llm_api_key, secrets\langfuse_secret_key from the secret store if used
# copy visitor.crt/.key and staff.crt/.key into certs\ (see https-and-access.md)
.\scripts\Test-ProductionConfig.ps1            # must print "All checks passed."
.\scripts\Invoke-ReleaseBuild.ps1              # builds api, web, ops images tagged RELEASE_TAG
docker compose --env-file .env -f compose.yaml up -d
docker compose --env-file .env -f compose.yaml ps
```

Expected: `db`, `api`, `worker`, `web` and `proxy` show `healthy`, and `migrate` shows `Exited (0)`. Then:

1. Sign in at `https://<STAFF_SITE>:8443/staff` with `ARCHIVE_BOOTSTRAP_ADMIN_EMAIL` and the `bootstrap_admin_password` secret. Store that password in the institution's password manager.
2. Empty the secret file. The account is kept; bootstrap skips existing accounts.

   ```powershell
   [IO.File]::WriteAllBytes("$PWD\secrets\bootstrap_admin_password", [byte[]]@())
   ```

3. Enter the rights register before any intake (spec 8.1).
4. Point kiosks and the smart display at `https://<VISITOR_SITE>/` (display layout per the PWA), and pin them in kiosk mode.

Never run `seed-fixtures` in production. Fixtures are synthetic demo data.

## 3. Migrations

- **Automatic.** Every `up` runs the one-shot `migrate` service (`alembic upgrade head`, then `archive.cli bootstrap`) after the database is healthy and **before** any api or worker container starts. Replicas therefore never race on migrations.
- **Manual command:**

  ```powershell
  docker compose --env-file .env -f compose.yaml run --rm migrate
  docker compose --env-file .env -f compose.yaml run --rm migrate alembic current
  docker compose --env-file .env -f compose.yaml logs migrate
  ```

- **Check:** `https://<STAFF_SITE>:8443/api/health/ready` reports the applied Alembic revision in `migration`.
- If `migrate` fails, api and worker do not start. That is intentional. Read `logs migrate`, fix the cause, and run `up -d` again.

## 4. Upgrades

```powershell
.\scripts\Invoke-ArchiveBackup.ps1 -OffsiteRoot <off-site path>   # pre-upgrade backup, verified
git fetch; git checkout <release>
notepad .env                                                      # new RELEASE_TAG
.\scripts\Test-ProductionConfig.ps1
.\scripts\Invoke-ReleaseBuild.ps1
docker compose --env-file .env -f compose.yaml up -d              # migrate runs, then services recreate
docker compose --env-file .env -f compose.yaml ps
```

Keep the previous tag's images until the new release has run for a while (`docker image ls ambedkar-archive/*`).

## 5. Rollback

- **No schema change in the release:** set `RELEASE_TAG` back and run `up -d`.
- **Schema changed:** do not run `alembic downgrade`. The only downgrade in the repository drops the whole schema. Restore the pre-upgrade backup ([backup-and-restore.md](backup-and-restore.md), "Disaster recovery"), then run the old tag.

## 6. Everyday commands

```powershell
docker compose --env-file .env -f compose.yaml ps
docker compose --env-file .env -f compose.yaml logs -f --tail 100 api worker proxy
docker compose --env-file .env -f compose.yaml restart proxy          # after replacing certificates
docker compose --env-file .env -f compose.yaml stop                   # planned maintenance
docker compose --env-file .env -f compose.yaml up -d                  # start again
docker compose --env-file .env -f compose.yaml up -d --scale api=2 --scale worker=2
docker compose --env-file .env -f compose.yaml run --rm ops python -m archive.cli import-manifest /intake/<batch>/manifest.json --enqueue --actor <operator>
```

Use `run --rm ops ...` for CLI tasks, not `exec api ...`. `exec` bypasses the entrypoint that loads the secrets.

**Never run `docker compose down -v` on the production project.** It deletes `pgdata` and the delivery and derivative volumes. `down` without `-v` is safe.

## Smoke test record (developer workstation, not production)

This was run with a temp `.env`, localhost-only ports, temp folders standing in for the disks, and a separate project name, beside the running local demo.

- **Healthy start.** `up -d` brought all services up healthy. `migrate` exited 0, with `created_staff: [admin]` and `demo_staff: false`.
- **Web container fix.** The first start exposed a failure: Caddy would not exec with all capabilities dropped. Adding `NET_BIND_SERVICE` fixed it, as recorded in `compose.yaml`.
- **Release build.** `Invoke-ReleaseBuild.ps1` built the api image with `INSTALL_DEV=0`, the web image from `web/Dockerfile`, and the ops image with `pg_dump` 17.11.
- **Recreate and scale.** `up -d --scale api=2` recreated the services on those images; `migrate` re-ran harmlessly with an exit code of 0.
- **No implicit builds.** An earlier version gave `ops` a build section, and `docker compose run ops` silently rebuilt images. That is why `ops` now has `pull_policy: never` and images are built only by the release script.
