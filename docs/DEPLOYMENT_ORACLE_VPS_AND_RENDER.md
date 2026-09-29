# Deployment Guide: Oracle Cloud VPS & Render

This guide provides end-to-end instructions for deploying the **Dr. B. R. Ambedkar Digital Heritage Archive** on:
1. **A Single Oracle Cloud (OCI) VPS** (Hosting both frontend & backend with Docker Compose and Caddy)
2. **Render (render.com)** (Using Render Blueprint or separate API & Static Site services)

---

## Part 1: Deploying on 1 Oracle Cloud (OCI) VPS

Oracle Cloud provides an **Always Free Tier** featuring:
- **Ampere A1 ARM Compute**: Up to 4 OCPUs, 24 GB RAM, and 200 GB block storage for free.
- **AMD Compute**: 1 OCPU, 1 GB RAM (requires 2–4 GB swap space).

Hosting the entire stack on **1 Ampere A1 VPS** is ideal and will smoothly run PostgreSQL 17 with `pgvector`, the FastAPI backend with multi-lingual embeddings (`fastembed`), document worker tasks, and Caddy serving the React PWA with automatic HTTPS.

---

### Step 1: Provision the OCI Compute Instance

1. Log into your **Oracle Cloud Console**.
2. Navigate to **Compute** -> **Instances** -> **Create Instance**.
3. Configure the instance:
   - **Name**: `ambedkar-archive-vps`
   - **Image**: **Ubuntu 22.04 LTS** or **Ubuntu 24.04 LTS** (Canonical Ubuntu).
   - **Shape**:
     - Recommended: **Ampere (ARM64)** `VM.Standard.A1.Flex` with **4 OCPUs** and **24 GB RAM** (Always Free eligible).
     - Alternative: **AMD** `VM.Standard.E2.1.Micro` (1 OCPU, 1 GB RAM).
   - **Networking**: Assign a **Public IPv4 address**.
   - **SSH Keys**: Download and save your private SSH key, or paste your public SSH key.
   - **Boot Volume**: 50 GB to 100 GB.
4. Click **Create** and note down the **Public IP Address** (e.g., `140.238.x.x`).

---

### Step 2: Open OCI Network Security List (Crucial Step)

By default, Oracle Cloud VCN blocks all incoming traffic except SSH (port 22). You **must** open ports 80 and 443 in the console:

1. In the OCI Console, go to **Networking** -> **Virtual Cloud Networks**.
2. Click your VCN (e.g., `vcn-xxxx`).
3. Under **Resources** (left sidebar), click **Security Lists**, then select **Default Security List for <your-vcn>**.
4. Click **Add Ingress Rules**:
   - **Source Type**: CIDR
   - **Source CIDR**: `0.0.0.0/0`
   - **IP Protocol**: `TCP`
   - **Destination Port Range**: `80,443`
   - **Description**: `Allow HTTP and HTTPS traffic for Archive`
5. Click **Add Ingress Rules**.

---

### Step 3: Configure the Host OS Firewall (iptables)

Oracle's Ubuntu images contain pre-configured `iptables` rules that drop incoming packets on ports 80 and 443 even after the VCN rule is added.

SSH into your Oracle VPS:
```bash
ssh -i /path/to/your_private_key.key ubuntu@<YOUR_VPS_PUBLIC_IP>
```

Run the following commands to open ports 80 and 443 on the OS firewall:
```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```
*(If `netfilter-persistent` is not installed, run `sudo apt-get update && sudo apt-get install -y iptables-persistent`)*.

*(Optional for 1 GB RAM VPS instances)* If you are on the AMD 1 GB RAM micro shape, create a 4 GB swap file so builds and embedding models do not get killed:
```bash
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

---

### Step 4: Install Docker & Docker Compose

Run this script to install the official Docker Engine and Compose plugin:
```bash
# Update packages
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg git

# Add Docker's official GPG key
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Add Docker apt repository
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker packages
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Allow current user to run docker without sudo
sudo usermod -aG docker $USER
newgrp docker
```

Verify Docker works:
```bash
docker compose version
```

---

### Step 5: Clone the Repository & Configure Environment

Clone the repository and switch to branch `B1`:
```bash
git clone https://github.com/UAnjana000/LESSGOOO.git sih-ambedkar
cd sih-ambedkar
git checkout B1
```

Create your `.env` file:
```bash
cp .env.example .env
nano .env
```

#### Scenario A: You have a Domain Name (Recommended for production HTTPS)
Point an A record in your DNS provider (e.g. Cloudflare, Namecheap, GoDaddy):
- `archive.yourdomain.com` -> `<YOUR_VPS_PUBLIC_IP>`

Set the following variables in `.env`:
```ini
ARCHIVE_ENVIRONMENT=production
ARCHIVE_PUBLIC_BASE_URL=https://archive.yourdomain.com

