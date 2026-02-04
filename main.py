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

from fastapi import FastAPI, HTTPException, BackgroundTasks, Header
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
import httpx

from deployer import deploy as deploy_to_aleph, orchestrator, AlephDeployer

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
    version="0.2.0"
)

# Load app templates
TEMPLATES_PATH = Path(__file__).parent / "templates" / "apps.json"
with open(TEMPLATES_PATH) as f:
    APP_DATA = json.load(f)

APPS = {app["id"]: app for app in APP_DATA["apps"]}
CATEGORIES = APP_DATA["categories"]

# In-memory deployments
DEPLOYMENTS = {}

# ============ Web3 Auth Storage ============
AUTH_NONCES = {}
AUTH_SESSIONS = {}
SESSION_EXPIRY_SECONDS = 86400
NONCE_EXPIRY_SECONDS = 300

# Aleph API base
ALEPH_API_URL = "https://api2.aleph.im/api/v0"


class SSHInfo(BaseModel):
    host: str
    port: int = 22
    user: str = "root"


class DeployRequest(BaseModel):
    app_id: str
    address: str
    instance_name: Optional[str] = None
    ssh_info: Optional[SSHInfo] = None
    ssh_pubkey: Optional[str] = None


class Deployment(BaseModel):
    id: str
    app_id: str
    address: str
    instance_name: str
    status: str
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
    now = time.time()
    expired = [addr for addr, data in AUTH_NONCES.items() 
               if now - data["created_at"] > NONCE_EXPIRY_SECONDS]
    for addr in expired:
        del AUTH_NONCES[addr]


def cleanup_expired_sessions():
    now = time.time()
    expired = [token for token, data in AUTH_SESSIONS.items() 
               if now > data["expires_at"]]
    for token in expired:
        del AUTH_SESSIONS[token]


def generate_nonce() -> str:
    return secrets.token_hex(16)


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


def verify_signature(address: str, message: str, signature: str) -> bool:
    if not ETH_ACCOUNT_AVAILABLE:
        return True
    try:
        message_encoded = encode_defunct(text=message)
        recovered_address = Account.recover_message(message_encoded, signature=signature)
        return recovered_address.lower() == address.lower()
    except Exception as e:
        print(f"Signature verification failed: {e}")
        return False


def get_session_from_token(token: str) -> Optional[dict]:
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
async def get_auth_nonce(request: NonceRequest):
    cleanup_expired_nonces()
    address = request.address.lower()
    if not address.startswith("0x") or len(address) != 42:
        raise HTTPException(status_code=400, detail="Invalid Ethereum address")
    
    nonce = generate_nonce()
    message = f"Sign this message to authenticate with Aleph Marketplace.\n\nNonce: {nonce}\nAddress: {address}"
    
    AUTH_NONCES[address] = {"nonce": nonce, "created_at": time.time()}
    return NonceResponse(nonce=nonce, message=message)


@app.post("/api/auth/verify", response_model=VerifyResponse)
async def verify_auth(request: VerifyRequest):
    cleanup_expired_nonces()
    address = request.address.lower()
    
    if address not in AUTH_NONCES:
        raise HTTPException(status_code=400, detail="No pending nonce. Request a new nonce.")
    
    stored_nonce = AUTH_NONCES[address]
    
    if time.time() - stored_nonce["created_at"] > NONCE_EXPIRY_SECONDS:
        del AUTH_NONCES[address]
        raise HTTPException(status_code=400, detail="Nonce expired.")
    
    if stored_nonce["nonce"] != request.nonce:
        raise HTTPException(status_code=400, detail="Invalid nonce")
    
    expected_message = f"Sign this message to authenticate with Aleph Marketplace.\n\nNonce: {request.nonce}\nAddress: {address}"
    
    if not verify_signature(address, expected_message, request.signature):
        raise HTTPException(status_code=401, detail="Invalid signature")
    
    del AUTH_NONCES[address]
    
    token = generate_session_token()
    expires_at = time.time() + SESSION_EXPIRY_SECONDS
    AUTH_SESSIONS[token] = {"address": address, "created_at": time.time(), "expires_at": expires_at}
    
    return VerifyResponse(token=token, address=address, expires_at=expires_at)


@app.get("/api/auth/session", response_model=SessionInfo)
async def get_session_info(authorization: Optional[str] = Header(None)):
    if not authorization:
        return SessionInfo(address="", authenticated=False)
    token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization
    session = get_session_from_token(token)
    if not session:
        return SessionInfo(address="", authenticated=False)
    return SessionInfo(address=session["address"], authenticated=True, expires_at=session["expires_at"])


@app.post("/api/auth/logout")
async def logout(authorization: Optional[str] = Header(None)):
    if not authorization:
        return {"success": True}
    token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization
    if token in AUTH_SESSIONS:
        del AUTH_SESSIONS[token]
    return {"success": True}


# ============ Credits API ============

