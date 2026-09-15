# Replace TryCloudflare Tunnels with 2n6.me Domain Gateway

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace all Cloudflare tunnel usage with the 2n6.me domain gateway, using Caddy on VMs for automatic HTTPS via Let's Encrypt.

**Architecture:** Instead of installing `cloudflared` on each VM and getting a random `*.trycloudflare.com` URL, we now: (1) look up the instance's deterministic subdomain via the gateway API (`https://api.2n6.me/api/hash/{instance_hash}`), (2) install Caddy on the VM as a reverse proxy with automatic ACME cert provisioning for `subdomain.2n6.me`, and (3) return `https://subdomain.2n6.me` as the public URL. The gateway already routes `*.2n6.me` traffic to VMs via HAProxy SNI passthrough (port 443) and HTTP routing (port 80 for ACME challenges).

**Tech Stack:** Python/FastAPI (backend), Caddy (VM reverse proxy), 2n6.me gateway API (httpx), vanilla JS (frontend)

---

### Task 1: Replace `setup_tunnel` in `ssh_executor.py`

**Files:**
- Modify: `ssh_executor.py:247-290` (replace `setup_tunnel` method)

**Step 1: Replace the `setup_tunnel` method with `setup_caddy_proxy`**

The new method installs Caddy on the VM, writes a Caddyfile that reverse-proxies to `localhost:{port}`, and uses automatic HTTPS for the `subdomain.2n6.me` domain. The gateway routes port 80 to `[vm_ipv6]:80` for ACME challenges, and port 443 to `[vm_ipv6]:443` for TLS passthrough.

Replace the entire `setup_tunnel` method (lines 247-290) with:

```python
    async def setup_caddy_proxy(self, local_port: int, subdomain: str, domain: str = "2n6.me") -> dict:
        """Set up Caddy as a reverse proxy with automatic HTTPS for the 2n6.me domain"""
        result = {"status": "pending", "port": local_port, "subdomain": subdomain}
        fqdn = f"{subdomain}.{domain}"

        # Check if caddy is installed
        code, _, _ = await self.run_command("which caddy")
        if code != 0:
            # Install caddy
            install_cmd = (
                "apt-get update -qq && apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https curl && "
                "curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg && "
                "curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list && "
                "apt-get update -qq && apt-get install -y -qq caddy"
            )
            code, _, stderr = await self.run_command(install_cmd, timeout=120)
            if code != 0:
                result["status"] = "failed"
                result["error"] = f"Failed to install caddy: {stderr}"
                return result

        # Stop caddy if running (clean state)
        await self.run_command("systemctl stop caddy 2>/dev/null || true")

        # Write Caddyfile
        caddyfile_content = f"{fqdn} {{\n    reverse_proxy localhost:{local_port}\n}}\n"
        write_cmd = _safe_write_file_command(caddyfile_content, "/etc/caddy/Caddyfile")
        code, _, stderr = await self.run_command(write_cmd)
        if code != 0:
            result["status"] = "failed"
            result["error"] = f"Failed to write Caddyfile: {stderr}"
            return result

        # Start caddy
        code, _, stderr = await self.run_command("systemctl enable caddy && systemctl start caddy")
        if code != 0:
            result["status"] = "failed"
            result["error"] = f"Failed to start caddy: {stderr}"
            return result

        # Give Caddy a moment to obtain the certificate
        await asyncio.sleep(5)

        result["status"] = "running"
        result["url"] = f"https://{fqdn}"
        return result
```

**Step 2: Verify the change reads cleanly**

Ensure `_safe_write_file_command` is imported/available at the top of the class (it already is — defined at module level on line 31).

**Step 3: Commit**

```bash
git add ssh_executor.py
git commit -m "feat: replace cloudflare tunnel with caddy reverse proxy for 2n6.me"
```

---

### Task 2: Replace tunnel setup in `deployer.py`

**Files:**
- Modify: `deployer.py:507-534` (replace `setup_cloudflare_tunnel` method)

**Step 1: Replace `setup_cloudflare_tunnel` with `setup_caddy_proxy`**

