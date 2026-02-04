# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

Aleph Cloud Marketplace — a one-click app deployment platform for Aleph Cloud decentralized infrastructure. Users connect an Ethereum wallet, pick a pre-configured app (WordPress, Gitea, etc.), and the system creates an Aleph Cloud VM, SSHes in, deploys docker-compose, sets up a Cloudflare tunnel, and returns access details.

## Running Locally

```bash
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8002
# Access at http://localhost:8002
```

No tests, linting, or CI exist yet.

## Production Deployment

The app runs on an Aleph Cloud VM itself:

```bash
ssh -p 24003 root@213.246.39.151
# Code lives at /root/aleph-marketplace/
# Restart after changes:
kill $(pgrep -f 'python3 main.py')
cd /root/aleph-marketplace && nohup python3 main.py > /tmp/marketplace.log 2>&1 &
```

Server runs uvicorn on port 8002 behind a Cloudflare tunnel.

## Architecture

Two Python files + one HTML SPA. No database — all state is in-memory dicts.

**main.py** — FastAPI app. Handles:
- Web3 auth (nonce-sign-verify flow with eth_account, session tokens with 24h expiry)
- REST API for credits, SSH keys, app catalog, deployments
- Serves the dashboard HTML
- Launches background tasks for long-running deployments

**deployer.py** — Two classes:
- `AlephDeployer`: Low-level operations — instance creation via aleph-sdk-python, VM IP polling (scheduler + CRN APIs), SSH command execution, docker-compose deployment, Cloudflare tunnel setup, marketplace key cleanup
- `DeploymentOrchestrator`: High-level state machine that chains AlephDeployer operations into a full deploy flow, runs as a background task

**templates/dashboard.html** — Vanilla HTML/JS SPA with ethers.js for wallet connection. Handles wallet auth, app browsing, SSH key selection, deployment initiation, and real-time status polling.

**templates/apps.json** — App catalog. Each entry has an id, resource requirements (vcpus, memory_mb, disk_gb), embedded docker_compose YAML, and estimated daily cost.

## Key Deploy Flow

1. Frontend: wallet connect -> nonce -> sign -> verify -> session token
2. `POST /api/deploy` with app_id + ssh_key -> creates Aleph instance via SDK (injects user key + marketplace key)
3. Background task: polls scheduler/CRN for VM IP (30 attempts, 10s apart)
4. SSHes into VM with marketplace private key (`/root/.ssh/id_rsa`)
5. Writes docker-compose.yml, pulls images, starts containers
6. Installs cloudflared, creates tunnel, extracts public URL
7. Removes marketplace SSH key from VM's authorized_keys
8. Frontend polls `GET /api/deployments/{id}` every 5s for status updates

## Important Patterns

- **aleph-sdk-python is optional**: deployer.py gracefully handles its absence with try/except imports and falls back to manual instructions
- **In-memory state**: `deployments` dict in main.py, `sessions`/`nonces` dicts for auth. Nothing persists across restarts.
- **SSH key security**: marketplace key is injected for automated deployment, then explicitly removed via `sed -i` after deployment completes
- **Async throughout**: FastAPI async handlers, asyncio.create_subprocess_exec for SSH, httpx.AsyncClient for API calls, BackgroundTasks for polling
- **CRN API version handling**: deployer.py tries v2 endpoint first (`/v2/about/executions/list`), falls back to v1 (`/about/executions/list`)

## Adding a New App

Add an entry to `templates/apps.json` in the `apps` array with: id, name, description, category, icon, tags, requirements (vcpus/memory_mb/disk_gb), docker_compose (embedded YAML string), and estimated_cost_per_day. The frontend renders it automatically.

## External APIs

- Scheduler: `https://scheduler.api.aleph.cloud`
- Aleph API: `https://api2.aleph.im/api/v0`
- CRN list: `https://crns-list.aleph.sh/crns.json`
- SSH keys fetched from Aleph network posts (type=ALEPH-SSH, channel=ALEPH-CLOUDSOLUTIONS)
