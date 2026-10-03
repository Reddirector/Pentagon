from __future__ import annotations

import re
from dataclasses import dataclass


DEFAULT_NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"

_API_KEY_ASSIGNMENT = re.compile(r"\bapi_key\s*=\s*([\"'])([^\"']+)\1", re.IGNORECASE)
_BASE_URL_ASSIGNMENT = re.compile(r"\bbase_url\s*=\s*([\"'])([^\"']+)\1", re.IGNORECASE)
_MODEL_ASSIGNMENT = re.compile(r"\bmodel\s*=\s*([\"'])([^\"']+)\1", re.IGNORECASE)


@dataclass(frozen=True)
class ParsedNvidiaSnippet:
    api_key: str | None
    base_url: str
    model: str | None


def parse_nvidia_snippet(raw_snippet: str) -> ParsedNvidiaSnippet:
    source = raw_snippet.replace(r"\_", "_")
    key_match = _API_KEY_ASSIGNMENT.search(source)
    key = key_match.group(2).strip() if key_match else None
    if key is None:
        stripped = source.strip()
        if stripped.startswith("nvapi-"):
            key = stripped.split()[0].strip("\"',")

    base_match = _BASE_URL_ASSIGNMENT.search(source)
    base_url = base_match.group(2).strip() if base_match else DEFAULT_NVIDIA_BASE_URL
    markdown_link = re.fullmatch(r"\[([^\]]+)\]\(([^)]+)\)", base_url)
    if markdown_link:
        base_url = markdown_link.group(2).strip()
    base_url = base_url.rstrip("/") or DEFAULT_NVIDIA_BASE_URL

    model_match = _MODEL_ASSIGNMENT.search(source)
    model = model_match.group(2).strip() if model_match else None
    return ParsedNvidiaSnippet(api_key=key, base_url=base_url, model=model or None)
