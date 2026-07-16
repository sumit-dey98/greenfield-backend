# Production Deployment Guide

**Current stack**: Render (app hosting) + Neon (managed Postgres) + GitHub Actions (CI sanity check).

This is the active deploy path. A self-hosted alternative (Oracle Cloud VM + nginx + certbot)
is documented at the bottom as a **future migration** once you're ready to run your own server —
kept here in detail so the switch is a config change, not a from-scratch rebuild.

(Koyeb was tried first but its dashboard was stuck on an acquisition-notice screen with no way
to reach service creation, and its CLI login also failed to resolve this — abandoned in favor
of Render, which is stable and well-established. Render's free tier does sleep after 15 min of
inactivity, causing a ~30-60s cold start on the next request — accepted for now since this is
low-traffic/still in development; revisit with a keep-alive ping or the $7/mo Starter plan if
that becomes a problem for real users.)

## 1. Neon (managed Postgres)

1. Create a free account at neon.tech, create a project (e.g. `greenfield-prod`).
2. Copy the **pooled** connection string (uses their PgBouncer endpoint, has `-pooler` in the
   hostname) — this is what `DATABASE_URL` should be in production, not the direct endpoint.
3. Locally (or from any machine with network access), run migrations once against it:
   ```
   DATABASE_URL="<neon-pooled-url>" alembic upgrade head
   ```
4. Confirm tables exist via the Neon SQL editor or `psql`.

## 2. Render setup (one-time, via dashboard)

1. Create a free account at render.com and connect your GitHub account (grants Render read
   access to the `greenfield-backend` repo so it can auto-deploy on push).
2. Dashboard → **New** → **Web Service** → select the `greenfield-backend` repo.
3. Runtime: Render auto-detects the `Dockerfile` at repo root — confirm **Docker** is selected
   as the environment (not "Python", which would ignore the Dockerfile).
4. Branch: `main`.
5. Instance type: **Free**.
6. Region: pick the closest available to your users.
7. Health check path: `/health` (already implemented, checks real DB connectivity).
8. Environment variables — add these under the service's Environment tab (mark `SECRET_KEY`
   and `DATABASE_URL` as **secret** so they're not shown in logs/build output):
   ```
   DATABASE_URL=<neon-pooled-connection-string>
   SECRET_KEY=<output of: openssl rand -hex 32>
   ALGORITHM=HS256
   ACCESS_TOKEN_EXPIRE_MINUTES=180
   REFRESH_TOKEN_EXPIRE_DAYS=7
   ENVIRONMENT=production
   CORS_ORIGINS=https://<your-vercel-app>.vercel.app
   ```
   Note: the `Dockerfile` already binds gunicorn to `$PORT` (defaulting to 8000), so Render's
   auto-injected `PORT` env var is picked up automatically — no extra config needed here.
9. Click **Create Web Service**. Render builds the Dockerfile and deploys — first build takes a
   few minutes. You'll get a public HTTPS URL like `https://greenfield-backend.onrender.com`
   automatically, no certbot/nginx needed.
10. Run migrations once against the live app — no shell/exec needed since Neon is reachable
    from anywhere with network access:
    ```
    DATABASE_URL="<neon-pooled-connection-string>" alembic upgrade head
    ```
    (Same command as step 1.3 — safe to re-run; Alembic no-ops if already at head.)
11. Verify:
    ```
    curl https://<your-app>.onrender.com/health
    ```
    Should return `{"db":"connected","students":<N>}`. The first request after any idle period
    will be slow (~30-60s cold start) — that's expected on the free tier, not a bug.

## 3. GitHub Actions (CI)

`.github/workflows/deploy.yml` runs on every push/PR: installs deps and runs
`python -m compileall app` as a fast sanity check before Render even starts a build.

**Deploys themselves are handled entirely by Render's own GitHub integration** — pushing to
`main` triggers Render to pull, build, and redeploy automatically. No GitHub secrets, SSH keys,
or container registry needed for this path.

## 4. Frontend (Vercel) update

Update the frontend's API base URL environment variable on Vercel to your Render app's URL
(`https://<your-app>.onrender.com`), redeploy the frontend, and confirm login/auth works
end to end.

## 5. Ongoing deploys

Every push to `main` auto-builds and redeploys on Render — nothing to run manually. Check
build/runtime logs in the Render dashboard under the service's Logs tab.

---

## Future migration: self-hosted Oracle Cloud VM

Once you're ready to run and own the full stack yourself (nginx, TLS, systemd, SSH deploys —
the "typical production infra" pattern), this is the path. `docker-compose.prod.yml` in this
repo is already written for this and unused until you switch. Nothing here needs to happen now.

### Why move later
Render abstracts away the server; this setup teaches the underlying pieces directly — reverse
proxy, TLS termination, container orchestration via Compose, deploy-over-SSH — the same shape
you'd run at most companies before a Kubernetes migration.

### 1. Provision the VM

