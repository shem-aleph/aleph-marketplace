"""
Aleph Cloud Deployer - Handles actual instance creation and app deployment

Uses aleph-sdk-python for programmatic instance creation with the credits payment model.
"""
import asyncio
import json
import logging
import os
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


class AlephDeployer:
    """Handles deployment of apps to Aleph Cloud instances using SDK"""
    
    API_URL = "https://api2.aleph.im/api/v0"
    
    def __init__(self, private_key: Optional[str] = None):
        """
        Initialize the deployer.
        
        Args:
            private_key: Hex-encoded private key (with or without 0x prefix)
        """
        self.private_key = private_key
        self._account = None
        
        if private_key and ALEPH_SDK_AVAILABLE:
            self._account = self._load_account(private_key)
    
    def _load_account(self, private_key: str) -> Optional["ETHAccount"]:
        """Load an Ethereum account from a private key."""
        if not ALEPH_SDK_AVAILABLE:
            return None
        
        # Handle different private key formats
        if private_key.startswith("0x"):
            private_key = private_key[2:]
        
        try:
            pk_bytes = bytes.fromhex(private_key)
            return ETHAccount(private_key=pk_bytes)
        except Exception as e:
            logger.error(f"Failed to load account: {e}")
            return None
    
    @property
    def address(self) -> Optional[str]:
        """Get the account address."""
        if self._account:
            return self._account.get_address()
        return None
    
    async def check_credits(self, address: str) -> dict:
        """Check credit balance for an address."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Try the official credits endpoint
                response = await client.get(
                    "https://balance.aleph.cloud/credit-balance",
                    params={"address": address}
                )
                if response.status_code == 200:
                    data = response.json()
                    return {"balance": data.get("balance", 0)}
        except Exception as e:
            logger.warning(f"Failed to fetch credits balance: {e}")
        return {"balance": "unknown", "note": "Could not fetch balance"}
    
    async def get_available_crns(
        self,
        vcpus: int = 1,
        memory_mb: int = 2048,
        disk_gb: int = 20
    ) -> list[dict]:
        """
        Fetch available Compute Resource Nodes (CRNs) from the network.
        
        Returns a list of CRNs that can host instances.
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    "https://scheduler.api.aleph.cloud/api/v0/allocation/resource_nodes"
                )
                if response.status_code == 200:
                    data = response.json()
                    crns = []
                    for node in data.get("resource_nodes", []):
                        # Filter for active nodes with stream payment support
                        if (node.get("status") == "active" and 
                            node.get("payment_receiver_address")):
                            crns.append({
                                "hash": node.get("hash"),
                                "name": node.get("name"),
                                "url": node.get("address"),
                                "payment_address": node.get("payment_receiver_address"),
                                "score": node.get("score", 0),
                            })
                    # Sort by score descending
                    crns.sort(key=lambda x: x.get("score", 0), reverse=True)
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
        """
        Create a new Aleph Cloud instance using the SDK with credits payment.
        
        Args:
            vcpus: Number of virtual CPUs (1, 2, 4, etc.)
            memory_mb: Memory in MB (2048, 4096, 8192, etc.)
            disk_size_mb: Disk size in MB (minimum 20480 = 20GB)
            ssh_pubkey: SSH public key for instance access
            rootfs: Rootfs image name or hash (ubuntu22, ubuntu24, debian12, or custom hash)
            instance_name: Human-readable name for the instance
            crn_url: URL of the CRN to deploy on (required for credits)
            crn_payment_address: Payment receiver address of the CRN (required for credits)
        
        Returns:
            dict with instance_hash, status, and connection details
        """
        if not ALEPH_SDK_AVAILABLE:
            return {
                "status": "error",
                "error": "aleph-sdk-python not installed",
                "instructions": "pip install aleph-sdk-python[ethereum]"
            }
        
        if not self._account:
            return {
                "status": "error",
                "error": "No account configured. Please provide a private key."
            }
        
        if not ssh_pubkey:
            return {
                "status": "error",
                "error": "SSH public key is required for instance access"
            }
        
        # Resolve rootfs hash
        rootfs_hash = ROOTFS_IMAGES.get(rootfs, rootfs)
        if len(rootfs_hash) != 64:
            return {
                "status": "error",
                "error": f"Invalid rootfs: {rootfs}. Use ubuntu22, ubuntu24, debian12, or a 64-char hash."
            }
        
        # For credits payment, we need a CRN
        if not crn_url or not crn_payment_address:
            # Try to auto-select a CRN
            crns = await self.get_available_crns(vcpus, memory_mb, disk_size_mb // 1024)
            if crns:
                selected_crn = crns[0]  # Pick the highest scored CRN
                crn_url = selected_crn["url"]
                crn_payment_address = selected_crn["payment_address"]
                logger.info(f"Auto-selected CRN: {selected_crn['name']} ({crn_url})")
            else:
                return {
                    "status": "error",
                    "error": "No CRNs available. Please specify crn_url and crn_payment_address."
                }
        
        # Ensure CRN URL is properly formatted
        if not crn_url.startswith("http"):
            crn_url = f"https://{crn_url}"
        crn_url = crn_url.rstrip("/")
        
        # Create the payment configuration for credits
        payment = Payment(
            chain=Chain.ETH,  # Credits work across chains
            type=PaymentType.credit,
            receiver=crn_payment_address,
        )
        
        try:
            async with AuthenticatedAlephHttpClient(
                account=self._account,
                api_server=aleph_settings.API_HOST
            ) as client:
                # Create the instance message
                message, status = await client.create_instance(
                    rootfs=rootfs_hash,
                    rootfs_size=disk_size_mb,
                    payment=payment,
                    vcpus=vcpus,
                    memory=memory_mb,
                    ssh_keys=[ssh_pubkey],
                    hypervisor=HypervisorType.qemu,
                    metadata={"name": instance_name},
                    channel="ALEPH-MARKETPLACE",
                    storage_engine=StorageEnum.storage,
                    sync=True,
                )
                
                instance_hash = str(message.item_hash)
                logger.info(f"Instance message created: {instance_hash}")
                
                # For credits/PAYG, we need to notify the CRN to start the instance
                await asyncio.sleep(2)  # Wait for message to propagate
                
                async with VmClient(self._account, crn_url) as vm_client:
                    start_status, start_result = await vm_client.start_instance(instance_hash)
                    
                    if start_status != 200:
                        logger.warning(f"CRN notification returned {start_status}: {start_result}")
                        return {
                            "status": "partial",
                            "instance_hash": instance_hash,
                            "message": "Instance created but CRN notification failed",
                            "crn_status": start_status,
                            "crn_response": start_result,
                            "manual_start": f"aleph instance allocate {instance_hash} --domain {crn_url}"
                        }
                
                return {
                    "status": "success",
                    "instance_hash": instance_hash,
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
                    "access": {
                        "note": "Instance is starting. SSH access will be available shortly.",
                        "check_status": f"aleph instance list",
                        "view_logs": f"aleph instance logs {instance_hash}",
                    },
                    "payment": {
                        "type": "credit",
                        "note": "Credits are deducted from your balance automatically"
                    }
                }
                
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Instance creation failed: {error_msg}")
            
            # Check for common error types
            if "InsufficientFunds" in error_msg or "balance" in error_msg.lower():
                return {
                    "status": "error",
                    "error": "Insufficient credits or ALEPH balance",
                    "details": error_msg,
                    "action": "Top up your credits at https://account.aleph.cloud"
                }
            
            return {
                "status": "error",
                "error": "Instance creation failed",
                "details": error_msg
            }
    
    async def create_instance(
        self,
        address: str,
        vcpus: int = 1,
        memory_mb: int = 2048,
        disk_gb: int = 20,
        ssh_keys: list[str] = None
    ) -> dict:
        """
        Create a new Aleph Cloud instance.
        
        If SDK is available and account is configured, uses SDK.
        Otherwise, returns manual instructions.
        """
        # Try SDK-based creation if available
        if ALEPH_SDK_AVAILABLE and self._account and ssh_keys:
            return await self.create_instance_with_sdk(
                vcpus=vcpus,
                memory_mb=memory_mb,
                disk_size_mb=disk_gb * 1024,
                ssh_pubkey=ssh_keys[0],
                instance_name=f"marketplace-{address[:8]}"
            )
        
        # Fallback to manual instructions
        return {
            "status": "manual_required",
            "instructions": {
                "method": "Use aleph-client CLI or web console",
                "cli_command": f"aleph instance create --vcpus {vcpus} --memory {memory_mb} --rootfs-size {disk_gb * 1024}",
                "web_console": "https://console.aleph.cloud/computing/instance/new",
                "specs": {
                    "vcpus": vcpus,
                    "memory_mb": memory_mb,
                    "disk_gb": disk_gb
                }
            },
            "sdk_note": "For automated creation, initialize AlephDeployer with a private_key"
        }
    
    async def delete_instance(self, instance_hash: str) -> dict:
        """
        Delete an instance and stop billing.
        
        Args:
            instance_hash: The instance item hash to delete
        
        Returns:
            dict with deletion status
        """
        if not ALEPH_SDK_AVAILABLE:
            return {
                "status": "error",
                "error": "aleph-sdk-python not installed"
            }
        
        if not self._account:
            return {
                "status": "error",
                "error": "No account configured"
            }
        
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
            return {
                "status": "error",
                "error": str(e)
            }
    
    async def get_instance_status(self, instance_hash: str) -> dict:
        """
        Get the status of an instance.
        
        Args:
            instance_hash: The instance item hash
        
        Returns:
            dict with instance status and details
        """
        try:
            async with httpx.AsyncClient(timeout=15.0) as http_client:
                # Get instance message
                msg_response = await http_client.get(
                    f"{self.API_URL}/messages/{instance_hash}"
                )
                
                if msg_response.status_code != 200:
                    return {"status": "not_found", "instance_hash": instance_hash}
                
                msg_data = msg_response.json()
                content = msg_data.get("content", {})
                
                # Try to get allocation info
                alloc_response = await http_client.get(
                    "https://scheduler.api.aleph.cloud/api/v0/allocation",
                    params={"item_hash": instance_hash}
                )
                
                allocation = None
                if alloc_response.status_code == 200:
                    allocation = alloc_response.json()
                
                return {
                    "status": "found",
                    "instance_hash": instance_hash,
                    "name": content.get("metadata", {}).get("name", "unnamed"),
                    "resources": content.get("resources", {}),
                    "payment": content.get("payment", {}),
                    "allocation": allocation,
                    "created": msg_data.get("time"),
                }
                
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "instance_hash": instance_hash
            }
    
    async def deploy_docker_compose(
        self,
        ssh_host: str,
        ssh_port: int,
        ssh_user: str,
        compose_content: str,
        app_name: str
    ) -> dict:
        """
        Deploy a docker-compose application to an existing instance via SSH.
        
        This generates the commands needed - actual execution requires SSH access.
        """
        deploy_script = f'''#!/bin/bash
set -e

# Create app directory
mkdir -p /root/apps/{app_name}
cd /root/apps/{app_name}

# Write docker-compose.yml
cat > docker-compose.yml << 'COMPOSE_EOF'
{compose_content}
COMPOSE_EOF

# Install Docker if not present
if ! command -v docker &> /dev/null; then
    echo "Installing Docker..."
    curl -fsSL https://get.docker.com | sh
fi

# Start the application
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
        """Generate commands to set up a Cloudflare tunnel."""
        tunnel_script = f'''#!/bin/bash
