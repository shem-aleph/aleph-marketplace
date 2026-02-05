"""
SSH Executor - Actually runs commands on remote instances
Uses asyncio subprocess for SSH execution
"""
import asyncio
import logging
import json
import os
import base64
import shlex
import secrets
from typing import Optional, Tuple
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)


def _sanitize_app_name(app_name: str) -> str:
    """Sanitize app name to prevent command injection and path traversal"""
    import re
    if not app_name:
        raise ValueError("App name cannot be empty")
    if not re.match(r'^[a-zA-Z0-9_-]+$', app_name):
        raise ValueError(f"Invalid app name: '{app_name}'")
    if len(app_name) > 64:
        raise ValueError("App name too long")
    return app_name


def _safe_write_file_command(content: str, filepath: str) -> str:
    """Generate a safe command to write file content using base64"""
    encoded = base64.b64encode(content.encode()).decode()
    safe_path = shlex.quote(filepath)
    return f"echo '{encoded}' | base64 -d > {safe_path}"


class SSHExecutor:
    """Execute commands on remote instances via SSH"""
    
    def __init__(self, host: str, port: int = 22, user: str = "root", key_path: Optional[str] = None):
        self.host = host
        self.port = port
        self.user = user
        self.key_path = key_path or os.path.expanduser("~/.ssh/id_rsa")
    
    async def run_command(self, command: str, timeout: int = 120) -> Tuple[int, str, str]:
        """
        Run a command on the remote host via SSH.
        
        Returns:
            Tuple of (return_code, stdout, stderr)
        """
        ssh_cmd = [
            "ssh",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "ConnectTimeout=10",
            "-p", str(self.port),
        ]
        
        if self.key_path and os.path.exists(self.key_path):
            ssh_cmd.extend(["-i", self.key_path])
        
        ssh_cmd.append(f"{self.user}@{self.host}")
        ssh_cmd.append(command)
        
        try:
            process = await asyncio.create_subprocess_exec(
                *ssh_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout
            )
            
            return (
                process.returncode or 0,
                stdout.decode('utf-8', errors='replace'),
                stderr.decode('utf-8', errors='replace')
            )
        except asyncio.TimeoutError:
            logger.error(f"SSH command timed out after {timeout}s")
            return (124, "", f"Command timed out after {timeout} seconds")
        except Exception as e:
            logger.error(f"SSH execution error: {e}")
            return (1, "", str(e))
    
    async def test_connection(self) -> bool:
        """Test if SSH connection works"""
        code, stdout, stderr = await self.run_command("echo connected", timeout=15)
        return code == 0 and "connected" in stdout
    
    async def check_docker(self) -> bool:
        """Check if Docker is installed"""
        code, stdout, _ = await self.run_command("docker --version", timeout=15)
        return code == 0
    
    async def install_docker(self) -> Tuple[bool, str]:
        """Install Docker on the remote host"""
        code, stdout, stderr = await self.run_command(
            "curl -fsSL https://get.docker.com | sh",
            timeout=300  # Docker install can take a while
        )
        if code == 0:
            return True, "Docker installed successfully"
        return False, f"Docker installation failed: {stderr}"
    
    async def deploy_compose(self, app_name: str, compose_content: str) -> dict:
        """Deploy a docker-compose application"""
        # SECURITY: Sanitize app name to prevent command injection
        try:
            safe_app_name = _sanitize_app_name(app_name)
        except ValueError as e:
            return {
                "status": "failed",
                "error": str(e),
                "steps": []
            }

        # Generate random passwords to replace placeholder tokens
        generated_passwords = {}
        if "__GENERATED_PASSWORD__" in compose_content:
            password = secrets.token_urlsafe(16)
            compose_content = compose_content.replace("__GENERATED_PASSWORD__", password)
            generated_passwords["password"] = password
        if "__GENERATED_ROOT_PASSWORD__" in compose_content:
            root_password = secrets.token_urlsafe(16)
            compose_content = compose_content.replace("__GENERATED_ROOT_PASSWORD__", root_password)
            generated_passwords["root_password"] = root_password

        result = {
            "status": "pending",
            "steps": [],
            "app_name": safe_app_name
        }

        if generated_passwords:
            result["generated_passwords"] = generated_passwords
        
        # Step 1: Create app directory (using shlex.quote for safety)
        safe_dir = shlex.quote(f"/root/apps/{safe_app_name}")
        code, _, stderr = await self.run_command(f"mkdir -p {safe_dir}")
        result["steps"].append({
            "step": "create_directory",
            "success": code == 0,
            "error": stderr if code != 0 else None
        })
        if code != 0:
            result["status"] = "failed"
            result["error"] = f"Failed to create directory: {stderr}"
            return result
        
        # Step 2: Write docker-compose.yml
        # SECURITY: Use base64 encoding to prevent any injection
        compose_path = f"/root/apps/{safe_app_name}/docker-compose.yml"
        write_cmd = _safe_write_file_command(compose_content, compose_path)
        code, _, stderr = await self.run_command(write_cmd)
        result["steps"].append({
            "step": "write_compose",
            "success": code == 0,
            "error": stderr if code != 0 else None
        })
        if code != 0:
            result["status"] = "failed"
            result["error"] = f"Failed to write compose file: {stderr}"
            return result

        # Step 2b: Write supporting config files if needed
        if "prometheus" in safe_app_name or "grafana" in safe_app_name:
            prometheus_config = (
                "global:\n"
                "  scrape_interval: 15s\n"
                "\n"
                "scrape_configs:\n"
                "  - job_name: 'prometheus'\n"
                "    static_configs:\n"
                "      - targets: ['localhost:9090']\n"
            )
            prom_path = f"/root/apps/{safe_app_name}/prometheus.yml"
            prom_cmd = _safe_write_file_command(prometheus_config, prom_path)
            code, _, stderr = await self.run_command(prom_cmd)
            result["steps"].append({
                "step": "write_prometheus_config",
                "success": code == 0,
                "error": stderr if code != 0 else None
            })
            if code != 0:
                result["status"] = "failed"
                result["error"] = f"Failed to write prometheus.yml: {stderr}"
                return result

        # Step 3: Check/Install Docker
        if not await self.check_docker():
            result["steps"].append({"step": "docker_check", "success": False, "installing": True})
            success, msg = await self.install_docker()
            result["steps"].append({
                "step": "docker_install",
                "success": success,
                "message": msg
            })
            if not success:
                result["status"] = "failed"
                result["error"] = msg
                return result
        else:
            result["steps"].append({"step": "docker_check", "success": True})
        
        # Step 4: Pull and start containers
        code, stdout, stderr = await self.run_command(
            f"cd {safe_dir} && docker compose pull && docker compose up -d",
            timeout=300
        )
        result["steps"].append({
            "step": "docker_compose_up",
            "success": code == 0,
            "output": stdout[:500] if stdout else None,
            "error": stderr if code != 0 else None
        })
        if code != 0:
            result["status"] = "failed"
            result["error"] = f"Failed to start containers: {stderr}"
            return result
        
        # Step 5: Get container status
        code, stdout, _ = await self.run_command(
            f"cd {safe_dir} && docker compose ps --format json"
        )
        if code == 0 and stdout.strip():
            try:
                # Handle multiple JSON objects (one per line)
                containers = []
                for line in stdout.strip().split('\n'):
                    if line.strip():
                        containers.append(json.loads(line))
                result["containers"] = containers
            except json.JSONDecodeError:
                result["containers_raw"] = stdout
        
        result["status"] = "running"
        result["app_directory"] = f"/root/apps/{safe_app_name}"
        return result
    
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
    
    async def get_app_status(self, app_name: str) -> dict:
        """Get status of a deployed app"""
        # SECURITY: Sanitize app name
        try:
            safe_app_name = _sanitize_app_name(app_name)
        except ValueError as e:
            return {"app_name": app_name, "status": "error", "error": str(e)}
        
        result = {"app_name": safe_app_name, "status": "unknown"}
        safe_dir = shlex.quote(f"/root/apps/{safe_app_name}")
        
        # Check if directory exists
        code, _, _ = await self.run_command(f"test -d {safe_dir}")
        if code != 0:
            result["status"] = "not_found"
            return result
        
        # Get container status
        code, stdout, _ = await self.run_command(
            f"cd {safe_dir} && docker compose ps --format json 2>/dev/null"
        )
        
        if code == 0 and stdout.strip():
            try:
                containers = []
                for line in stdout.strip().split('\n'):
                    if line.strip():
                        containers.append(json.loads(line))
                result["containers"] = containers
                
                # Determine overall status
                running = all(c.get("State") == "running" for c in containers)
                result["status"] = "running" if running else "degraded"
            except json.JSONDecodeError:
                result["status"] = "unknown"
                result["raw_output"] = stdout
        else:
            result["status"] = "stopped"
        
        return result
    
    async def stop_app(self, app_name: str) -> dict:
        """Stop a deployed app"""
        # SECURITY: Sanitize app name
        try:
            safe_app_name = _sanitize_app_name(app_name)
        except ValueError as e:
            return {"status": "error", "error": str(e)}
        
        safe_dir = shlex.quote(f"/root/apps/{safe_app_name}")
        code, stdout, stderr = await self.run_command(
            f"cd {safe_dir} && docker compose down"
        )
        return {
            "status": "stopped" if code == 0 else "failed",
            "output": stdout,
            "error": stderr if code != 0 else None
        }
    
    async def remove_app(self, app_name: str) -> dict:
        """Remove a deployed app completely"""
        # SECURITY: Sanitize app name
        try:
            safe_app_name = _sanitize_app_name(app_name)
        except ValueError as e:
            return {"status": "error", "error": str(e)}
        
        safe_dir = shlex.quote(f"/root/apps/{safe_app_name}")
        
        # Stop containers
        await self.run_command(f"cd {safe_dir} && docker compose down -v 2>/dev/null")
        
        # Remove directory (safe because we sanitized the name)
        code, _, stderr = await self.run_command(f"rm -rf {safe_dir}")
        
        return {
            "status": "removed" if code == 0 else "failed",
            "error": stderr if code != 0 else None
        }