1. Sign up at oracle.com/cloud/free (requires a card for identity verification, not charged
   for Always Free resources).
2. Create a Compute Instance: Always Free-eligible shape (e.g. `VM.Standard.A1.Flex` or
   `VM.Standard.E2.1.Micro`), Ubuntu 22.04/24.04 image. Save the generated SSH key pair.
3. In the VM's subnet **Security List** (or attached Network Security Group), add ingress rules
   for TCP 80 and 443 from `0.0.0.0/0` (22 should already be open for SSH).
4. Note the instance's **public IP** — this is `<VM_IP>` referenced below.

SSH in:
```
ssh -i /path/to/key ubuntu@<VM_IP>
```

### 2. Install Docker + nginx + certbot

```
sudo apt update && sudo apt upgrade -y
sudo apt install -y ca-certificates curl gnupg nginx certbot python3-certbot-nginx ufw

# Docker
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
newgrp docker

# Firewall (VM-local, in addition to the cloud security list)
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
```

### 3. Create a dedicated deploy user (used by GitHub Actions, not your personal login)

```
sudo adduser --disabled-password --gecos "" deploy
sudo usermod -aG docker deploy
sudo mkdir -p /home/deploy/.ssh
sudo ssh-keygen -t ed25519 -f /tmp/deploy_key -N "" -C "github-actions-deploy"
sudo mv /tmp/deploy_key.pub /home/deploy/.ssh/authorized_keys
sudo chown -R deploy:deploy /home/deploy/.ssh
sudo chmod 700 /home/deploy/.ssh && sudo chmod 600 /home/deploy/.ssh/authorized_keys
cat /tmp/deploy_key   # copy this PRIVATE key into the GitHub secret DEPLOY_SSH_KEY, then delete it locally
shred -u /tmp/deploy_key
```

### 4. First-time app deploy (as the `deploy` user)

```
sudo su - deploy
git clone https://github.com/sumit-dey98/greenfield-backend.git
cd greenfield-backend

# Create the prod env file (never committed) — fill in real values.
cp .env.example .env.prod
nano .env.prod
```

`.env.prod` should contain:
```
DATABASE_URL=<neon-pooled-connection-string>
SECRET_KEY=<output of: openssl rand -hex 32>
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=180
REFRESH_TOKEN_EXPIRE_DAYS=7
ENVIRONMENT=production
CORS_ORIGINS=https://<your-vercel-app>.vercel.app,https://api.<VM_IP>.sslip.io
```

You'll need to push the image somewhere the VM can pull from (GitHub Container Registry works
well — `docker build -t ghcr.io/sumit-dey98/greenfield-backend:latest . && docker push ...`
from CI, updating `docker-compose.prod.yml`'s image reference to match your actual repo path),
then:
```
echo "<a GitHub Personal Access Token with read:packages>" | docker login ghcr.io -u sumit-dey98 --password-stdin
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml exec api alembic upgrade head
```

The API is now listening on `127.0.0.1:8000` on the VM (not yet publicly reachable — that's
nginx's job next).

### 5. nginx reverse proxy + free HTTPS via sslip.io

No domain is owned, so use `sslip.io`, a free wildcard DNS service: any hostname of the form
`<anything>.<VM_IP>.sslip.io` automatically resolves to `<VM_IP>`. Use
`api.<VM_IP>.sslip.io` (dots in the IP work fine as DNS labels) as the public hostname — or a
real domain if you've bought one by then.

```
sudo nano /etc/nginx/sites-available/greenfield-api
```

```nginx
server {
    listen 80;
    server_name api.<VM_IP>.sslip.io;

    client_max_body_size 10M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

(Replace both literal `<VM_IP>` occurrences with the real dotted IP, e.g. `api.150.230.12.34.sslip.io`.)

```
sudo ln -s /etc/nginx/sites-available/greenfield-api /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# Free Let's Encrypt cert + auto-configures nginx for HTTPS + sets up renewal
sudo certbot --nginx -d api.<VM_IP>.sslip.io
```

Verify:
```
curl https://api.<VM_IP>.sslip.io/health
```

Certbot installs a systemd timer for automatic renewal — no further action needed.

### 6. GitHub repo configuration (for the SSH deploy path)

Add these secrets in the repo's Settings → Secrets and variables → Actions:

| Secret | Value |
|---|---|
| `DEPLOY_HOST` | `<VM_IP>` |
| `DEPLOY_USER` | `deploy` |
| `DEPLOY_SSH_KEY` | the private key generated above (`/tmp/deploy_key` contents) |

You'd then add a `deploy` job to `.github/workflows/deploy.yml` with an SSH-based step
(build+push to GHCR, then SSH in and run the `docker compose` commands above).

### 7. Cut over

Once the VM is verified working end to end, update the Vercel frontend's API URL to the new
`https://api.<VM_IP>.sslip.io` (or real domain), redeploy the frontend, confirm auth works, then
delete the Render service if no longer needed.
