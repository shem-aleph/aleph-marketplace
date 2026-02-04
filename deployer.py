"""
Aleph Cloud Deployer - Handles actual instance creation and app deployment

Uses aleph-sdk-python for programmatic instance creation with the credits payment model.
Includes automated VM IP retrieval and SSH-based deployment execution.
"""
import asyncio
import json
import logging
import os
import subprocess
import tempfile
from typing import Optional, Any
from pathlib import Path

import httpx

# Aleph SDK imports
try:
    from aleph.sdk import AlephHttpClient, AuthenticatedAlephHttpClient
    from aleph.sdk.chains.ethereum import ETHAccount
    from aleph.sdk.client.vm_client import VmClient
    from aleph.sdk.conf import settings as aleph_settings
    from aleph.sdk.types import StorageEnum
    from aleph_message.models import Chain
    from aleph_message.models.execution.base import Payment, PaymentType
    from aleph_message.models.execution.environment import HypervisorType
    ALEPH_SDK_AVAILABLE = True
except ImportError:
    ALEPH_SDK_AVAILABLE = False
    logging.warning("aleph-sdk-python not installed. SDK-based instance creation unavailable.")

logger = logging.getLogger(__name__)

# Default rootfs images available on Aleph
ROOTFS_IMAGES = {
    "ubuntu22": "887957042bb0e360da3485ed33175882571f0b716d31e9fce8fb984c48fa77fb",  # Ubuntu 22.04
    "ubuntu24": "77fef271aa6ff9825efa3186ca2e715d19e7108279b817201c69c34cedc74c27",  # Ubuntu 24.04
    "debian12": "6e30de68c6cedfa6b45240c2b51e52495ac6fb1888c60c6e6c7b5ee3d3a8c47e",  # Debian 12
}

# Scheduler API
SCHEDULER_URL = "https://scheduler.api.aleph.cloud"
ALEPH_API_URL = "https://api2.aleph.im/api/v0"

# Marketplace deployment SSH key paths
MARKETPLACE_SSH_PRIVATE_KEY = "/root/.ssh/id_rsa"
MARKETPLACE_SSH_PUBLIC_KEY = "/root/.ssh/id_rsa.pub"