# Ports for public internet
HTTP_PORT=80
HTTPS_PORT=443
PUBLIC_HTTPS_PORT=443

# Caddy configuration
SITE_ADDRESS=archive.yourdomain.com
# Provide your email for automatic Let's Encrypt / ZeroSSL TLS certificates:
TLS_MODE=admin@yourdomain.com

# Strong secrets
POSTGRES_PASSWORD=your_strong_postgres_password_here
ARCHIVE_JWT_SECRET=your_random_32_char_secret_here

# Admin account bootstrap credentials
BOOTSTRAP_ADMIN_EMAIL=admin@yourdomain.com
BOOTSTRAP_ADMIN_PASSWORD=your_strong_admin_password_here
```

#### Scenario B: You are using the Raw Public IP (Without a custom domain)
If you don't have a domain yet, Caddy can serve over HTTP or with internal self-signed TLS:
```ini
ARCHIVE_ENVIRONMENT=demo
ARCHIVE_PUBLIC_BASE_URL=http://<YOUR_VPS_PUBLIC_IP>

HTTP_PORT=80
HTTPS_PORT=443
PUBLIC_HTTPS_PORT=443

SITE_ADDRESS=<YOUR_VPS_PUBLIC_IP>
TLS_MODE=internal

POSTGRES_PASSWORD=your_strong_postgres_password_here
ARCHIVE_JWT_SECRET=your_random_32_char_secret_here
BOOTSTRAP_ADMIN_EMAIL=admin@archive.local
BOOTSTRAP_ADMIN_PASSWORD=your_admin_password_here
```

---

### Step 6: Build & Start the Archive Stack

Start the entire system:
```bash
docker compose up -d --build
```

This single command:
1. Starts **PostgreSQL 17 with `pgvector`** (`db`).
2. Runs database migrations (`alembic upgrade head`) and seeds the admin user.
3. Starts the **FastAPI API server** (`api`) with fastembed models pre-cached.
4. Starts the **Background Worker** (`worker`) for OCR and document transformations.
5. Builds the **React PWA frontend** with Vite and starts the **Caddy reverse proxy** (`proxy`) terminating SSL and forwarding `/api/*` and `/iiif/*` to the FastAPI backend.

Check container statuses:
```bash
docker compose ps
```

View API startup logs:
```bash
docker compose logs -f api
```

Once `api` reports healthy, visit:
- Visitor Portal: `https://archive.yourdomain.com` (or `http://<YOUR_VPS_PUBLIC_IP>`)
- Kiosk Mode: `https://archive.yourdomain.com/kiosk`
- Staff Archivist Portal: `https://archive.yourdomain.com/staff/login`

---

### Step 7: Useful Maintenance Commands on VPS

- **View real-time logs**:
  ```bash
  docker compose logs -f
  ```
- **Update to latest code**:
  ```bash
  git pull origin B1
  docker compose up -d --build
  ```
- **Run a manual backup**:
  ```bash
  docker compose exec worker python -m archive.cli backup
  ```
- **Restart services**:
  ```bash
  docker compose restart
  ```

---
---

## Part 2: Deploying on Render (render.com)

Render is a managed Cloud Application platform. You can deploy the Ambedkar Archive onto Render using either:
- **Method A: 1-Click Render Blueprint (`render.yaml`)** (Recommended)
- **Method B: Manual Setup on Render Dashboard**

---

### Prerequisite: PostgreSQL with `pgvector`

Render's managed database free tier does not include `pgvector` by default. For a zero-cost, persistent cloud database with `pgvector` pre-installed:

1. Create a free account on [Supabase](https://supabase.com) (or [Neon](https://neon.tech)).
2. Create a new project (e.g. `ambedkar-archive-db`).
3. In Supabase Dashboard -> **Project Settings** -> **Database**, copy your **Connection String (URI)**:
   ```
   postgresql://postgres.[PROJECT_REF]:[PASSWORD]@aws-0-[REGION].pooler.supabase.com:6543/postgres
   ```
4. In Supabase SQL Editor, verify `vector` is enabled (enabled by default on Supabase):
   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   ```

*(Note: The archive automatically converts `postgres://` and `postgresql://` connection strings to `postgresql+psycopg://` without manual edits).*

---

### Method A: 1-Click Deployment via `render.yaml` Blueprint

The repository contains a `render.yaml` file pre-configured for Render Blueprints.

1. Push your repository to GitHub.
2. Log into [Render Dashboard](https://dashboard.render.com).
3. Click **New +** (top right) -> **Blueprint**.
4. Connect your GitHub repository (`sih-Ambedkar` or `LESSGOOO`).
5. Choose branch `B1`.
6. Render will parse `render.yaml` and display two services:
   - **`ambedkar-archive-api`** (Docker Web Service)
   - **`ambedkar-archive-web`** (Static Site Frontend)
7. Fill in the requested environment variables:
   - `ARCHIVE_DATABASE_URL`: Paste your Supabase/Neon connection string.
   - `ARCHIVE_PUBLIC_BASE_URL`: Leave blank or set to `https://ambedkar-archive-api.onrender.com`.
   - `VITE_API_BASE_URL`: Set to `https://ambedkar-archive-api.onrender.com`.
   - `ARCHIVE_CORS_ORIGINS`: Set to `*` or `https://ambedkar-archive-web.onrender.com`.
8. Click **Apply**.
9. Render will automatically build the backend Docker container and compile the Vite frontend static site.

---

### Method B: Manual Service Creation on Render

If you prefer to configure services manually in Render:

#### 1. Backend Web Service (`ambedkar-archive-api`)
1. Click **New +** -> **Web Service**.
2. Select your GitHub repository.
3. Configure:
   - **Name**: `ambedkar-archive-api`
   - **Language**: `Docker`
   - **Dockerfile Path**: `./backend/Dockerfile`
   - **Docker Context**: `./backend`
   - **Instance Type**: **Starter** ($7/mo) or Free (Note: free has 512MB RAM; Starter is recommended for embedding models).
4. Under **Environment Variables**, add:
   - `ARCHIVE_ENVIRONMENT`: `production`
   - `ARCHIVE_DATABASE_URL`: Your Supabase connection string.
   - `ARCHIVE_PUBLIC_BASE_URL`: `https://ambedkar-archive-api.onrender.com`
   - `ARCHIVE_JWT_SECRET`: *(Click Generate)*
   - `ARCHIVE_BOOTSTRAP_ADMIN_EMAIL`: `admin@archive.org`
   - `ARCHIVE_BOOTSTRAP_ADMIN_PASSWORD`: *(Enter strong password)*
   - `ARCHIVE_CORS_ORIGINS`: `*`
   - `PORT`: `8000`
5. Click **Create Web Service**.

#### 2. Frontend Static Site (`ambedkar-archive-web`)
1. Click **New +** -> **Static Site**.
2. Select your GitHub repository.
3. Configure:
   - **Name**: `ambedkar-archive-web`
   - **Branch**: `B1`
   - **Root Directory**: `web`
   - **Build Command**: `npm ci && npm run build`
   - **Publish Directory**: `dist`
4. Under **Environment Variables**, add:
   - `VITE_API_BASE_URL`: `https://ambedkar-archive-api.onrender.com`
5. Under **Redirects/Rewrites**:
   - **Type**: `Rewrite`
   - **Source**: `/*`
   - **Destination**: `/index.html`
6. Click **Create Static Site**.

---

### Keeping Render Free Tier Active

Render free web services enter sleep mode after 15 minutes of inactivity. When a visitor arrives, waking up takes 30–50 seconds.

To keep your free instance active 24/7 for evaluation or presentations:
1. Create a free account at [cron-job.org](https://cron-job.org) or [UptimeRobot](https://uptimerobot.com).
2. Create a monitor to ping:
   - **URL**: `https://ambedkar-archive-api.onrender.com/api/health/ready`
   - **Interval**: Every 5 or 10 minutes.
3. This guarantees zero cold-start delay for evaluators.

---

## Comparison Summary

| Feature | 1 Oracle Cloud VPS (Recommended) | Render (render.com) |
| :--- | :--- | :--- |
| **Cost** | 100% Free (Always Free Tier) | Free or Starter ($7/mo) |
| **Resources** | Up to 4 OCPU, 24 GB RAM, 200 GB Disk | 512 MB Free / 2 GB Starter |
| **Setup Complexity** | Single `docker compose up -d` | Split Blueprint / Cloud DB |
| **ML & FastEmbed** | Full local speed (zero memory limits) | Requires Starter or cloud API |
| **Database** | Local PostgreSQL 17 + `pgvector` container | External Supabase / Neon |
| **Cold Starts** | None (always running) | 30s cold start on free plan unless pinged |
| **SSL / TLS** | Auto Let's Encrypt via Caddy proxy | Auto Let's Encrypt via Render |