@app.get("/api/credits/{address}")
async def get_credits(address: str):
    """Get credit balance for an address from the Aleph network."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{ALEPH_API_URL}/addresses/{address}/balance"
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


# ============ SSH Keys API ============

@app.get("/api/ssh-keys/{address}")
async def get_ssh_keys(address: str):
    """
    Fetch user's SSH keys stored on the Aleph network.
    These are POST messages of type ALEPH-SSH in channel ALEPH-CLOUDSOLUTIONS.
    """
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{ALEPH_API_URL}/posts.json",
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
                    key_data = content.get("key", "")
                    label = content.get("label", "Unnamed Key")
                    if key_data:
                        keys.append({
                            "key": key_data,
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


# ============ Allocation Status API ============

@app.get("/api/allocation/{instance_hash}")
async def get_allocation_status(instance_hash: str):
    """
    Get VM allocation info including IP addresses from the scheduler and CRN.
    """
    deployer = AlephDeployer()
    
    result = {
        "instance_hash": instance_hash,
        "status": "checking",
    }
    
    # Check scheduler allocation
    allocation = await deployer.get_allocation(instance_hash)
    if allocation:
        result["allocation"] = allocation
        result["vm_ipv6"] = allocation.get("vm_ipv6")
        
        node = allocation.get("node", {})
        crn_url = node.get("url") or node.get("address")
        
        if crn_url:
            result["crn_url"] = crn_url
            # Get full networking from CRN
            networking = await deployer.get_vm_networking_from_crn(crn_url, instance_hash)
            if networking:
                result["networking"] = networking
                result["status"] = "allocated"
            else:
                result["status"] = "allocated_no_networking"
        else:
            result["status"] = "allocated"
    else:
        result["status"] = "not_allocated"
    
    return result


# ============ App Routes ============

@app.get("/")
async def home():
    """Serve the marketplace frontend (dashboard)."""
    return await dashboard()


@app.get("/api/apps")
async def list_apps(category: Optional[str] = None):
    apps = list(APPS.values())
    if category:
        apps = [a for a in apps if a["category"] == category]
    return {"apps": apps, "categories": CATEGORIES}


@app.get("/api/apps/{app_id}")
async def get_app(app_id: str):
    if app_id not in APPS:
        raise HTTPException(status_code=404, detail="App not found")
    return APPS[app_id]


@app.post("/api/deploy")
async def deploy_app(request: DeployRequest, background_tasks: BackgroundTasks):
    """Deploy an app. If SSH pubkey provided, will create instance and auto-deploy."""
    if request.app_id not in APPS:
        raise HTTPException(status_code=404, detail="App not found")
    
    app_config = APPS[request.app_id]
    ssh_info = request.ssh_info.dict() if request.ssh_info else None
    
    result = await deploy_to_aleph(
        app=app_config,
        address=request.address,
        instance_name=request.instance_name or f"{app_config['name']} Instance",
        ssh_info=ssh_info,
        ssh_pubkey=request.ssh_pubkey,
    )
    
    # Store deployment
    DEPLOYMENTS[result["deployment_id"]] = {
        **result,
        "app_id": request.app_id,
        "address": request.address,
        "instance_name": request.instance_name,
        "created_at": datetime.utcnow().isoformat()
    }
    
    # If instance was created, start background polling for IP + auto-deploy
    if result.get("status") == "instance_created" and result.get("instance_hash"):
        background_tasks.add_task(
            _background_poll_and_deploy,
            deployment_id=result["deployment_id"],
            app=app_config,
            instance_hash=result["instance_hash"],
            crn_url=result.get("crn_url"),
        )
    
    return result


async def _background_poll_and_deploy(
    deployment_id: str, app: dict, instance_hash: str, crn_url: Optional[str]
):
    """Background task to poll for VM IP and deploy the app."""
    try:
        result = await orchestrator.poll_and_deploy(
            deployment_id=deployment_id,
            app=app,
            instance_hash=instance_hash,
            crn_url=crn_url,
        )
        # Update stored deployment
        if deployment_id in DEPLOYMENTS:
            DEPLOYMENTS[deployment_id].update(result)
    except Exception as e:
        if deployment_id in DEPLOYMENTS:
            DEPLOYMENTS[deployment_id]["status"] = "error"
            DEPLOYMENTS[deployment_id]["error"] = str(e)


@app.post("/api/deploy/execute")
async def execute_deployment(deployment_id: str, ssh_info: SSHInfo):
    """Execute deployment on an existing instance via SSH."""
    if deployment_id not in orchestrator.deployments:
        raise HTTPException(status_code=404, detail="Deployment not found")
    
    deployment = orchestrator.deployments[deployment_id]
    app_name = deployment_id.split("-")[0]
    if app_name not in APPS:
        raise HTTPException(status_code=404, detail="App not found")
    
    app_config = APPS[app_name]
    deployer = AlephDeployer()
    
    compose_result = await deployer.deploy_docker_compose(
        ssh_host=ssh_info.host,
        ssh_port=ssh_info.port,
        ssh_user=ssh_info.user,
        compose_content=app_config["docker_compose"],
        app_name=app_config["id"]
    )
    
    tunnel_result = await deployer.setup_cloudflare_tunnel(
        ssh_host=ssh_info.host,
        ssh_port=ssh_info.port,
        ssh_user=ssh_info.user,
        local_port=80
    )
    
    return {
        "deployment_id": deployment_id,
        "ssh_connection": f"ssh -p {ssh_info.port} {ssh_info.user}@{ssh_info.host}",
        "deploy_script": compose_result["deploy_script"],
        "tunnel_script": tunnel_result["tunnel_script"],
    }


@app.get("/api/deployments")
async def list_deployments(address: Optional[str] = None):
    deployments = list(DEPLOYMENTS.values())
    if address:
        deployments = [d for d in deployments if d.get("address", "").lower() == address.lower()]
    return {"deployments": deployments}


@app.get("/api/deployments/{deployment_id}")
async def get_deployment(deployment_id: str):
    if deployment_id not in DEPLOYMENTS:
        raise HTTPException(status_code=404, detail="Deployment not found")
    return DEPLOYMENTS[deployment_id]


# ============ Dashboard ============

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Interactive marketplace dashboard with credit balance + SSH key support."""
    html_path = Path(__file__).parent / "templates" / "dashboard.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text())
    return HTMLResponse("<h1>Dashboard template not found</h1>")


# Mount static files if directory exists
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