This method generates a script (not executed directly — it's used in the manual/orchestrator flow). Replace lines 507-534:

```python
    async def setup_caddy_proxy(
        self,
        ssh_host: str,
        ssh_port: int,
        ssh_user: str,
        local_port: int,
        subdomain: str,
        domain: str = "2n6.me"
    ) -> dict:
        """Generate commands to set up Caddy reverse proxy with automatic HTTPS."""
        fqdn = f"{subdomain}.{domain}"
        tunnel_script = f'''#!/bin/bash
# Install Caddy if not present
if ! command -v caddy &> /dev/null; then
    apt-get update -qq
    apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https curl
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -qq && apt-get install -y -qq caddy
fi

# Write Caddyfile
cat > /etc/caddy/Caddyfile << 'CADDY_EOF'
{fqdn} {{
    reverse_proxy localhost:{local_port}
}}
CADDY_EOF

# Restart caddy to pick up new config
systemctl enable caddy
systemctl restart caddy

echo "Caddy configured for https://{fqdn}"
'''

        return {
            "status": "script_ready",
            "tunnel_script": tunnel_script,
            "url": f"https://{fqdn}",
            "note": "Run this after docker-compose is running. Caddy will auto-provision an HTTPS certificate."
        }
```

**Step 2: Update all callers of `setup_cloudflare_tunnel` in deployer.py**

In `DeploymentOrchestrator.deploy_app` (around line 592-603), the method calls `self.deployer.setup_cloudflare_tunnel(...)`. This needs updating to pass the subdomain. However, at this point in the orchestrator flow, we don't have the instance hash to derive a subdomain. This code path is for deploying to an **existing** instance where `ssh_info` is provided — the user would need to provide the instance hash too, or we skip the proxy setup for this flow.

For now, update the call to use the new method name and pass a placeholder — this manual flow can be enhanced later:

Change the `setup_cloudflare_tunnel` call in `deploy_app` (around line 593) to:

```python
            tunnel_result = await self.deployer.setup_caddy_proxy(
                ssh_host=ssh_info["host"],
                ssh_port=ssh_info.get("port", 22),
                ssh_user=ssh_info.get("user", "root"),
                local_port=tunnel_port,
                subdomain="manual",  # TODO: derive from instance hash when available
            )
```

Also update the call in `execute_deployment` in `main.py` (around line 419) — see Task 3.

**Step 3: Commit**

```bash
git add deployer.py
git commit -m "feat: replace cloudflare tunnel script with caddy proxy in deployer"
```

---

### Task 3: Update `main.py` — gateway API lookup + new tunnel flow

**Files:**
- Modify: `main.py:449-457` (no change needed to port detection)
- Modify: `main.py:464-558` (`_run_deploy_job` — add gateway lookup, replace tunnel step)
- Modify: `main.py:367-436` (`execute_deployment` — update cloudflare reference)

**Step 1: Add gateway API lookup helper at module level (after imports, around line 30)**

Add this constant and helper function near the top of `main.py`:

```python
GATEWAY_API_URL = "https://api.2n6.me"

async def lookup_instance_subdomain(instance_hash: str) -> Optional[str]:
    """Look up the 2n6.me subdomain for an instance via the gateway API"""
    if not instance_hash:
        return None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{GATEWAY_API_URL}/api/hash/{instance_hash}")
            if resp.status_code == 200:
                data = resp.json()
                return data.get("subdomain")
    except Exception as e:
        logging.getLogger("deploy").warning(f"Gateway lookup failed for {instance_hash}: {e}")
    return None
```

**Step 2: Update `_run_deploy_job` to use gateway + caddy instead of cloudflare**

In `_run_deploy_job` (line 520-530), replace the tunnel section:

Old code (lines 520-530):
```python
        # Set up tunnel
        if request.setup_tunnel:
            job["step"] = "tunnel"
            tunnel_port = request.tunnel_port
            if tunnel_port is None:
                tunnel_port = get_host_port_from_compose(app["docker_compose"])
            tunnel_result = await executor.setup_tunnel(tunnel_port)
            if tunnel_result.get("url"):
                deployment_tracker.update_deployment(deployment_id, public_url=tunnel_result["url"])
                job["public_url"] = tunnel_result["url"]
            job["tunnel"] = tunnel_result
```

New code:
```python
        # Set up public URL via 2n6.me gateway + Caddy
        if request.setup_tunnel:
            job["step"] = "tunnel"
            tunnel_port = request.tunnel_port
            if tunnel_port is None:
                tunnel_port = get_host_port_from_compose(app["docker_compose"])

            # Look up subdomain from gateway
            subdomain = await lookup_instance_subdomain(request.instance_hash)
            if subdomain:
                tunnel_result = await executor.setup_caddy_proxy(tunnel_port, subdomain)
                if tunnel_result.get("url"):
                    deployment_tracker.update_deployment(deployment_id, public_url=tunnel_result["url"])
                    job["public_url"] = tunnel_result["url"]
                job["tunnel"] = tunnel_result
            else:
                log.warning(f"Could not resolve subdomain for instance {request.instance_hash}")
                job["tunnel"] = {"status": "skipped", "reason": "No subdomain resolved from gateway"}
```

**Step 3: Update `execute_deployment` endpoint (line 419)**

Change `setup_cloudflare_tunnel` to `setup_caddy_proxy` and pass a subdomain:

```python
    tunnel_result = await deployer.setup_caddy_proxy(
        ssh_host=ssh_info.host,
        ssh_port=ssh_info.port,
        ssh_user=ssh_info.user,
        local_port=tunnel_port,
        subdomain="manual",  # TODO: derive from instance hash
    )
```

**Step 4: Commit**

```bash
git add main.py
git commit -m "feat: use 2n6.me gateway API for subdomain lookup and caddy for HTTPS"
```

---

### Task 4: Update the frontend deploy flow

**Files:**
- Modify: `dashboard_v2.py` (the `DASHBOARD_HTML` string — deployment steps and labels)

**Step 1: Update step labels in `startDeploy()`**

In the step definitions (around the `steps` array in `startDeploy()`), change the tunnel step label:

Old:
```javascript
{ id: 'step-deploy', title: 'Deploy Application', desc: 'Installing app via SSH...' },
```

No change needed here — "Deploy Application" is still accurate.

In the polling `stepLabels` object, change:

Old:
```javascript
tunnel: 'Setting up public URL...',
```

New:
```javascript
tunnel: 'Setting up HTTPS reverse proxy...',
```

**Step 2: Update the success panel URL display**

The success panel already displays `deployData.public_url` generically — no change needed since the URL format will just change from `https://xxx.trycloudflare.com` to `https://words-words-words-words.2n6.me`. The display code is already generic.

**Step 3: Update the deploy request to NOT send `setup_tunnel: true` if no instance hash**

Currently the frontend always sends `setup_tunnel: true`. This is still correct since the backend now checks for the instance hash before attempting the caddy setup. No change needed.

**Step 4: Commit**

```bash
git add dashboard_v2.py
git commit -m "feat: update frontend labels for caddy/2n6.me proxy setup"
```

---

### Task 5: Remove all cloudflare/cloudflared references

**Files:**
- Modify: `ssh_executor.py` — remove old `setup_tunnel` if not already replaced in Task 1
- Modify: `deployer.py` — remove old `setup_cloudflare_tunnel` if not already replaced in Task 2
- Modify: `CLAUDE.md` — update architecture description

**Step 1: Search for any remaining cloudflare references**

Run: `grep -rn -i 'cloudflare\|cloudflared\|trycloudflare' --include='*.py' --include='*.html' --include='*.md' .`

Remove or update any stale references found.

**Step 2: Update `CLAUDE.md`**

In the "Key Deploy Flow" section, change step 6 from:
```
6. Installs cloudflared, creates tunnel, extracts public URL
```
to:
```
6. Looks up 2n6.me subdomain via gateway API, installs Caddy reverse proxy with auto-HTTPS
```

In the "Important Patterns" section, add:
```
- **2n6.me domain gateway**: Each instance gets a deterministic subdomain (4 BIP-39 words derived from the instance hash). The gateway at api.2n6.me routes `*.2n6.me` traffic to VMs via HAProxy SNI passthrough. Caddy on the VM handles HTTPS cert provisioning via Let's Encrypt.
```

**Step 3: Commit**

```bash
git add -A
git commit -m "chore: remove all cloudflare references, update docs for 2n6.me"
```

---

### Task 6: Test the full flow manually

**Step 1: Start the app locally**

```bash
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8002
```

**Step 2: Verify the gateway API is reachable**

```bash
curl https://api.2n6.me/api/status
```

Expected: JSON with instance_count, route_count, domain: "2n6.me"

**Step 3: Test subdomain lookup with a known instance hash**

```bash
curl https://api.2n6.me/api/hash/<some-instance-hash>
```

Expected: JSON with subdomain, url, active fields

**Step 4: Verify no cloudflare references remain**

```bash
grep -rn -i 'cloudflare\|cloudflared\|trycloudflare' --include='*.py' --include='*.html' --include='*.md' .
```

Expected: No matches (or only this plan doc)

**Step 5: Commit final state**

```bash
git add -A
git commit -m "feat: complete migration from cloudflare tunnels to 2n6.me gateway with caddy"
```
