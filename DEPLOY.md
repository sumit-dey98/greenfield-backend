# Production Deployment Guide

One-time manual setup for hosting greenfield-backend in production. After this is done once,
every push to `main` auto-deploys via GitHub Actions (see `.github/workflows/deploy.yml`).

Stack: Oracle Cloud Free Tier VM (Ubuntu) + Docker + nginx + Let's Encrypt (via sslip.io) +
Neon (managed Postgres) + GitHub Container Registry (GHCR).

## 1. Neon (managed Postgres)

1. Create a free account at neon.tech, create a project (e.g. `greenfield-prod`).
2. Copy the **pooled** connection string (uses their PgBouncer endpoint, has `-pooler` in the
   hostname) — this is what `DATABASE_URL` should be in production, not the direct endpoint.
3. Locally (or from any machine with network access), run migrations once against it:
   ```
   DATABASE_URL="<neon-pooled-url>" alembic upgrade head
   ```
4. Confirm tables exist via the Neon SQL editor or `psql`.

## 2. Oracle Cloud Free Tier VM

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

### Install Docker + nginx + certbot

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

### Create a dedicated deploy user (used by GitHub Actions, not your personal login)

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

### First-time app deploy (as the `deploy` user)

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

Log in to GHCR (needed once to pull the private package) and start the app:
```
echo "<a GitHub Personal Access Token with read:packages>" | docker login ghcr.io -u sumit-dey98 --password-stdin
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml exec api alembic upgrade head
```

The API is now listening on `127.0.0.1:8000` on the VM (not yet publicly reachable — that's nginx's job next).

## 3. nginx reverse proxy + free HTTPS via sslip.io

No domain is owned, so we use `sslip.io`, a free wildcard DNS service: any hostname of the form
`<anything>.<VM_IP>.sslip.io` automatically resolves to `<VM_IP>`. We'll use
`api.<VM_IP>.sslip.io` (dots in the IP work fine as DNS labels) as the public hostname.

Exit back to your normal sudo user, then create the nginx site:

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
Should return `{"db":"connected","students":<N>}`.

Certbot installs a systemd timer for automatic renewal — no further action needed.

## 4. GitHub repo configuration

In the repo's Settings → Secrets and variables → Actions, add:

| Secret | Value |
|---|---|
| `DEPLOY_HOST` | `<VM_IP>` |
| `DEPLOY_USER` | `deploy` |
| `DEPLOY_SSH_KEY` | the private key generated above (`/tmp/deploy_key` contents) |

`GITHUB_TOKEN` is provided automatically by Actions — no setup needed for GHCR push/pull from
the CI job. The `docker login` inside the SSH deploy script reuses that same token to let the
VM pull the (private-by-default) GHCR image.

## 5. Ongoing deploys

Every push to `main` now:
1. Builds and compile-checks the image.
2. Pushes it to `ghcr.io/sumit-dey98/greenfield-backend:latest`.
3. SSHs into the VM, pulls the new image, recreates the container, and runs
   `alembic upgrade head`.

To deploy manually if needed, SSH in as `deploy` and run the same three `docker compose`
commands shown in step 2 above.

## 6. Frontend (Vercel) update

Update the frontend's API base URL environment variable on Vercel to
`https://api.<VM_IP>.sslip.io`, redeploy the frontend, and confirm login/auth works end to end.