def _read_marketplace_pubkey() -> Optional[str]:
    """Read the marketplace server's SSH public key for injection into VMs."""
    try:
        with open(MARKETPLACE_SSH_PUBLIC_KEY, "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        logger.warning(f"Marketplace SSH public key not found at {MARKETPLACE_SSH_PUBLIC_KEY}")
        return None


class AlephDeployer:
    """Handles deployment of apps to Aleph Cloud instances using SDK"""
    
    API_URL = ALEPH_API_URL
    
    def __init__(self, private_key: Optional[str] = None):
        self.private_key = private_key
        self._account = None
        
        if private_key and ALEPH_SDK_AVAILABLE:
            self._account = self._load_account(private_key)
    
    def _load_account(self, private_key: str) -> Optional["ETHAccount"]:
        if not ALEPH_SDK_AVAILABLE:
            return None
        if private_key.startswith("0x"):
            private_key = private_key[2:]
        try:
            pk_bytes = bytes.fromhex(private_key)
            return ETHAccount(private_key=pk_bytes)
        except Exception as e:
            logger.error(f"Failed to load account: {e}")
            return None
    
    def _build_ssh_keys(self, user_pubkey: str) -> list[str]:
        """Build SSH keys list: user key + marketplace deployment key."""
        keys = [user_pubkey]
        marketplace_key = _read_marketplace_pubkey()
        if marketplace_key:
            keys.append(marketplace_key)
            logger.info("Injecting marketplace deployment key for automated deployment")
        else:
            logger.warning("Marketplace deployment key not found - SSH deployment may fail")
        return keys
    
    async def remove_marketplace_key_from_vm(
        self,
        ssh_host: str,
        ssh_port: int,
        ssh_user: str = "root",
    ) -> dict:
        """Remove the marketplace's public key from the VM's authorized_keys after deployment."""
        marketplace_key = _read_marketplace_pubkey()
        if not marketplace_key:
            return {"status": "skipped", "reason": "No marketplace key to remove"}
        
        # Extract just the key data (type + base64) without the comment for matching
        key_parts = marketplace_key.split()
        if len(key_parts) >= 2:
            # Match on the key type and base64 data (not the comment)
            key_pattern = f"{key_parts[0]} {key_parts[1]}"
        else:
            key_pattern = marketplace_key
        
        # Escape special characters for sed
        escaped_key = key_pattern.replace("/", "\\/").replace("+", "\\+")
        
        remove_cmd = f"sed -i '/{escaped_key}/d' ~/.ssh/authorized_keys"
        
        result = await self.execute_ssh_command(
            ssh_host=ssh_host,
            ssh_port=ssh_port,
            ssh_user=ssh_user,
            command=remove_cmd,
            ssh_key_path=MARKETPLACE_SSH_PRIVATE_KEY,
            timeout=30,
        )
        
        if result.get("status") == "success":
            logger.info("Successfully removed marketplace deployment key from VM")
        else:
            logger.warning(f"Failed to remove marketplace key from VM: {result}")
        
        return result
    
    @property
    def address(self) -> Optional[str]:
        if self._account:
            return self._account.get_address()
        return None
    
    async def check_credits(self, address: str) -> dict:
        """Check credit balance for an address using the working Aleph API."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{ALEPH_API_URL}/addresses/{address}/balance"
                )
                if response.status_code == 200:
                    data = response.json()
                    return {
                        "balance": data.get("balance", 0),
                        "credit_balance": data.get("credit_balance", 0),
                        "locked_amount": data.get("locked_amount", 0),
                    }
        except Exception as e:
            logger.warning(f"Failed to fetch credits balance: {e}")
        return {"balance": "unknown", "credit_balance": "unknown", "note": "Could not fetch balance"}
    
    async def get_allocation(self, instance_hash: str) -> Optional[dict]:
        """
        Get VM allocation info from the scheduler.
        Returns node info and VM IPv6 if allocated.
        """
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    f"{SCHEDULER_URL}/api/v0/allocation/{instance_hash}"
                )
                if response.status_code == 200:
                    data = response.json()
                    return {
                        "vm_hash": data.get("vm_hash"),
                        "vm_type": data.get("vm_type"),
                        "vm_ipv6": data.get("vm_ipv6"),
                        "node": data.get("node", {}),
                        "period": data.get("period", {}),
                    }
        except Exception as e:
            logger.warning(f"Failed to fetch allocation: {e}")
        return None
    
    async def get_vm_networking_from_crn(self, crn_url: str, instance_hash: str) -> Optional[dict]:
        """
        Query the CRN directly for VM networking info (IPv4, IPv6, mapped ports).
        Tries v2 endpoint first, falls back to v1.
        """
        crn_url = crn_url.rstrip("/")
        if not crn_url.startswith("http"):
            crn_url = f"https://{crn_url}"
        
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Try v2 first
            for endpoint in ["/v2/about/executions/list", "/about/executions/list"]:
                try:
                    response = await client.get(f"{crn_url}{endpoint}")
                    if response.status_code == 200:
                        data = response.json()
                        # data is a dict keyed by vm_hash
                        vm_info = data.get(instance_hash)
                        if vm_info:
                            networking = vm_info.get("networking", {})
                            return {
                                "ipv4_network": networking.get("ipv4_network"),
                                "host_ipv4": networking.get("host_ipv4"),
                                "ipv6_network": networking.get("ipv6_network"),
                                "ipv6_ip": networking.get("ipv6_ip", networking.get("ipv6")),
                                "mapped_ports": networking.get("mapped_ports", {}),
                            }
                except Exception as e:
                    logger.debug(f"CRN query {endpoint} failed: {e}")
                    continue
        return None

    async def poll_for_vm_ip(
        self,
        instance_hash: str,
        crn_url: Optional[str] = None,
        max_attempts: int = 30,
        interval_seconds: int = 10,
    ) -> dict:
        """
        Poll the scheduler and CRN to retrieve the VM's IP address after creation.
        
        Returns dict with IPv4/IPv6 info and SSH connection details.
        Polls for up to max_attempts * interval_seconds (default 5 min).
        """
        result = {
            "status": "polling",
            "instance_hash": instance_hash,
            "ipv6": None,
            "ipv4": None,
            "ssh_host": None,
            "ssh_port": None,
            "mapped_ports": {},
        }
        
        for attempt in range(max_attempts):
            logger.info(f"Polling for VM IP (attempt {attempt + 1}/{max_attempts})...")
            
            # Check scheduler allocation
            allocation = await self.get_allocation(instance_hash)
            if allocation:
                result["ipv6"] = allocation.get("vm_ipv6")
                node = allocation.get("node", {})
                crn_url_from_alloc = node.get("url") or node.get("address")
                if crn_url_from_alloc:
                    crn_url = crn_url_from_alloc
            
            # Query CRN directly for full networking
            if crn_url:
                networking = await self.get_vm_networking_from_crn(crn_url, instance_hash)
                if networking:
                    result["ipv4"] = networking.get("host_ipv4")
                    result["ipv6"] = networking.get("ipv6_ip") or result["ipv6"]
                    result["mapped_ports"] = networking.get("mapped_ports", {})
                    
                    # Determine SSH connection info
                    ssh_port_info = result["mapped_ports"].get("22")
                    if ssh_port_info:
                        result["ssh_port"] = ssh_port_info.get("host") or ssh_port_info
                        result["ssh_host"] = result["ipv4"]
                    elif result["ipv6"]:
                        result["ssh_host"] = result["ipv6"]
                        result["ssh_port"] = 22
                    elif result["ipv4"]:
                        result["ssh_host"] = result["ipv4"]
                        result["ssh_port"] = 22
                    
                    if result["ssh_host"]:
                        result["status"] = "ready"
                        return result
            
            # If we have IPv6 from scheduler, try SSH on it
            if result["ipv6"] and not result["ssh_host"]:
                result["ssh_host"] = result["ipv6"]
                result["ssh_port"] = 22
                result["status"] = "ready"
                return result
            
            if attempt < max_attempts - 1:
                await asyncio.sleep(interval_seconds)
        
        result["status"] = "timeout"
        return result
    
    async def execute_ssh_command(
        self,
        ssh_host: str,
        ssh_port: int,
        ssh_user: str,
        command: str,
        ssh_key_path: Optional[str] = None,
        timeout: int = 300,
    ) -> dict:
        """
        Execute a command on a remote host via SSH.
        Uses subprocess for actual execution. The VM must have ALLOW_INTERNAL_SSH=1.
        """
        # Default to marketplace deployment key
        if ssh_key_path is None:
            ssh_key_path = MARKETPLACE_SSH_PRIVATE_KEY
        
        ssh_args = [
            "ssh",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "ConnectTimeout=30",
            "-p", str(ssh_port),
        ]
        
        if ssh_key_path:
            ssh_args.extend(["-i", ssh_key_path])
        
        ssh_args.append(f"{ssh_user}@{ssh_host}")
        ssh_args.append(command)
        
        try:
            proc = await asyncio.create_subprocess_exec(
                *ssh_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
            
            return {
                "status": "success" if proc.returncode == 0 else "error",
                "return_code": proc.returncode,
                "stdout": stdout.decode("utf-8", errors="replace")[-2000:],  # Last 2000 chars
                "stderr": stderr.decode("utf-8", errors="replace")[-1000:],
            }
        except asyncio.TimeoutError:
            return {"status": "timeout", "error": f"SSH command timed out after {timeout}s"}
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
    async def deploy_docker_compose_via_ssh(
        self,
        ssh_host: str,
        ssh_port: int,
        ssh_user: str,
        compose_content: str,
        app_name: str,
        ssh_key_path: Optional[str] = None,
    ) -> dict:
        """
        Deploy a docker-compose app by actually SSHing into the instance.
        """
        # Escape compose content for heredoc
        escaped_compose = compose_content.replace("'", "'\\''")
        
        deploy_script = f"""#!/bin/bash
set -e

echo "=== Creating app directory ==="
mkdir -p /root/apps/{app_name}
cd /root/apps/{app_name}

echo "=== Writing docker-compose.yml ==="
cat > docker-compose.yml << 'COMPOSE_EOF'
{compose_content}
COMPOSE_EOF

echo "=== Checking Docker ==="
if ! command -v docker &> /dev/null; then
    echo "Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
fi

echo "=== Pulling images ==="
docker compose pull

echo "=== Starting application ==="
docker compose up -d

echo "=== Status ==="
docker compose ps

echo "=== DEPLOY_SUCCESS ==="
"""
        
        result = await self.execute_ssh_command(
            ssh_host=ssh_host,
            ssh_port=ssh_port,
            ssh_user=ssh_user,
            command=deploy_script,
            ssh_key_path=ssh_key_path,
            timeout=600,  # 10 min for docker pull
        )
        
        result["app_name"] = app_name
        result["app_directory"] = f"/root/apps/{app_name}"
        result["deployed"] = "DEPLOY_SUCCESS" in result.get("stdout", "")
        
        return result
    
    async def setup_cloudflare_tunnel_via_ssh(
        self,
        ssh_host: str,
        ssh_port: int,
        ssh_user: str,
        local_port: int,
        ssh_key_path: Optional[str] = None,
    ) -> dict:
        """
        Set up a Cloudflare quick tunnel via SSH and return the public URL.
        """
        tunnel_script = f"""#!/bin/bash
set -e

# Install cloudflared if not present
if ! command -v cloudflared &> /dev/null; then
    echo "Installing cloudflared..."
    curl -sL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared
    chmod +x /usr/local/bin/cloudflared
fi

# Kill any existing tunnel
pkill -f "cloudflared tunnel" 2>/dev/null || true
sleep 1

# Start tunnel in background
nohup cloudflared tunnel --url http://localhost:{local_port} > /tmp/tunnel-{local_port}.log 2>&1 &
TUNNEL_PID=$!

# Wait for URL to appear (up to 30 seconds)
for i in $(seq 1 30); do
    URL=$(grep -o 'https://[a-z0-9-]*\\.trycloudflare\\.com' /tmp/tunnel-{local_port}.log 2>/dev/null | head -1)
    if [ -n "$URL" ]; then
        echo "TUNNEL_URL=$URL"
        echo "TUNNEL_PID=$TUNNEL_PID"
        exit 0
    fi
    sleep 1
done

echo "TUNNEL_TIMEOUT"
cat /tmp/tunnel-{local_port}.log
exit 1
"""
        
        result = await self.execute_ssh_command(
            ssh_host=ssh_host,
            ssh_port=ssh_port,
            ssh_user=ssh_user,
            command=tunnel_script,
            ssh_key_path=ssh_key_path,
            timeout=60,
        )
        
        # Extract tunnel URL from output
        stdout = result.get("stdout", "")
        for line in stdout.split("\n"):
            if line.startswith("TUNNEL_URL="):
                result["tunnel_url"] = line.split("=", 1)[1].strip()
                break
        
        return result
    
    async def get_available_crns(
        self,
        vcpus: int = 1,
        memory_mb: int = 2048,
        disk_gb: int = 20
    ) -> list[dict]:
        """Fetch available CRNs from the CRN list service."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    "https://crns-list.aleph.sh/crns.json",
                    params={"filter_inactive": "true"}
                )
                if response.status_code == 200:
                    data = response.json()
                    crns = []
                    for node in data.get("crns", []):
                        # Need payment receiver for credits
                        if node.get("payment_receiver_address"):
                            crns.append({
                                "hash": node.get("hash"),
                                "name": node.get("name"),
                                "url": node.get("address"),
                                "payment_address": node.get("payment_receiver_address"),
                                "version": node.get("version", "0.0.0"),
                            })
                    return crns
        except Exception as e:
            logger.warning(f"Failed to fetch CRNs: {e}")
        return []
    
    async def create_instance_with_sdk(
        self,
        vcpus: int = 1,
        memory_mb: int = 2048,
        disk_size_mb: int = 20480,
        ssh_pubkey: str = "",
        rootfs: str = "debian12",
        instance_name: str = "marketplace-instance",
        crn_url: Optional[str] = None,
        crn_payment_address: Optional[str] = None,
    ) -> dict:
        """Create a new Aleph Cloud instance using the SDK with credits payment."""
        if not ALEPH_SDK_AVAILABLE:
            return {"status": "error", "error": "aleph-sdk-python not installed"}
        
        if not self._account:
            return {"status": "error", "error": "No account configured"}
        
        if not ssh_pubkey:
            return {"status": "error", "error": "SSH public key is required"}
        
        rootfs_hash = ROOTFS_IMAGES.get(rootfs, rootfs)
        if len(rootfs_hash) != 64:
            return {"status": "error", "error": f"Invalid rootfs: {rootfs}"}
        
        # Auto-select CRN if not provided
        if not crn_url or not crn_payment_address:
            crns = await self.get_available_crns(vcpus, memory_mb, disk_size_mb // 1024)
            if crns:
                selected_crn = crns[0]
                crn_url = selected_crn["url"]
                crn_payment_address = selected_crn["payment_address"]
                logger.info(f"Auto-selected CRN: {selected_crn['name']} ({crn_url})")
            else:
                return {"status": "error", "error": "No CRNs available"}
        
        if not crn_url.startswith("http"):
            crn_url = f"https://{crn_url}"
        crn_url = crn_url.rstrip("/")
        
        payment = Payment(
            chain=Chain.ETH,
            type=PaymentType.credit,
            receiver=crn_payment_address,
        )
        
        try:
            async with AuthenticatedAlephHttpClient(
                account=self._account,
                api_server=aleph_settings.API_HOST
            ) as client:
                message, status = await client.create_instance(
                    rootfs=rootfs_hash,
                    rootfs_size=disk_size_mb,
                    payment=payment,
                    vcpus=vcpus,
                    memory=memory_mb,
                    ssh_keys=self._build_ssh_keys(ssh_pubkey),
                    hypervisor=HypervisorType.qemu,
                    metadata={"name": instance_name},
                    channel="ALEPH-MARKETPLACE",
                    storage_engine=StorageEnum.storage,
                    sync=True,
                )
                
                instance_hash = str(message.item_hash)
                logger.info(f"Instance message created: {instance_hash}")
                
                await asyncio.sleep(2)
                
                async with VmClient(self._account, crn_url) as vm_client:
                    start_status, start_result = await vm_client.start_instance(instance_hash)
                    
                    if start_status != 200:
                        logger.warning(f"CRN notification returned {start_status}")
                        return {
                            "status": "partial",
                            "instance_hash": instance_hash,
                            "crn_url": crn_url,
                            "message": "Instance created but CRN notification failed",
                        }
                
                return {
                    "status": "success",
                    "instance_hash": instance_hash,
                    "crn_url": crn_url,
                    "specs": {
                        "vcpus": vcpus,
                        "memory_mb": memory_mb,
                        "disk_mb": disk_size_mb,
                        "rootfs": rootfs,
                    },
                    "crn": {
                        "url": crn_url,
                        "payment_address": crn_payment_address,
                    },
                    "payment": {
                        "type": "credit",
                    }
                }
                
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Instance creation failed: {error_msg}")
            
            if "InsufficientFunds" in error_msg or "balance" in error_msg.lower():
                return {
                    "status": "error",
                    "error": "Insufficient credits or ALEPH balance",
                    "details": error_msg,
                }
            
            return {"status": "error", "error": "Instance creation failed", "details": error_msg}
    
    async def create_instance(
        self,
        address: str,
        vcpus: int = 1,
        memory_mb: int = 2048,
        disk_gb: int = 20,
        ssh_keys: list[str] = None
    ) -> dict:
        """Create instance. Uses SDK if available, else returns manual instructions."""
        if ALEPH_SDK_AVAILABLE and self._account and ssh_keys:
            return await self.create_instance_with_sdk(
                vcpus=vcpus,
                memory_mb=memory_mb,
                disk_size_mb=disk_gb * 1024,
                ssh_pubkey=ssh_keys[0],
                instance_name=f"marketplace-{address[:8]}"
            )
        
        return {
            "status": "manual_required",
            "instructions": {
                "method": "Use aleph-client CLI or web console",
                "cli_command": f"aleph instance create --vcpus {vcpus} --memory {memory_mb} --rootfs-size {disk_gb * 1024}",
                "web_console": "https://console.aleph.cloud/computing/instance/new",
            },
        }
    
    async def delete_instance(self, instance_hash: str) -> dict:
        """Delete an instance and stop billing."""
        if not ALEPH_SDK_AVAILABLE:
            return {"status": "error", "error": "aleph-sdk-python not installed"}
        if not self._account:
            return {"status": "error", "error": "No account configured"}
        
        try:
            from aleph_message.models import ItemHash
            
            async with AuthenticatedAlephHttpClient(
                account=self._account,
                api_server=aleph_settings.API_HOST
            ) as client:
                message, status = await client.forget(
                    hashes=[ItemHash(instance_hash)],
                    reason="User deletion via marketplace",
                )
                return {
                    "status": "success",
                    "message": f"Instance {instance_hash} deleted",
                    "forget_hash": str(message.item_hash)
                }
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
    async def get_instance_status(self, instance_hash: str) -> dict:
        """Get the status of an instance including allocation info."""
        try:
            async with httpx.AsyncClient(timeout=15.0) as http_client:
                msg_response = await http_client.get(
                    f"{self.API_URL}/messages/{instance_hash}"
                )
                
                if msg_response.status_code != 200:
                    return {"status": "not_found", "instance_hash": instance_hash}
                
                msg_data = msg_response.json()
                content = msg_data.get("content", {})
                
                # Get allocation info with IP
                allocation = await self.get_allocation(instance_hash)
                
                result = {
                    "status": "found",
                    "instance_hash": instance_hash,
                    "name": content.get("metadata", {}).get("name", "unnamed"),
                    "resources": content.get("resources", {}),
                    "payment": content.get("payment", {}),
                    "created": msg_data.get("time"),
                }
                
                if allocation:
                    result["allocation"] = allocation
                    result["vm_ipv6"] = allocation.get("vm_ipv6")
                    
                    # Try to get full networking from CRN
                    node = allocation.get("node", {})
                    crn_url = node.get("url") or node.get("address")
                    if crn_url:
                        networking = await self.get_vm_networking_from_crn(crn_url, instance_hash)
                        if networking:
                            result["networking"] = networking
                
                return result
                
        except Exception as e:
            return {"status": "error", "error": str(e), "instance_hash": instance_hash}
    
    async def deploy_docker_compose(
        self,
        ssh_host: str,
        ssh_port: int,
        ssh_user: str,
        compose_content: str,
        app_name: str
    ) -> dict:
        """Generate deploy script (for backward compat — use deploy_docker_compose_via_ssh for execution)."""
        deploy_script = f'''#!/bin/bash
set -e
mkdir -p /root/apps/{app_name}
cd /root/apps/{app_name}
cat > docker-compose.yml << 'COMPOSE_EOF'
{compose_content}
COMPOSE_EOF
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com | sh
fi
docker compose pull
docker compose up -d
echo "✅ {app_name} deployed successfully!"
docker compose ps
'''
        return {
            "status": "script_ready",
            "ssh_command": f"ssh -p {ssh_port} {ssh_user}@{ssh_host}",
            "deploy_script": deploy_script,
            "app_directory": f"/root/apps/{app_name}"
        }
    
    async def setup_cloudflare_tunnel(
        self,
        ssh_host: str,
        ssh_port: int,
        ssh_user: str,
        local_port: int
    ) -> dict:
        """Generate tunnel script (backward compat)."""
        tunnel_script = f'''#!/bin/bash
if ! command -v cloudflared &> /dev/null; then
    curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared
    chmod +x /usr/local/bin/cloudflared
fi
pkill -f "cloudflared tunnel" 2>/dev/null || true
nohup cloudflared tunnel --url http://localhost:{local_port} > /tmp/tunnel-{local_port}.log 2>&1 &
sleep 5
grep -o 'https://[a-z-]*\\.trycloudflare\\.com' /tmp/tunnel-{local_port}.log | head -1
'''
        return {"status": "script_ready", "tunnel_script": tunnel_script}


class DeploymentOrchestrator:
    """Orchestrates full app deployments with automated IP retrieval and SSH execution."""
    
    def __init__(self, private_key: Optional[str] = None):
        self.deployer = AlephDeployer(private_key=private_key)
        self.deployments = {}
    
    async def deploy_app(
        self,
        app: dict,
        address: str,
        instance_name: str,
        ssh_info: Optional[dict] = None,
        ssh_pubkey: Optional[str] = None
    ) -> dict:
        """
        Full deployment flow:
        1. Check credits
        2. Create instance (if no ssh_info)
        3. Poll for VM IP
        4. SSH in and deploy docker-compose
        5. Optionally set up Cloudflare tunnel
        """
        deployment_id = f"{app['id']}-{address[:8]}"
        
        result = {
            "deployment_id": deployment_id,
            "app": app["name"],
            "status": "pending",
            "steps": []
        }
        
        # Step 1: Check credits
        credits = await self.deployer.check_credits(address)
        result["steps"].append({
            "step": "check_credits",
            "status": "complete",
            "balance": credits.get("credit_balance", credits.get("balance", "unknown"))
        })
        
        if ssh_info:
            # Deploy to existing instance
            compose_result = await self.deployer.deploy_docker_compose(
                ssh_host=ssh_info["host"],
                ssh_port=ssh_info.get("port", 22),
                ssh_user=ssh_info.get("user", "root"),
                compose_content=app["docker_compose"],
                app_name=app["id"]
            )
            result["steps"].append({
                "step": "prepare_deployment",
                "status": "complete",
                "details": compose_result
            })
            
            tunnel_result = await self.deployer.setup_cloudflare_tunnel(
                ssh_host=ssh_info["host"],
                ssh_port=ssh_info.get("port", 22),
                ssh_user=ssh_info.get("user", "root"),
                local_port=80
            )
            result["steps"].append({
                "step": "prepare_tunnel",
                "status": "complete",
                "details": tunnel_result
            })
            
            result["status"] = "ready_to_execute"
            result["execution_instructions"] = {
                "1_connect": f"ssh -p {ssh_info.get('port', 22)} {ssh_info.get('user', 'root')}@{ssh_info['host']}",
                "2_deploy": "Run the deployment script",
                "3_tunnel": "Run the tunnel script to get public URL"
            }
        
        elif ssh_pubkey and self.deployer._account:
            # Create new instance with SDK
            instance_result = await self.deployer.create_instance_with_sdk(
                vcpus=app["requirements"]["vcpus"],
                memory_mb=app["requirements"]["memory_mb"],
                disk_size_mb=app["requirements"]["disk_gb"] * 1024,
                ssh_pubkey=ssh_pubkey,
                instance_name=instance_name
            )
            result["steps"].append({
                "step": "create_instance",
                "status": instance_result.get("status"),
                "details": instance_result
            })
            
            if instance_result.get("status") == "success":
                result["status"] = "instance_created"
                result["instance_hash"] = instance_result["instance_hash"]
                result["crn_url"] = instance_result.get("crn_url")
            else:
                result["status"] = "instance_creation_failed"
        
        else:
            # No instance, provide instructions
            instance_result = await self.deployer.create_instance(
                address=address,
                vcpus=app["requirements"]["vcpus"],
                memory_mb=app["requirements"]["memory_mb"],
                disk_gb=app["requirements"]["disk_gb"]
            )
            result["steps"].append({
                "step": "create_instance",
                "status": "manual_required",
                "details": instance_result
            })
            result["status"] = "awaiting_instance"
            result["next_steps"] = [
                "1. Create an instance using the Aleph Cloud console or CLI",
                "2. Note the SSH connection details",
                "3. Call this API again with ssh_info to complete deployment"
            ]
        
        self.deployments[deployment_id] = result
        return result
    
    async def poll_and_deploy(
        self,
        deployment_id: str,
        app: dict,
        instance_hash: str,
        crn_url: Optional[str] = None,
    ) -> dict:
        """
        Background task: poll for VM IP, then deploy the app via SSH.
        This is the automated flow triggered after instance creation.
        """
        deployment = self.deployments.get(deployment_id, {})
        deployment["status"] = "waiting_for_ip"
        self.deployments[deployment_id] = deployment
        
        # Step: Poll for IP
        ip_result = await self.deployer.poll_for_vm_ip(
            instance_hash=instance_hash,
            crn_url=crn_url,
            max_attempts=30,
            interval_seconds=10,
        )
        
        deployment["steps"].append({
            "step": "poll_ip",
            "status": ip_result["status"],
            "details": ip_result,
        })
        
        if ip_result["status"] != "ready":
            deployment["status"] = "ip_timeout"
            self.deployments[deployment_id] = deployment
            return deployment
        
        ssh_host = ip_result["ssh_host"]
        ssh_port = ip_result.get("ssh_port", 22)
        
        deployment["ssh_info"] = {
            "host": ssh_host,
            "port": ssh_port,
            "ipv4": ip_result.get("ipv4"),
            "ipv6": ip_result.get("ipv6"),
            "mapped_ports": ip_result.get("mapped_ports", {}),
        }
        deployment["status"] = "deploying_app"
        self.deployments[deployment_id] = deployment
        
        # Wait a bit for SSH to be ready
        await asyncio.sleep(30)
        
        # Step: Deploy docker-compose via SSH
        deploy_result = await self.deployer.deploy_docker_compose_via_ssh(
            ssh_host=ssh_host,
            ssh_port=ssh_port,
            ssh_user="root",
            compose_content=app["docker_compose"],
            app_name=app["id"],
        )
        
        deployment["steps"].append({
            "step": "deploy_app",
            "status": "success" if deploy_result.get("deployed") else "error",
            "details": deploy_result,
        })
        
        if deploy_result.get("deployed"):
            deployment["status"] = "running"
            
            # Step: Set up Cloudflare tunnel
            tunnel_result = await self.deployer.setup_cloudflare_tunnel_via_ssh(
                ssh_host=ssh_host,
                ssh_port=ssh_port,
                ssh_user="root",
                local_port=80,
            )
            
            deployment["steps"].append({
                "step": "setup_tunnel",
                "status": "success" if tunnel_result.get("tunnel_url") else "skipped",
                "details": tunnel_result,
            })
            
            if tunnel_result.get("tunnel_url"):
                deployment["public_url"] = tunnel_result["tunnel_url"]
            
            # Step: Remove marketplace deployment key from VM
            try:
                cleanup_result = await self.deployer.remove_marketplace_key_from_vm(
                    ssh_host=ssh_host,
                    ssh_port=ssh_port,
                    ssh_user="root",
                )
                deployment["steps"].append({
                    "step": "cleanup_deployment_key",
                    "status": cleanup_result.get("status", "unknown"),
                    "details": cleanup_result,
                })
                deployment["deployment_key_cleaned"] = cleanup_result.get("status") == "success"
                if cleanup_result.get("status") == "success":
                    logger.info(f"Deployment key cleaned up for {deployment_id}")
                else:
                    logger.warning(f"Deployment key cleanup returned: {cleanup_result.get('status')} for {deployment_id}")
            except Exception as e:
                logger.warning(f"Failed to clean up deployment key for {deployment_id}: {e}")
                deployment["steps"].append({
                    "step": "cleanup_deployment_key",
                    "status": "error",
                    "details": {"error": str(e)},
                })
                deployment["deployment_key_cleaned"] = False
        else:
            deployment["status"] = "deploy_failed"
        
        self.deployments[deployment_id] = deployment
        return deployment


# Singleton orchestrator (without private key by default)
orchestrator = DeploymentOrchestrator()


async def deploy(
    app: dict,
    address: str,
    instance_name: str,
    ssh_info: dict = None,
    ssh_pubkey: str = None,
    private_key: str = None
) -> dict:
    """Main deployment function."""
    if private_key:
        orch = DeploymentOrchestrator(private_key=private_key)
        return await orch.deploy_app(app, address, instance_name, ssh_info, ssh_pubkey)
    
    return await orchestrator.deploy_app(app, address, instance_name, ssh_info, ssh_pubkey)


async def create_instance(
    private_key: str,
    vcpus: int = 1,
    memory_mb: int = 2048,
    disk_gb: int = 20,
    ssh_pubkey: str = "",
    rootfs: str = "debian12",
    instance_name: str = "aleph-instance"
) -> dict:
    """Create an Aleph Cloud instance directly."""
    deployer = AlephDeployer(private_key=private_key)
    return await deployer.create_instance_with_sdk(
        vcpus=vcpus,
        memory_mb=memory_mb,
        disk_size_mb=disk_gb * 1024,
        ssh_pubkey=ssh_pubkey,
        rootfs=rootfs,
        instance_name=instance_name
    )
