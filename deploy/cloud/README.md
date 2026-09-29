# deploy/cloud: Vercel website + Azure B2s backend

The website (the built `web/` app) is served by Vercel. Vercel forwards `/api/*` and `/iiif/*` to one
Azure VM that runs the root `docker-compose.yml` (db, api, worker, proxy) with a Let's Encrypt
certificate. Visitors use the Vercel address. Staff use the VM address, which serves the same site
directly, so large intake uploads do not pass through Vercel.

| Part | Where | Address |
| --- | --- | --- |
| Website | Vercel | `https://<project>.vercel.app` |
| API, worker, database, files | Azure VM (B2s, 4 GB) | `https://ambedkar-archive.centralindia.cloudapp.azure.com` |

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
| Region | Central India |
| Image | Ubuntu Server 24.04 LTS (x64) |
| Size | B2s (2 vCPU, 4 GiB) |
| Authentication | SSH public key, username `azureuser`; download the private key (`.pem`) |
| Inbound ports | SSH (22), HTTP (80), HTTPS (443) |
| OS disk | Standard SSD, 64 GiB |

After it is created: open the VM's public IP address resource → Configuration → set Assignment to
**Static** and DNS name label to **`ambedkar-archive`** → Save.

## 2. Prepare the VM

```bash
ssh -i ~/Downloads/<key>.pem azureuser@ambedkar-archive.centralindia.cloudapp.azure.com
curl -fsSL https://raw.githubusercontent.com/UAnjana000/LESSGOOO/main/deploy/cloud/setup-server.sh | bash
exit   # log in again so the docker group applies
```

## 3. Copy settings and data

On the demo machine, from the repository root (Git Bash):

```bash
bash deploy/cloud/export-local-data.sh ../archive-bundle
scp -i ~/Downloads/<key>.pem .env azureuser@ambedkar-archive.centralindia.cloudapp.azure.com:archive/.env
scp -i ~/Downloads/<key>.pem -r ../archive-bundle azureuser@ambedkar-archive.centralindia.cloudapp.azure.com:
```

On the VM, edit `~/archive/.env` and set:

```
SITE_ADDRESS=ambedkar-archive.centralindia.cloudapp.azure.com
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

- Website only: push to `main`; Vercel redeploys.
- Backend: on the VM, `cd ~/archive && git pull && docker compose -f docker-compose.yml -f deploy/cloud/docker-compose.cloud.yml up -d --build`.

Never run `docker compose down -v`: it deletes the database and file volumes.

## Checks

```bash
docker stats --no-stream                 # memory per container; the api holds about 2.8 GB
free -h                                  # RAM and swap
sudo dmesg | grep -i "killed process"    # containers killed for memory
```

If containers are killed for memory, add `ARCHIVE_RERANKER_BACKEND=lexical` to `.env` and run the
`up -d` command again. It drops the reranking model at a small cost to Ask ordering.
