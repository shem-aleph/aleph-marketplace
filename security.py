"""
Security utilities for Aleph Cloud Marketplace
"""
import re
import ipaddress
import secrets
import base64
import shlex
import time
from typing import Optional
from collections import defaultdict
from fastapi import HTTPException, Request


# ============ Input Validation ============

def sanitize_app_name(app_name: str) -> str:
    """
    Sanitize app name to prevent command injection and path traversal.
    Only allows alphanumeric, dash, underscore.
    """
    if not app_name:
        raise ValueError("App name cannot be empty")
    
    if not re.match(r'^[a-zA-Z0-9_-]+$', app_name):
        raise ValueError(
            f"Invalid app name: '{app_name}'. "
            "Only alphanumeric characters, dashes, and underscores allowed."
        )
    
    if len(app_name) > 64:
        raise ValueError("App name too long (max 64 characters)")
    
    # Extra safety: block any path traversal attempts
    if '..' in app_name or '/' in app_name or '\\' in app_name:
        raise ValueError("Invalid characters in app name")
    
    return app_name


def validate_eth_address(address: str) -> str:
    """
    Validate and normalize Ethereum address.
    Returns lowercase address.
    """
    if not address:
        raise HTTPException(status_code=400, detail="Address cannot be empty")
    
    if not re.match(r'^0x[a-fA-F0-9]{40}$', address):
        raise HTTPException(
            status_code=400, 
            detail="Invalid Ethereum address format. Must be 0x followed by 40 hex characters."
        )
    
    return address.lower()


import os

# Allow internal SSH for self-deployment (dogfooding)
# Set ALLOW_INTERNAL_SSH=1 to enable
ALLOW_INTERNAL_SSH = os.environ.get("ALLOW_INTERNAL_SSH", "0") == "1"

def validate_ssh_host(host: str) -> str:
    """
    Validate SSH host to prevent SSRF attacks.
    Blocks internal IPs, localhost, and cloud metadata endpoints.
    Set ALLOW_INTERNAL_SSH=1 env var to allow localhost (for self-deployment).
    """
    if not host:
        raise ValueError("SSH host cannot be empty")
    
    # Normalize
    host = host.lower().strip()
    
    # Block obvious localhost variants (unless internal SSH is allowed)
    localhost_patterns = ['localhost', '127.0.0.1', '::1', '0.0.0.0']
    if host in localhost_patterns:
        if ALLOW_INTERNAL_SSH:
            return host  # Allow for self-deployment
        raise ValueError("Localhost not allowed as SSH target")
    
    # Block cloud metadata endpoints
    blocked_hosts = [
        '169.254.169.254',      # AWS/GCP/Azure metadata
        'metadata.google.internal',
        '100.100.100.200',      # Alibaba Cloud
        'metadata.azure.com',
    ]
    if host in blocked_hosts:
        raise ValueError(f"Blocked host: {host}")
    
    # Try to parse as IP and check for internal ranges
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private:
            raise ValueError(f"Private IP addresses not allowed: {host}")
        if ip.is_loopback:
            raise ValueError(f"Loopback addresses not allowed: {host}")
        if ip.is_link_local:
            raise ValueError(f"Link-local addresses not allowed: {host}")
        if ip.is_reserved:
            raise ValueError(f"Reserved addresses not allowed: {host}")
    except ValueError as e:
        if "not allowed" in str(e):
            raise
        # It's a hostname, not an IP - that's fine
        pass
    
    return host


def validate_port(port: int) -> int:
    """Validate port number"""
    if not isinstance(port, int) or port < 1 or port > 65535:
        raise ValueError(f"Invalid port: {port}. Must be 1-65535.")
    return port


# ============ Safe Command Building ============

def safe_shell_arg(value: str) -> str:
    """Safely quote a value for shell use"""
    return shlex.quote(value)


def safe_write_file_command(content: str, filepath: str) -> str:
    """
    Generate a safe command to write file content.
    Uses base64 encoding to prevent any injection.
    """
    # Base64 encode the content to prevent any shell interpretation
    encoded = base64.b64encode(content.encode()).decode()
    safe_path = shlex.quote(filepath)
    return f"echo '{encoded}' | base64 -d > {safe_path}"


def generate_heredoc_delimiter() -> str:
    """Generate a random heredoc delimiter to prevent injection"""
    return f"EOF_{secrets.token_hex(8)}"


# ============ Rate Limiting ============

class RateLimiter:
    """Simple in-memory rate limiter"""
    
    def __init__(self):
        self.requests = defaultdict(list)
    
    def check(
        self, 
        key: str, 
        max_requests: int = 10, 
        window_seconds: int = 60
    ) -> bool:
        """
        Check if request is allowed.
        Returns True if allowed, raises HTTPException if rate limited.
        """
        now = time.time()
        
        # Clean old entries
        self.requests[key] = [
            t for t in self.requests[key] 
            if now - t < window_seconds
        ]
        
        if len(self.requests[key]) >= max_requests:
            raise HTTPException(
                status_code=429, 
                detail=f"Too many requests. Max {max_requests} per {window_seconds} seconds."
            )
        
        self.requests[key].append(now)
        return True
    
    def get_client_key(self, request: Request, prefix: str = "") -> str:
        """Get a rate limit key for a client"""
        client_ip = request.client.host if request.client else "unknown"
        return f"{prefix}:{client_ip}"


# Global rate limiter instance
rate_limiter = RateLimiter()


# ============ Auth Helpers ============

def require_eth_account():
    """Raise error if eth_account is not available"""
    # Import here to check availability
    try:
        from eth_account import Account
        return True
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="Authentication service unavailable. eth_account library not installed."
        )


def extract_token(authorization: Optional[str]) -> Optional[str]:
    """Extract token from Authorization header"""
    if not authorization:
        return None
    if authorization.startswith("Bearer "):
        return authorization[7:]
    return authorization
