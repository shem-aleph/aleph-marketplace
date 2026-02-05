"""
Aleph Cloud Marketplace - One-click app deployment on decentralized infrastructure
"""
import json
import os
import asyncio
import secrets
import hashlib
import time
from pathlib import Path
from typing import Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException, BackgroundTasks, Header, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from pydantic import BaseModel
import httpx

import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s: %(message)s')

from deployer import deploy as deploy_to_aleph, orchestrator
from dashboard_v2 import DASHBOARD_HTML
from ssh_executor import SSHExecutor, DeploymentTracker

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
from security import (
    sanitize_app_name, validate_eth_address, validate_ssh_host, validate_port,
    rate_limiter, require_eth_account, extract_token
)

# Try to import eth_account for signature verification
try:
    from eth_account.messages import encode_defunct
    from eth_account import Account
    ETH_ACCOUNT_AVAILABLE = True
except ImportError:
    ETH_ACCOUNT_AVAILABLE = False

app = FastAPI(
    title="Aleph Cloud Marketplace",
    description="One-click deployment of applications on Aleph Cloud",
    version="0.1.0"
)

# Load app templates
TEMPLATES_PATH = Path(__file__).parent / "templates" / "apps.json"
with open(TEMPLATES_PATH) as f:
    APP_DATA = json.load(f)

APPS = {app["id"]: app for app in APP_DATA["apps"]}
CATEGORIES = APP_DATA["categories"]

# In-memory deployments (would use persistent storage in production)
DEPLOYMENTS = {}

# Persistent deployment tracker
deployment_tracker = DeploymentTracker("/tmp/marketplace_deployments.json")

# ============ Web3 Auth Storage ============
# Nonce storage: {address: {nonce: str, created_at: float}}
AUTH_NONCES = {}
# Session storage: {token: {address: str, created_at: float, expires_at: float}}
AUTH_SESSIONS = {}
# Session expiry: 24 hours
SESSION_EXPIRY_SECONDS = 86400
# Nonce expiry: 5 minutes
NONCE_EXPIRY_SECONDS = 300


class SSHInfo(BaseModel):
    host: str
    port: int = 22
    user: str = "root"


class DeployRequest(BaseModel):
    app_id: str
    address: str  # Ethereum address for deployment
    instance_name: Optional[str] = None
    ssh_info: Optional[SSHInfo] = None  # If provided, deploy to existing instance


class Deployment(BaseModel):
    id: str
    app_id: str
    address: str
    instance_name: str
    status: str  # pending, deploying, running, failed, stopped
    created_at: str
    instance_hash: Optional[str] = None
    ssh_info: Optional[dict] = None
    public_url: Optional[str] = None


class NonceRequest(BaseModel):
    address: str


class NonceResponse(BaseModel):
    nonce: str
    message: str


class VerifyRequest(BaseModel):
    address: str
    signature: str
    nonce: str


class VerifyResponse(BaseModel):
    token: str
    address: str
    expires_at: float


class SessionInfo(BaseModel):
    address: str
    authenticated: bool
    expires_at: Optional[float] = None


# ============ Auth Helper Functions ============

def cleanup_expired_nonces():
    """Remove expired nonces"""
    now = time.time()
    expired = [addr for addr, data in AUTH_NONCES.items() 
               if now - data["created_at"] > NONCE_EXPIRY_SECONDS]
    for addr in expired:
        del AUTH_NONCES[addr]


def cleanup_expired_sessions():
    """Remove expired sessions"""
    now = time.time()
    expired = [token for token, data in AUTH_SESSIONS.items() 
               if now > data["expires_at"]]
    for token in expired:
        del AUTH_SESSIONS[token]


def generate_nonce() -> str:
    """Generate a cryptographically secure nonce"""
    return secrets.token_hex(16)


def generate_session_token() -> str:
    """Generate a session token"""
    return secrets.token_urlsafe(32)


def verify_signature(address: str, message: str, signature: str) -> bool:
    """Verify an Ethereum signature"""
    if not ETH_ACCOUNT_AVAILABLE:
        # SECURITY: Do NOT accept signatures without proper verification
        raise HTTPException(
            status_code=503,
            detail="Authentication unavailable: eth_account library not installed"
        )
    
    try:
        # Encode the message as per EIP-191
        message_encoded = encode_defunct(text=message)
        # Recover the address from the signature
        recovered_address = Account.recover_message(message_encoded, signature=signature)
        # Compare addresses (case-insensitive)
        return recovered_address.lower() == address.lower()
    except Exception as e:
        print(f"Signature verification failed: {e}")
        return False


