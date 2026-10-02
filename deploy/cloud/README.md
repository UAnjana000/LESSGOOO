# deploy/cloud: Vercel website + Azure B2s backend

The website (the built `web/` app) is served by Vercel. Vercel forwards `/api/*` and `/iiif/*` to one
Azure VM that runs the root `docker-compose.yml` (db, api, worker, proxy) with a Let's Encrypt
certificate. Visitors use the Vercel address. Staff use the VM address, which serves the same site
directly, so large intake uploads do not pass through Vercel.

| Part | Where | Address |
| --- | --- | --- |
| Website | Vercel | `https://<project>.vercel.app` |
| API, worker, database, files | Azure VM (B2s, 4 GB) | `https://ambedkar-archive.indiasouthcentral.cloudapp.azure.com` |

The VM address is set in `web/vercel.json`. If you choose a different DNS label in step 1, change both
rewrite destinations there.

| File | Purpose |
| --- | --- |
| `Caddyfile` | Proxy config for the VM: managed HTTPS for `SITE_ADDRESS`, plus `localhost` for the health check |
| `docker-compose.cloud.yml` | Overlay that mounts that Caddyfile into the proxy container |
| `setup-server.sh` | One-time VM preparation: 6 GB swap, Docker, repository checkout |
| `export-local-data.sh` | Run on the demo machine: database dump and stored files into `../archive-bundle` |
| `restore-data.sh` | Run once on the VM: loads that bundle into an empty installation |

## 1. Create the VM (Azure portal)

Virtual machines → Create → Azure virtual machine:

| Setting | Value |
| --- | --- |
| Region | India South Central (allowed by the subscription policy) |
| Image | Ubuntu Server 24.04 LTS (x64) |
| Size | B2s (2 vCPU, 4 GiB) |
| Authentication | SSH public key, username `azureuser`; download the private key (`.pem`) |
| Inbound ports | SSH (22), HTTP (80), HTTPS (443) |
| OS disk | Standard SSD, 64 GiB |

After it is created: open the VM's public IP address resource → Configuration → set Assignment to
**Static** and DNS name label to **`ambedkar-archive`** → Save.

## 2. Prepare the VM

```bash
ssh -i ~/Downloads/<key>.pem azureuser@ambedkar-archive.indiasouthcentral.cloudapp.azure.com
curl -fsSL https://raw.githubusercontent.com/UAnjana000/LESSGOOO/main/deploy/cloud/setup-server.sh | bash
exit   # log in again so the docker group applies
```

## 3. Copy settings and data

On the demo machine, from the repository root (Git Bash):

```bash
bash deploy/cloud/export-local-data.sh ../archive-bundle
scp -i ~/Downloads/<key>.pem .env azureuser@ambedkar-archive.indiasouthcentral.cloudapp.azure.com:archive/.env
scp -i ~/Downloads/<key>.pem -r ../archive-bundle azureuser@ambedkar-archive.indiasouthcentral.cloudapp.azure.com:
```

On the VM, edit `~/archive/.env` and set:

```
SITE_ADDRESS=ambedkar-archive.indiasouthcentral.cloudapp.azure.com
ARCHIVE_PUBLIC_BASE_URL=https://<project>.vercel.app
HTTP_PORT=80
HTTPS_PORT=443
ARCHIVE_LANGFUSE_HOST=
ARCHIVE_LANGFUSE_PUBLIC_KEY=
ARCHIVE_LANGFUSE_SECRET_KEY=
```

`ARCHIVE_PUBLIC_BASE_URL` is the address printed in the QR codes, so it is the Vercel address. The
Langfuse settings are empty because Langfuse does not run on the VM; traces go to the `traces` volume.

## 4. Build, restore, start

```bash
cd ~/archive
docker compose -f docker-compose.yml -f deploy/cloud/docker-compose.cloud.yml build
bash deploy/cloud/restore-data.sh ~/archive-bundle
docker compose -f docker-compose.yml -f deploy/cloud/docker-compose.cloud.yml up -d
docker compose ps
```

The first build downloads the embedding and reranking models and takes 20 to 40 minutes on a B2s.
`restore-data.sh` refuses to run against a database that already has tables.

## 5. Vercel

Vercel → Add New → Project → import `UAnjana000/LESSGOOO` → Root Directory **`web`** → Deploy. The
build settings come from `web/vercel.json`. Every push to `main` redeploys the website.

## Updating

Every push to `main` deploys both halves: Vercel rebuilds the website, and the GitHub Actions workflow
`.github/workflows/deploy-azure.yml` builds and tests the web app, deploys the backend to the VM, and
checks `/api/health`. Runs are listed under the repository's Actions tab; "Run workflow" there redeploys
without a push.

Manual backend deploy, on the VM: `cd ~/archive && git pull && bash deploy/cloud/deploy.sh`.

### Automatic deploys: how they are wired

| Where | Name | Value |
| --- | --- | --- |
| GitHub secret | `AZURE_DEPLOY_KEY` | Private half of a key used only for deploying |
| GitHub secret | `AZURE_KNOWN_HOSTS` | The VM's SSH host keys (`ssh-keyscan`), checked against a first-hand login |
| GitHub variable | `AZURE_HOST` | `ambedkar-archive.indiasouthcentral.cloudapp.azure.com` |
| VM `~/.ssh/authorized_keys` | the deploy key's line | `command="exec bash ~/archive/deploy/cloud/pull-and-deploy.sh",no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty ssh-ed25519 …` |

The forced command means the deploy key can only pull and deploy; it cannot open a shell. To revoke it,
delete that line on the VM and the secret on GitHub. The VM always deploys `origin/main`: if someone has
committed or edited tracked files on the VM, `pull-and-deploy.sh` saves them (a `vm-diverged-*` branch and
a patch in `~/archive-backups`) and resets to `origin/main` instead of failing every deploy with
"Not possible to fast-forward". Keep VM-only settings in `.env`, which is not tracked.

**Older VMs** still have `command="cd ~/archive && git pull --ff-only -q && exec bash deploy/cloud/deploy.sh"`.
If a deploy fails with "Not possible to fast-forward", log in with your own key (not the deploy key) once:

```bash
cd ~/archive
git fetch origin
git log --oneline origin/main..HEAD          # VM-only commits, if any
git branch "vm-diverged-$(date +%F)" HEAD     # keep them
git diff HEAD > ~/vm-edits-$(date +%F).patch  # keep any edits to tracked files
git checkout --force -B main origin/main
nano ~/.ssh/authorized_keys
```

In `authorized_keys`, on the deploy key's line only, replace
`command="cd ~/archive && git pull --ff-only -q && exec bash deploy/cloud/deploy.sh"` with
`command="exec bash ~/archive/deploy/cloud/pull-and-deploy.sh"`, leave the rest of the line as it is, and save.
Then re-run the failed "Deploy to Azure" workflow on GitHub.

Never run `docker compose down -v`: it deletes the database and file volumes.

## Checks

```bash
docker stats --no-stream                 # memory per container; the api holds about 2.8 GB
free -h                                  # RAM and swap
sudo dmesg | grep -i "killed process"    # containers killed for memory
```

If containers are killed for memory, add `ARCHIVE_RERANKER_BACKEND=lexical` to `.env` and run the
`up -d` command again. It drops the reranking model at a small cost to Ask ordering.