# Install cloudflared if not present
if ! command -v cloudflared &> /dev/null; then
    curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared
    chmod +x /usr/local/bin/cloudflared
fi

# Start tunnel
nohup cloudflared tunnel --url http://localhost:{local_port} > /tmp/tunnel-{local_port}.log 2>&1 &

# Wait for URL
sleep 5
grep -o 'https://[a-z-]*\\.trycloudflare\\.com' /tmp/tunnel-{local_port}.log | head -1
'''
        
        return {
            "status": "script_ready",
            "tunnel_script": tunnel_script,
            "note": "Run this after docker-compose is running"
        }


class DeploymentOrchestrator:
    """Orchestrates full app deployments"""
    
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
        Full deployment flow for an app.
        
        If ssh_info is provided, deploys to existing instance.
        If ssh_pubkey is provided and deployer has account, creates new instance.
        Otherwise, provides instructions for instance creation.
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
            "balance": credits.get("balance", "unknown")
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
            
            # Tunnel setup
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
                result["next_steps"] = [
                    f"1. Wait for instance to start (check: aleph instance list)",
                    f"2. Get SSH details from instance allocation",
                    f"3. Deploy app using the generated scripts"
                ]
            else:
                result["status"] = "instance_creation_failed"
        
        else:
            # No instance - provide creation instructions
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
    """
    Main deployment function.
    
    Args:
        app: App configuration with docker_compose and requirements
        address: User's wallet address
        instance_name: Name for the instance
        ssh_info: Existing instance SSH details (optional)
        ssh_pubkey: SSH public key for new instance (optional)
        private_key: Private key for SDK-based creation (optional)
    """
    if private_key:
        # Create a new orchestrator with the private key
        orch = DeploymentOrchestrator(private_key=private_key)
        return await orch.deploy_app(app, address, instance_name, ssh_info, ssh_pubkey)
    
    return await orchestrator.deploy_app(app, address, instance_name, ssh_info, ssh_pubkey)


# Convenience function for direct instance creation
async def create_instance(
    private_key: str,
    vcpus: int = 1,
    memory_mb: int = 2048,
    disk_gb: int = 20,
    ssh_pubkey: str = "",
    rootfs: str = "debian12",
    instance_name: str = "aleph-instance"
) -> dict:
    """
    Create an Aleph Cloud instance directly.
    
    Args:
        private_key: Hex-encoded private key (with or without 0x prefix)
        vcpus: Number of vCPUs
        memory_mb: Memory in MB
        disk_gb: Disk size in GB
        ssh_pubkey: SSH public key for access
        rootfs: OS image (ubuntu22, ubuntu24, debian12, or custom hash)
        instance_name: Human-readable name
    
    Returns:
        dict with creation status and instance details
    """
    deployer = AlephDeployer(private_key=private_key)
    return await deployer.create_instance_with_sdk(
        vcpus=vcpus,
        memory_mb=memory_mb,
        disk_size_mb=disk_gb * 1024,
        ssh_pubkey=ssh_pubkey,
        rootfs=rootfs,
        instance_name=instance_name
    )
