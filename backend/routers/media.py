"""
All_Chat - Media Router
Link preview unfurling (Open Graph + fallback meta scraping).
Server-side fetch prevents SSRF from client — we validate URLs strictly.
"""

import re
import ipaddress
import socket
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import Optional

from core.deps import get_current_user
from models.user import User

router = APIRouter()

# Timeout for external fetches
FETCH_TIMEOUT = 5.0
MAX_RESPONSE_SIZE = 500_000  # 500KB — enough for HTML head

# Block private/internal IP ranges (SSRF protection)
BLOCKED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),        # this network
    ipaddress.ip_network("10.0.0.0/8"),        # RFC1918 private
    ipaddress.ip_network("100.64.0.0/10"),     # shared address space
    ipaddress.ip_network("127.0.0.0/8"),       # loopback
    ipaddress.ip_network("169.254.0.0/16"),    # link-local
    ipaddress.ip_network("172.16.0.0/12"),     # RFC1918 private
    ipaddress.ip_network("192.168.0.0/16"),    # RFC1918 private
    ipaddress.ip_network("198.18.0.0/15"),     # benchmark
    ipaddress.ip_network("198.51.100.0/24"),   # TEST-NET-2
    ipaddress.ip_network("203.0.113.0/24"),    # TEST-NET-3
    ipaddress.ip_network("240.0.0.0/4"),       # reserved
    ipaddress.ip_network("::1/128"),           # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),          # IPv6 unique local
    ipaddress.ip_network("fe80::/10"),         # IPv6 link-local
    ipaddress.ip_network("::ffff:0:0/96"),     # IPv4-mapped IPv6
]


class LinkPreview(BaseModel):
    url: str
    title: Optional[str] = None
    description: Optional[str] = None
    image: Optional[str] = None
    site_name: Optional[str] = None


def _validate_url(url: str) -> str:
    """Strict URL validation. Blocks private IPs (SSRF protection)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Only http/https URLs allowed.")
    if not parsed.netloc:
        raise HTTPException(status_code=400, detail="Invalid URL.")

    hostname = parsed.hostname
    if not hostname:
        raise HTTPException(status_code=400, detail="Invalid hostname.")

    # Resolve and check IP
    try:
        resolved_ip = socket.gethostbyname(hostname)
        ip = ipaddress.ip_address(resolved_ip)
        for network in BLOCKED_NETWORKS:
            if ip in network:
                raise HTTPException(status_code=400, detail="URL resolves to a private address.")
    except socket.gaierror:
        raise HTTPException(status_code=400, detail="Could not resolve hostname.")

    return url


@router.get("/preview", response_model=LinkPreview)
async def link_preview(
    url: str = Query(..., max_length=2048),
    _: User = Depends(get_current_user),  # must be logged in to fetch previews
):
    """Fetch Open Graph / meta tags for a URL and return preview data."""
    validated_url = _validate_url(url)

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; AllChat/1.0; +https://allchat.local/bot)",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.5",
    }

    try:
        async with httpx.AsyncClient(
            timeout=FETCH_TIMEOUT,
            follow_redirects=True,
            max_redirects=3,
        ) as client:
            response = await client.get(
                validated_url,
                headers=headers,
            )
            # Validate the final URL after any redirects (open redirect SSRF)
            if str(response.url) != validated_url:
                _validate_url(str(response.url))
            response.raise_for_status()
            content = response.text[:MAX_RESPONSE_SIZE]
    except HTTPException:
        raise
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="URL timed out.")
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Could not fetch URL.")

    soup = BeautifulSoup(content, "html.parser")

    def og(prop: str) -> Optional[str]:
        tag = soup.find("meta", property=f"og:{prop}")
        if tag and tag.get("content"):
            return str(tag["content"])[:500]
        return None

    def meta(name: str) -> Optional[str]:
        tag = soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            return str(tag["content"])[:500]
        return None

    title = (
        og("title")
        or meta("title")
        or (soup.title.string[:200] if soup.title else None)
    )
    description = og("description") or meta("description")
    image = og("image")
    site_name = og("site_name")

    # Validate image URL if present
    if image:
        try:
            _validate_url(image)
        except HTTPException:
            image = None

    return LinkPreview(
        url=validated_url,
        title=title,
        description=description,
        image=image,
        site_name=site_name,
    )