def get_session_from_token(token: str) -> Optional[dict]:
    """Get session data from token, returns None if invalid/expired"""
    cleanup_expired_sessions()
    if token not in AUTH_SESSIONS:
        return None
    session = AUTH_SESSIONS[token]
    if time.time() > session["expires_at"]:
        del AUTH_SESSIONS[token]
        return None
    return session


# ============ Auth API Routes ============

@app.post("/api/auth/nonce", response_model=NonceResponse)
async def get_auth_nonce(request: NonceRequest, req: Request):
    """Generate a nonce for wallet signing"""
    # SECURITY: Rate limit nonce requests
    rate_limiter.check(
        rate_limiter.get_client_key(req, "nonce"), 
        max_requests=20, 
        window_seconds=60
    )
    
    cleanup_expired_nonces()
    
    # SECURITY: Validate address format properly
    address = validate_eth_address(request.address)
    
    nonce = generate_nonce()
    message = f"Sign this message to authenticate with Aleph Marketplace.\n\nNonce: {nonce}\nAddress: {address}"
    
    AUTH_NONCES[address] = {
        "nonce": nonce,
        "created_at": time.time()
    }
    
    return NonceResponse(nonce=nonce, message=message)


@app.post("/api/auth/verify", response_model=VerifyResponse)
async def verify_auth(request: VerifyRequest, req: Request):
    """Verify a signed message and return a session token"""
    # SECURITY: Rate limit verification attempts
    rate_limiter.check(
        rate_limiter.get_client_key(req, "verify"), 
        max_requests=10, 
        window_seconds=60
    )
    
    cleanup_expired_nonces()
    
    # SECURITY: Validate address format
    address = validate_eth_address(request.address)
    
    # Check if nonce exists and is valid
    if address not in AUTH_NONCES:
        raise HTTPException(status_code=400, detail="No pending nonce for this address. Request a new nonce.")
    
    stored_nonce = AUTH_NONCES[address]
    
    # Check nonce expiry
    if time.time() - stored_nonce["created_at"] > NONCE_EXPIRY_SECONDS:
        del AUTH_NONCES[address]
        raise HTTPException(status_code=400, detail="Nonce expired. Request a new nonce.")
    
    # Check nonce matches
    if stored_nonce["nonce"] != request.nonce:
        raise HTTPException(status_code=400, detail="Invalid nonce")
    
    # Construct the expected message
    expected_message = f"Sign this message to authenticate with Aleph Marketplace.\n\nNonce: {request.nonce}\nAddress: {address}"
    
    # Verify signature
    if not verify_signature(address, expected_message, request.signature):
        raise HTTPException(status_code=401, detail="Invalid signature")
    
    # Remove used nonce
    del AUTH_NONCES[address]
    
    # Create session
    token = generate_session_token()
    expires_at = time.time() + SESSION_EXPIRY_SECONDS
    
    AUTH_SESSIONS[token] = {
        "address": address,
        "created_at": time.time(),
        "expires_at": expires_at
    }
    
    return VerifyResponse(token=token, address=address, expires_at=expires_at)


@app.get("/api/auth/session", response_model=SessionInfo)
async def get_session_info(authorization: Optional[str] = Header(None)):
    """Get current session info"""
    if not authorization:
        return SessionInfo(address="", authenticated=False)
    
    # Extract token from "Bearer <token>" format
    token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization
    
    session = get_session_from_token(token)
    if not session:
        return SessionInfo(address="", authenticated=False)
    
    return SessionInfo(
        address=session["address"],
        authenticated=True,
        expires_at=session["expires_at"]
    )


@app.post("/api/auth/logout")
async def logout(authorization: Optional[str] = Header(None)):
    """Logout and invalidate session"""
    if not authorization:
        return {"success": True}
    
    token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization
    
    if token in AUTH_SESSIONS:
        del AUTH_SESSIONS[token]
    
    return {"success": True}


# ============ API Routes ============

@app.get("/")
async def home():
    """Redirect to the marketplace dashboard"""
    return RedirectResponse(url="/dashboard")


@app.get("/api/apps")
async def list_apps(category: Optional[str] = None):
    """List all available apps"""
    apps = list(APPS.values())
    if category:
        apps = [a for a in apps if a["category"] == category]
    return {"apps": apps, "categories": CATEGORIES}


