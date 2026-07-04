# GPU Index

A public dashboard of GPU cloud **prices** and **availability**, updated every hour.

Visit the site to compare per-GPU-hour costs across providers, see price history, and check whether capacity looked available recently. A free JSON API exposes the same data.

---

## What runs where

Everything ships as three Docker containers:

| Container | What it does |
|-----------|--------------|
| **scheduler** | Polls providers hourly, stores observations, computes rollups |
| **api** | Serves the website + JSON API |
| **caddy** | Web server / reverse proxy (handles HTTPS in production) |

Data lives in a SQLite file on a Docker volume (`gpuindex-data`). Both scheduler and api read/write the same file.

---

## Run on your Mac (local)

**Prerequisites:** [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running.

```bash
git clone https://github.com/varunkandukuri24/gpuindex.git
cd gpuindex

cp .env.example .env
# Edit .env — at minimum set LAMBDA_API_KEY and CONTACT_EMAIL

docker compose up --build -d
```

Open **http://localhost:8080**

Useful commands:

```bash
docker compose exec scheduler gpuindex-status          # health + row counts
docker compose exec scheduler gpuindex-rollup          # refresh site snapshots now
docker compose exec scheduler gpuindex-snapshot --gpu H100-SXM-80GB
docker compose logs -f scheduler                       # watch collectors
docker compose down                                    # stop everything
```

Run tests (optional, for development):

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

---

## Environment variables

Copy `.env.example` to `.env`. Never commit `.env`.

| Variable | Required | Description |
|----------|----------|-------------|
| `LAMBDA_API_KEY` | Recommended | Lambda Cloud API key ([get one here](https://cloud.lambda.ai)) |
| `CONTACT_EMAIL` | Recommended | Shown in collector User-Agent |
| `RUNPOD_API_KEY` | Optional | RunPod works without a key |
| `COLLECTOR_INTERVAL_MINUTES` | Optional | Default `60` |
| `DATABASE_URL` | Auto-set | Leave as-is in Docker |

---

## JSON API

Rate-limited, no auth required:

| Endpoint | Description |
|----------|-------------|
| `GET /api/v1/index` | All GPUs — cheapest prices, availability indicator |
| `GET /api/v1/prices?gpu=H100-SXM-80GB` | Provider comparison + price history |
| `GET /api/v1/availability?gpu=H100-SXM-80GB` | Daily availability rollup |
| `GET /api/v1/meta` | Snapshot timestamp |

---

# Deploy to the internet

This section assumes you've never used a VPS before. That's fine.

## What is a VPS?

A **VPS** (Virtual Private Server) is a small Linux computer you rent in a data center. It runs 24/7 on someone else's hardware, has a public IP address, and costs about **$5–6/month**.

Your Mac sleeps; a VPS doesn't. That's why you deploy here instead of leaving Docker running on your laptop.

You'll SSH into it (remote terminal) and run the same `docker compose` commands.

## What you need before starting

1. **A VPS account** — pick one:
   - [Hetzner](https://www.hetzner.com/cloud) (cheapest, ~€4/mo)
   - [DigitalOcean](https://www.digitalocean.com) (~$6/mo)
   - [Linode](https://www.linode.com) (~$5/mo)

2. **A domain name** (optional but recommended) — e.g. `gpuindex.dev` from Namecheap, Cloudflare, Google Domains (~$10/year). You can also use the raw IP address to start, but you won't get HTTPS easily.

3. **Your `.env` file** from local — especially `LAMBDA_API_KEY`.

---

## Step 1 — Create the VPS

In your provider's dashboard:

1. Click **Create server** / **Create droplet**
2. **Region:** pick one close to you (or US-East if unsure)
3. **OS:** Ubuntu 24.04 LTS
4. **Size:** smallest option (1 vCPU, 1 GB RAM) — enough for this project
5. **Authentication:** add your **SSH key** if you have one, or use a root password (you'll get it by email)
6. Create it

You'll get an **IP address** like `123.45.67.89`. Write it down.

---

## Step 2 — Connect to your VPS

On your Mac, open Terminal:

```bash
ssh root@123.45.67.89
```

Replace with your IP. Accept the fingerprint prompt. You're now inside the VPS.

---

## Step 3 — Install Docker on the VPS

Run these commands on the VPS:

```bash
curl -fsSL https://get.docker.com | sh
```

Verify:

```bash
docker --version
docker compose version
```

---

## Step 4 — Clone your code on the VPS

Still on the VPS:

```bash
git clone https://github.com/varunkandukuri24/gpuindex.git
cd gpuindex
```

---

## Step 5 — Configure secrets

```bash
cp .env.example .env
nano .env
```

Set your keys (at minimum `LAMBDA_API_KEY` and `CONTACT_EMAIL`). Save: `Ctrl+O`, Enter, `Ctrl+X`.

---

## Step 6 — (Optional) Copy your local database

If you've been collecting data on your Mac and want to keep it, do this **on your Mac** first:

```bash
cd ~/gpuindex
docker compose down

docker run --rm \
  -v gpuindex_gpuindex-data:/data \
  -v $(pwd):/backup \
  alpine tar czf /backup/gpuindex-db-backup.tar.gz -C /data .
```

Copy the backup to your VPS:

```bash
scp ~/gpuindex/gpuindex-db-backup.tar.gz root@123.45.67.89:~/gpuindex/
```

Then **on the VPS**, after first `docker compose up` (step 7):

```bash
cd ~/gpuindex
docker compose up -d scheduler
docker compose down

docker run --rm \
  -v gpuindex_gpuindex-data:/data \
  -v $(pwd):/backup \
  alpine tar xzf /backup/gpuindex-db-backup.tar.gz -C /data
```

Skip this section if you're fine starting with an empty database.

---

## Step 7 — Start the app

On the VPS:

```bash
cd ~/gpuindex
docker compose up --build -d
docker compose exec scheduler alembic upgrade head
docker compose exec scheduler gpuindex-rollup
docker compose exec scheduler gpuindex-status
```

You should see price observations > 0 and collectors succeeding.

**Test without a domain:** the app listens on port 8080 internally, but Caddy only exposes port 8080 mapped to 80. For a quick test, temporarily edit `docker-compose.yml` caddy ports to `"80:80"` and visit `http://123.45.67.89` in your browser.

---

## Step 8 — Point your domain at the VPS

In your domain registrar's DNS settings (Cloudflare, Namecheap, etc.):

| Type | Name | Value | TTL |
|------|------|-------|-----|
| A | `@` | `123.45.67.89` | Auto |
| A | `www` | `123.45.67.89` | Auto |

Or use a subdomain:

| Type | Name | Value |
|------|------|-------|
| A | `gpu` | `123.45.67.89` |

Wait 5–30 minutes for DNS to propagate. Check with:

```bash
dig gpu.yourdomain.com +short
```

It should print your VPS IP.

---

## Step 9 — Enable HTTPS

On the VPS, edit the Caddyfile:

```bash
nano ~/gpuindex/Caddyfile
```

Replace the contents with your domain (Caddy auto-provisions HTTPS):

```
gpu.yourdomain.com {
    reverse_proxy api:8000
}
```

Update `docker-compose.yml` caddy ports to expose standard web ports:

```yaml
    ports:
      - "80:80"
      - "443:443"
```

Restart:

```bash
cd ~/gpuindex
docker compose up -d
```

Visit **https://gpu.yourdomain.com** — you should see the index with a padlock.

---

## Step 10 — Stop local Docker on your Mac

Once the VPS is running and collecting data:

```bash
cd ~/gpuindex
docker compose down
```

Quit Docker Desktop if you want your laptop to cool down. The VPS handles everything now.

---

## Keeping it running

Docker is set to `restart: unless-stopped`, so containers survive reboots.

**Deploy updates** after you push code to GitHub:

```bash
# on the VPS
cd ~/gpuindex
git pull
docker compose up --build -d
docker compose exec scheduler alembic upgrade head
```

**Check health anytime:**

```bash
docker compose ps
docker compose exec scheduler gpuindex-status
docker compose logs --tail=50 scheduler
```

**Monthly cost:** ~$5 VPS + ~$1 domain = **~$6/month total**.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Site shows "No snapshot data yet" | Run `docker compose exec scheduler gpuindex-rollup` |
| Lambda shows 0 rows | Check `LAMBDA_API_KEY` in `.env`, then `docker compose up -d --force-recreate` |
| Can't SSH in | Check IP, verify VPS is running in provider dashboard |
| HTTPS not working | DNS must point to VPS first; ports 80 and 443 open in provider firewall |
| Out of disk | `docker system prune` or upgrade VPS storage |

---

## Project layout

```
collectors/     Provider polling logic
analysis/       Rollup + report scripts
api/            Website + JSON API
jobs/           Scheduler + status CLI
web/            HTML templates + CSS
db/             Database models
tests/          Unit tests (mocked HTTP, no live API calls)
```

---

## License

TBD