class DeploymentTracker:
    """Track deployments with persistence"""
    
    def __init__(self, storage_path: str = "/tmp/marketplace_deployments.json"):
        self.storage_path = Path(storage_path)
        self.deployments = self._load()
    
    def _load(self) -> dict:
        """Load deployments from disk"""
        if self.storage_path.exists():
            try:
                with open(self.storage_path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {}
    
    def _save(self):
        """Save deployments to disk"""
        with open(self.storage_path, 'w') as f:
            json.dump(self.deployments, f, indent=2, default=str)
    
    def add_deployment(
        self,
        deployment_id: str,
        address: str,
        app_id: str,
        app_name: str,
        ssh_host: str,
        ssh_port: int,
        status: str = "deploying"
    ) -> dict:
        """Record a new deployment"""
        deployment = {
            "id": deployment_id,
            "address": address.lower(),
            "app_id": app_id,
            "app_name": app_name,
            "ssh_host": ssh_host,
            "ssh_port": ssh_port,
            "status": status,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
            "public_url": None,
        }
        self.deployments[deployment_id] = deployment
        self._save()
        return deployment
    
    def update_deployment(self, deployment_id: str, **updates) -> Optional[dict]:
        """Update a deployment"""
        if deployment_id not in self.deployments:
            return None
        
        self.deployments[deployment_id].update(updates)
        self.deployments[deployment_id]["updated_at"] = datetime.utcnow().isoformat()
        self._save()
        return self.deployments[deployment_id]
    
    def get_deployment(self, deployment_id: str) -> Optional[dict]:
        """Get a deployment by ID"""
        return self.deployments.get(deployment_id)
    
    def get_deployments_by_address(self, address: str) -> list:
        """Get all deployments for an address"""
        address = address.lower()
        return [d for d in self.deployments.values() if d["address"] == address]
    
    def get_all_deployments(self) -> list:
        """Get all deployments"""
        return list(self.deployments.values())
    
    def remove_deployment(self, deployment_id: str) -> bool:
        """Remove a deployment record"""
        if deployment_id in self.deployments:
            del self.deployments[deployment_id]
            self._save()
            return True
        return False