@app.get("/api/apps/{app_id}")
async def get_app(app_id: str):
    """Get details for a specific app"""
    if app_id not in APPS:
        raise HTTPException(status_code=404, detail="App not found")
    return APPS[app_id]


@app.post("/api/deploy")
async def deploy_app(request: DeployRequest, authorization: Optional[str] = Header(None)):
    """Deploy an app to Aleph Cloud"""
    # Require authentication
    if not authorization:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization
    session = get_session_from_token(token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    
    # Verify the address matches the authenticated session
    if session["address"].lower() != request.address.lower():
        raise HTTPException(status_code=403, detail="Address mismatch")
    
    if request.app_id not in APPS:
        raise HTTPException(status_code=404, detail="App not found")
    
    app = APPS[request.app_id]
    
    # Use the real deployer
    ssh_info = request.ssh_info.dict() if request.ssh_info else None
    result = await deploy_to_aleph(
        app=app,
        address=request.address,
        instance_name=request.instance_name or f"{app['name']} Instance",
        ssh_info=ssh_info
    )
    
    # Store in deployments
    DEPLOYMENTS[result["deployment_id"]] = {
        **result,
        "app_id": request.app_id,
        "address": request.address,
        "instance_name": request.instance_name,
        "created_at": datetime.utcnow().isoformat()
    }
    
    return result


@app.post("/api/deploy/execute")
async def execute_deployment(
    deployment_id: str, 
    ssh_info: SSHInfo,
    authorization: Optional[str] = Header(None)
):
    """Execute deployment on an instance (requires SSH access)"""
    # SECURITY: Require authentication
    if not authorization:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    token = extract_token(authorization)
    session = get_session_from_token(token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    
    if deployment_id not in orchestrator.deployments:
        raise HTTPException(status_code=404, detail="Deployment not found")
    
    deployment = orchestrator.deployments[deployment_id]
    
    # SECURITY: Verify ownership
    if deployment.get("address", "").lower() != session["address"].lower():
        raise HTTPException(status_code=403, detail="Not your deployment")
    
    # SECURITY: Validate SSH host
    try:
        validate_ssh_host(ssh_info.host)
        validate_port(ssh_info.port)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Get the app
    app_name = deployment_id.rsplit("-", 1)[0]
    if app_name not in APPS:
        raise HTTPException(status_code=404, detail="App not found")
    
    app = APPS[app_name]
    
    # Generate execution commands
    from deployer import AlephDeployer
    deployer = AlephDeployer()
    
    compose_result = await deployer.deploy_docker_compose(
        ssh_host=ssh_info.host,
        ssh_port=ssh_info.port,
        ssh_user=ssh_info.user,
        compose_content=app["docker_compose"],
        app_name=app["id"]
    )
    
    tunnel_port = get_host_port_from_compose(app["docker_compose"])
    tunnel_result = await deployer.setup_caddy_proxy(
        ssh_host=ssh_info.host,
        ssh_port=ssh_info.port,
        ssh_user=ssh_info.user,
        local_port=tunnel_port,
        subdomain="manual",  # TODO: derive from instance hash
    )
    
    return {
        "deployment_id": deployment_id,
        "ssh_connection": f"ssh -p {ssh_info.port} {ssh_info.user}@{ssh_info.host}",
        "deploy_script": compose_result["deploy_script"],
        "tunnel_script": tunnel_result["tunnel_script"],
        "instructions": [
            f"1. Connect: ssh -p {ssh_info.port} {ssh_info.user}@{ssh_info.host}",
            "2. Copy and run the deploy_script",
            "3. Copy and run the tunnel_script to get your public URL"
        ]
    }


class SSHDeployRequest(BaseModel):
    app_id: str
    ssh_host: str
    ssh_port: int = 22
    ssh_user: str = "root"
    setup_tunnel: bool = True
    tunnel_port: Optional[int] = None  # Auto-detect from docker-compose if not specified
    instance_hash: Optional[str] = None  # Aleph instance hash for tracking


def get_host_port_from_compose(compose_content: str) -> int:
    """Extract the first exposed host port from docker-compose"""
    import re
    # Match patterns like '80:3000', '8080:80', etc.
    port_pattern = r"['\"]?(\d+):(\d+)['\"]?"
    matches = re.findall(port_pattern, compose_content)
    if matches:
        return int(matches[0][0])  # Return the host port (first number)
    return 80  # Default to 80


# In-memory store for async deploy jobs
DEPLOY_JOBS = {}


async def _run_deploy_job(deployment_id: str, app: dict, request: SSHDeployRequest, validated_host: str):
    """Background task that performs the actual SSH deployment."""
    log = logging.getLogger("deploy")
    job = DEPLOY_JOBS[deployment_id]

    try:
        executor = SSHExecutor(
            host=validated_host,
            port=request.ssh_port,
            user=request.ssh_user
        )

        # SSH connection with retries
        job["step"] = "connecting"
        log.info(f"Deploy {request.app_id} to {validated_host}:{request.ssh_port}")
        connected = False
        for attempt in range(12):
            if await executor.test_connection():
                connected = True
                log.info(f"SSH connected on attempt {attempt + 1}")
                break
            log.info(f"SSH attempt {attempt + 1}/12 failed, retrying...")
            if attempt < 11:
                await asyncio.sleep(10)

        if not connected:
            log.error(f"Cannot connect to {validated_host}:{request.ssh_port} after 12 attempts")
            job["status"] = "failed"
            job["error"] = f"Cannot SSH to {validated_host}:{request.ssh_port} after 12 attempts"
            deployment_tracker.update_deployment(deployment_id, status="failed", error=job["error"])
            return

        # Deploy docker-compose
        job["step"] = "deploying"
        log.info(f"Deploying docker-compose for {request.app_id}...")
        deploy_result = await executor.deploy_compose(
            app_name=request.app_id,
            compose_content=app["docker_compose"]
        )
        log.info(f"Deploy result: status={deploy_result.get('status')}, error={deploy_result.get('error')}")

        if deploy_result["status"] != "running":
            job["status"] = "failed"
            job["error"] = deploy_result.get("error", "Docker deployment failed")
            deployment_tracker.update_deployment(deployment_id, status="failed", error=job["error"])
            return

        deployment_tracker.update_deployment(
            deployment_id, status="running",
            containers=deploy_result.get("containers", [])
        )
        job["containers"] = deploy_result.get("containers", [])

        if deploy_result.get("generated_passwords"):
            job["generated_passwords"] = deploy_result["generated_passwords"]

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

        # Cleanup marketplace SSH key
        try:
            mk_path = os.path.expanduser("~/.ssh/id_rsa.pub")
            if os.path.exists(mk_path):
                with open(mk_path) as f:
                    mk_content = f.read().strip()
                mk_parts = mk_content.split()
                if len(mk_parts) >= 2:
                    mk_id = mk_parts[1][:40]
                    await executor.run_command(
                        f"grep -v '{mk_id}' ~/.ssh/authorized_keys > /tmp/.ak_clean && "
                        f"mv /tmp/.ak_clean ~/.ssh/authorized_keys && "
                        f"chmod 600 ~/.ssh/authorized_keys"
                    )
        except Exception:
            pass

        job["status"] = "complete"
        job["step"] = "done"
        log.info(f"Deploy {deployment_id} complete. URL={job.get('public_url')}")

    except Exception as e:
        log.error(f"Deploy {deployment_id} failed: {e}")
        job["status"] = "failed"
        job["error"] = str(e)
        deployment_tracker.update_deployment(deployment_id, status="failed", error=str(e))


@app.post("/api/deploy/ssh")
async def deploy_via_ssh(
    request: SSHDeployRequest,
    authorization: Optional[str] = Header(None)
):
    """
    Start an async deployment. Returns immediately with a deployment_id.
    Poll GET /api/deploy/ssh/{deployment_id} for progress.
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Authentication required")

    token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization
    session = get_session_from_token(token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    address = session["address"]

    if request.app_id not in APPS:
        raise HTTPException(status_code=404, detail="App not found")

    app = APPS[request.app_id]

    try:
        validated_host = validate_ssh_host(request.ssh_host)
        validate_port(request.ssh_port)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    deployment_id = f"{request.app_id}-{address[:8]}-{int(time.time())}"
    deployment_tracker.add_deployment(
        deployment_id=deployment_id,
        address=address,
        app_id=request.app_id,
        app_name=app["name"],
        ssh_host=request.ssh_host,
        ssh_port=request.ssh_port,
        status="deploying"
    )
    if request.instance_hash:
        deployment_tracker.update_deployment(deployment_id, instance_hash=request.instance_hash)

    DEPLOY_JOBS[deployment_id] = {
        "status": "running",
        "step": "queued",
        "ssh_host": request.ssh_host,
        "ssh_port": request.ssh_port,
        "app_name": app["name"],
    }

    # Launch background task
    asyncio.create_task(_run_deploy_job(deployment_id, app, request, validated_host))

    return {"deployment_id": deployment_id, "status": "started"}


@app.get("/api/deploy/ssh/{deployment_id}")
async def get_deploy_status(deployment_id: str):
    """Poll for deployment progress."""
    job = DEPLOY_JOBS.get(deployment_id)
    if not job:
        raise HTTPException(status_code=404, detail="Deployment job not found")
    return {"deployment_id": deployment_id, **job}


@app.get("/api/deployments/my")
async def get_my_deployments(authorization: Optional[str] = Header(None)):
    """Get all deployments for the authenticated user"""
    if not authorization:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization
    session = get_session_from_token(token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    
    deployments = deployment_tracker.get_deployments_by_address(session["address"])
    return {"deployments": deployments}


@app.get("/api/deployments/{deployment_id}/status")
async def get_deployment_status(deployment_id: str, authorization: Optional[str] = Header(None)):
    """Get live status of a deployment by checking containers"""
    deployment = deployment_tracker.get_deployment(deployment_id)
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")
    
    # Create executor to check status
    executor = SSHExecutor(
        host=deployment["ssh_host"],
        port=deployment["ssh_port"],
        user="root"
    )
    
    # Test connection
    if not await executor.test_connection():
        return {
            "deployment_id": deployment_id,
            "status": "unreachable",
            "error": "Cannot connect to instance"
        }
    
    # Get app status
    status = await executor.get_app_status(deployment["app_id"])
    
    # Update tracker
    deployment_tracker.update_deployment(
        deployment_id,
        status=status["status"],
        containers=status.get("containers", [])
    )
    
    return {
        "deployment_id": deployment_id,
        **status,
        "ssh_host": deployment["ssh_host"],
        "public_url": deployment.get("public_url")
    }


@app.post("/api/deployments/{deployment_id}/stop")
async def stop_deployment(deployment_id: str, authorization: Optional[str] = Header(None)):
    """Stop a running deployment"""
    if not authorization:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization
    session = get_session_from_token(token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    
    deployment = deployment_tracker.get_deployment(deployment_id)
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")
    
    # Verify ownership
    if deployment["address"] != session["address"].lower():
        raise HTTPException(status_code=403, detail="Not your deployment")
    
    executor = SSHExecutor(
        host=deployment["ssh_host"],
        port=deployment["ssh_port"],
        user="root"
    )
    
    result = await executor.stop_app(deployment["app_id"])
    
    deployment_tracker.update_deployment(deployment_id, status="stopped")
    
    return {"deployment_id": deployment_id, **result}


@app.delete("/api/deployments/{deployment_id}")
async def delete_deployment(deployment_id: str, authorization: Optional[str] = Header(None)):
    """Delete a deployment completely"""
    if not authorization:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization
    session = get_session_from_token(token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    
    deployment = deployment_tracker.get_deployment(deployment_id)
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")
    
    # Verify ownership
    if deployment["address"] != session["address"].lower():
        raise HTTPException(status_code=403, detail="Not your deployment")
    
    executor = SSHExecutor(
        host=deployment["ssh_host"],
        port=deployment["ssh_port"],
        user="root"
    )
    
    result = await executor.remove_app(deployment["app_id"])
    
    deployment_tracker.remove_deployment(deployment_id)
    
    return {"deployment_id": deployment_id, **result}


@app.get("/api/instances/{address}")
async def get_instances(address: str):
    """Get all Aleph instances for an address"""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                "https://api2.aleph.im/api/v0/messages.json",
                params={
                    "addresses": address,
                    "message_type": "INSTANCE",
                    "pagination": 100
                }
            )
            if response.status_code == 200:
                data = response.json()
                messages = data.get("messages", [])
                
                instances = []
                for msg in messages:
                    content = msg.get("content", {})
                    instances.append({
                        "item_hash": msg.get("item_hash"),
                        "name": content.get("metadata", {}).get("name", "unnamed"),
                        "resources": content.get("resources", {}),
                        "payment": content.get("payment", {}),
                        "created": msg.get("time"),
                    })
                
                return {"address": address, "instances": instances, "count": len(instances)}
    except Exception as e:
        pass
    
    return {"address": address, "instances": [], "error": "Could not fetch instances"}


@app.get("/api/deployments")
async def list_deployments(authorization: Optional[str] = Header(None)):
    """List deployments for authenticated user only"""
    # SECURITY: Require authentication
    if not authorization:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    token = extract_token(authorization)
    session = get_session_from_token(token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    
    # Only return user's own deployments
    user_deployments = [
        d for d in DEPLOYMENTS.values() 
        if d.get("address", "").lower() == session["address"].lower()
    ]
    return {"deployments": user_deployments}


@app.get("/api/deployments/{deployment_id}")
async def get_deployment(deployment_id: str, authorization: Optional[str] = Header(None)):
    """Get deployment status"""
    if deployment_id not in DEPLOYMENTS:
        raise HTTPException(status_code=404, detail="Deployment not found")
    
    deployment = DEPLOYMENTS[deployment_id]
    
    # SECURITY: Require auth and verify ownership
    if not authorization:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    token = extract_token(authorization)
    session = get_session_from_token(token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    
    if deployment.get("address", "").lower() != session["address"].lower():
        raise HTTPException(status_code=403, detail="Not your deployment")
    
    return deployment


@app.get("/api/ssh-keys/{address}")
async def get_ssh_keys(address: str):
    """Get SSH keys stored on the Aleph network for an address"""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                "https://api2.aleph.im/api/v0/posts.json",
                params={
                    "addresses": address,
                    "types": "ALEPH-SSH",
                    "channels": "ALEPH-CLOUDSOLUTIONS",
                    "pagination": 50,
                    "page": 1,
                }
            )
            if response.status_code == 200:
                data = response.json()
                keys = []
                for post in data.get("posts", []):
                    content = post.get("content", {})
                    ssh_key = content.get("key", "")
                    label = content.get("label", content.get("name", "Unnamed Key"))
                    if ssh_key:
                        keys.append({
                            "key": ssh_key,
                            "label": label,
                            "hash": post.get("item_hash", ""),
                            "time": post.get("time"),
                        })
                return {
                    "address": address,
                    "keys": keys,
                    "total": data.get("pagination_total", len(keys)),
                }
    except Exception as e:
        pass
    return {"address": address, "keys": [], "error": "Could not fetch SSH keys"}


@app.get("/api/credits/{address}")
async def get_credits(address: str):
    """Get credit balance for an address from the Aleph network"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"https://api2.aleph.im/api/v0/addresses/{address}/balance"
            )
            if response.status_code == 200:
                data = response.json()
                return {
                    "address": address,
                    "balance": data.get("balance", 0),
                    "credit_balance": data.get("credit_balance", 0),
                    "locked_amount": data.get("locked_amount", 0),
                }
    except Exception as e:
        pass
    return {"address": address, "balance": None, "credit_balance": None, "error": "Could not fetch balance"}


@app.get("/api/crns")
async def list_crns():
    """Get available CRNs for instance allocation"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                "https://crns-list.aleph.sh/crns.json"
            )
            if response.status_code == 200:
                data = response.json()
                crns = []
                for node in data.get("crns", []):
                    if (node.get("payment_receiver_address") and
                            node.get("qemu_support")):
                        crns.append({
                            "hash": node.get("hash"),
                            "name": node.get("name"),
                            "url": node.get("address"),
                            "payment_address": node.get("payment_receiver_address"),
                            "stream_reward": node.get("stream_reward"),
                            "score": node.get("score", 0),
                        })
                crns.sort(key=lambda x: x.get("score", 0), reverse=True)
                return {"crns": crns, "count": len(crns)}
    except Exception as e:
        return {"crns": [], "error": str(e)}
    return {"crns": [], "error": "Failed to fetch CRNs"}


@app.post("/api/notify-allocation")
async def notify_crn_allocation(
    instance_hash: str,
    crn_url: str,
    authorization: Optional[str] = Header(None)
):
    """
    Try to notify a CRN about a new instance allocation.
    This is a best-effort proxy — CRN may require owner signature.
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Authentication required")

    token = extract_token(authorization)
    session = get_session_from_token(token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    if not crn_url.startswith("http"):
        crn_url = f"https://{crn_url}"
    crn_url = crn_url.rstrip("/")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{crn_url}/control/allocation/notify",
                json={"instance": instance_hash},
                timeout=15.0
            )
            status = "notified" if resp.status_code in (200, 201, 202) else "failed"
            print(f"[NOTIFY] {crn_url} hash={instance_hash[:16]}... => {resp.status_code} {resp.text[:200]}")
            return {
                "status": status,
                "crn_url": crn_url,
                "instance_hash": instance_hash,
                "crn_status": resp.status_code,
                "crn_response": resp.text[:500]
            }
    except Exception as e:
        print(f"[NOTIFY] {crn_url} hash={instance_hash[:16]}... => ERROR: {e}")
        return {
            "status": "notification_failed",
            "crn_url": crn_url,
            "instance_hash": instance_hash,
            "error": str(e)
        }


@app.get("/api/marketplace-key")
async def get_marketplace_key():
    """Get the marketplace's public SSH key for automated deployment"""
    key_path = os.path.expanduser("~/.ssh/id_rsa.pub")
    try:
        with open(key_path) as f:
            return {"key": f.read().strip()}
    except FileNotFoundError:
        return {"key": None, "error": "Marketplace SSH key not found on server"}


@app.get("/api/allocation/{instance_hash}")
async def get_allocation(instance_hash: str, crn_url: Optional[str] = None):
    """Get VM allocation info (IP) by querying the CRN directly or the scheduler"""
    import logging
    log = logging.getLogger("allocation")

    vm_ipv4 = None
    ssh_port = 22
    result = {"instance_hash": instance_hash, "allocated": False}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # If we know the CRN, query it directly first (skip slow scheduler)
            crn_urls_to_try = []
            if crn_url:
                url = crn_url if crn_url.startswith("http") else f"https://{crn_url}"
                crn_urls_to_try.append(url.rstrip("/"))

            # Query CRN execution list first (faster, more reliable for targeted instances)
            if crn_urls_to_try:
                for url in crn_urls_to_try:
                    for api_path in ["/v2/about/executions/list",
                                     "/about/executions/list"]:
                        try:
                            exec_resp = await client.get(
                                f"{url}{api_path}", timeout=10.0
                            )
                            if exec_resp.status_code == 200:
                                executions = exec_resp.json()
                                if isinstance(executions, dict) and instance_hash in executions:
                                    vm_data = executions[instance_hash]
                                    result["allocated"] = True
                                    net = vm_data.get("networking", {})
                                    vm_ipv4 = net.get("host_ipv4")
                                    mapped = net.get("mapped_ports", {})
                                    if "22" in mapped:
                                        ssh_port = mapped["22"].get("host", 22)
                                    log.info(f"CRN {url}: found instance, ip={vm_ipv4}, port={ssh_port}, running={vm_data.get('running')}")
                                    break
                                else:
                                    n = len(executions) if isinstance(executions, dict) else 'N/A'
                                    log.info(f"CRN {url}{api_path}: instance not in list ({n} executions)")
                            else:
                                log.warning(f"CRN {url}{api_path}: status {exec_resp.status_code}")
                            if vm_ipv4:
                                break
                        except Exception as e:
                            log.warning(f"CRN {url}{api_path}: error {e}")
                            continue
                    if vm_ipv4:
                        break

            # Fallback: try scheduler if CRN didn't have the info
            if not vm_ipv4:
                try:
                    alloc_response = await client.get(
                        "https://scheduler.api.aleph.cloud/api/v0/allocation",
                        params={"item_hash": instance_hash},
                        timeout=10.0
                    )
                    if alloc_response.status_code == 200:
                        alloc_data = alloc_response.json()
                        result["allocated"] = True
                        if isinstance(alloc_data, dict):
                            vm_ipv4 = (alloc_data.get("vm_ipv4")
                                       or alloc_data.get("ipv4")
                                       or alloc_data.get("ip"))
                            ssh_port = alloc_data.get("ssh_port", 22)
                            log.info(f"Scheduler: ip={vm_ipv4}")
                    else:
                        log.info(f"Scheduler: status {alloc_response.status_code}")
                except Exception as e:
                    log.info(f"Scheduler: error {e}")

            if vm_ipv4:
                result["vm_ipv4"] = vm_ipv4
                result["ssh_port"] = ssh_port

            return result
    except Exception as e:
        log.error(f"Allocation error: {e}")
        return {"instance_hash": instance_hash, "allocated": False, "error": str(e)}


# ============ Static Files & Dashboard ============

# Mount static files if directory exists
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Interactive marketplace dashboard"""
    return DASHBOARD_HTML


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
