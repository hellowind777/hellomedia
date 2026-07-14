"""HelloMedia runtime auth discovery (Codex / Hermes / OpenClaw / env / CLI)."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

BASE_URL_ENV = ("OPENAI_BASE_URL", "GPT_BASE_URL", "BASE_URL")
API_KEY_ENV = ("OPENAI_API_KEY", "GPT_API_KEY", "API_KEY")
MODEL_ENV = ("OPENAI_IMAGE_MODEL", "OPENAI_MODEL", "GPT_MODEL")
ACCOUNT_ID_ENV = ("OPENAI_ACCOUNT_ID", "CHATGPT_ACCOUNT_ID")
CLIENT_VERSION_ENV = ("HELLOMEDIA_CLIENT_VERSION", "OPENAI_CLIENT_VERSION")
ORIGINATOR_ENV = ("HELLOMEDIA_ORIGINATOR", "OPENAI_ORIGINATOR")
DEFAULT_BASE_URL = "https://api.openai.com"
DEFAULT_MANAGED_CLIENT_VERSION = "0.122.0"
DEFAULT_MANAGED_ORIGINATOR = "codex_cli_rs"
CODEX_OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
CODEX_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_TOKEN_REFRESH_SKEW_SECONDS = 120
CODEX_KEYRING_SERVICE = "Codex Auth"
OPENCLAW_STATE_ENV = "OPENCLAW_STATE_DIR"
OPENCLAW_AGENT_ENV = "OPENCLAW_AGENT_DIR"
OPENCLAW_ALT_AGENT_ENV = "PI_CODING_AGENT_DIR"
OPENCLAW_OAUTH_DIR_ENV = "OPENCLAW_OAUTH_DIR"
HERMES_HOME_ENV = "HERMES_HOME"
MANAGED_AUTH_SENTINELS = {
    "PROXY_MANAGED",
    "OPENAI_MANAGED",
    "OPENAI_AUTH_MANAGED",
    "HOST_MANAGED",
    "ACCOUNT_MANAGED",
    "USE_HOST_AUTH",
    "USE_OPENAI_AUTH",
}
ENDPOINT_SUFFIXES = (
    "/v1/responses",
    "/v1/chat/completions",
    "/v1/images/generations",
    "/v1/images/edits",
    "/responses",
    "/chat/completions",
    "/images/generations",
    "/images/edits",
)
ENDPOINT_PATH_SUFFIXES = {
    "responses": "/responses",
    "chat": "/chat/completions",
    "images": "/images/generations",
    "images-edits": "/images/edits",
}
def first_value(names: tuple[str, ...]) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None

def default_codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")

def coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return None

def strip_known_endpoint_suffix(path: str) -> str:
    normalized = re.sub(r"/+$", "", path or "")
    changed = True
    while changed and normalized:
        changed = False
        lowered = normalized.lower()
        for suffix in ENDPOINT_SUFFIXES:
            if lowered.endswith(suffix):
                normalized = normalized[: -len(suffix)]
                changed = True
                break
        lowered = normalized.lower()
        if lowered.endswith("/v1"):
            normalized = normalized[:-3]
            changed = True
    return normalized.rstrip("/")

def normalize_base_url(value: str | None) -> str:
    raw = (value or DEFAULT_BASE_URL).strip()
    if not raw.startswith(("http://", "https://")):
        raise ValueError("Base URL must start with http:// or https://")
    parsed = urlparse(raw)
    normalized_path = strip_known_endpoint_suffix(parsed.path)
    normalized = parsed._replace(path=normalized_path, params="", query="", fragment="")
    return urlunparse(normalized).rstrip("/")

def infer_endpoint_style_hint(raw_url: str | None) -> str | None:
    if not raw_url:
        return None
    parsed = urlparse(raw_url.strip())
    path = re.sub(r"/+$", "", parsed.path or "")
    if not path or path == "/":
        return None
    lowered = path.lower()
    if lowered.endswith("/v1"):
        return "v1"
    if any(lowered.endswith(f"/v1{suffix}") for suffix in ENDPOINT_PATH_SUFFIXES.values()):
        return "v1"
    if any(lowered.endswith(suffix) for suffix in ENDPOINT_PATH_SUFFIXES.values()):
        return "plain"
    return "plain"

def is_official_openai_base_url(base_url: str) -> bool:
    parsed = urlparse(base_url.rstrip("/"))
    return parsed.scheme in {"http", "https"} and parsed.netloc.lower() == "api.openai.com" and (
        parsed.path in {"", "/"}
    )

def is_chatgpt_codex_base_url(base_url: str) -> bool:
    parsed = urlparse(base_url.rstrip("/"))
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != "chatgpt.com":
        return False
    normalized_path = strip_known_endpoint_suffix(parsed.path).lower()
    return normalized_path in {
        "/backend-api",
        "/backend-api/codex",
    }

def is_local_openai_auth_proxy(base_url: str, *, requires_openai_auth: bool = False) -> bool:
    return bool(requires_openai_auth) and is_localish_base_url(base_url)

def endpoint_root_path(base_url: str) -> str:
    parsed = urlparse(base_url.rstrip("/"))
    return strip_known_endpoint_suffix(parsed.path)

def build_endpoint_url_variants(
    base_url: str,
    endpoint: str,
    *,
    style_hint: str | None = None,
    allow_plain_variant: bool = False,
) -> list[tuple[str, str]]:
    root = base_url.rstrip("/")
    parsed = urlparse(root)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"Unsupported base URL: {base_url}")

    path_root = endpoint_root_path(root)
    suffix = ENDPOINT_PATH_SUFFIXES.get(endpoint)
    if suffix is None:
        raise ValueError(f"Unknown endpoint kind: {endpoint}")

    if is_chatgpt_codex_base_url(root):
        path_variants = [("chatgpt", f"{path_root}{suffix}")]
    elif is_official_openai_base_url(root):
        path_variants = [("v1", f"{path_root}/v1{suffix}")]
    else:
        v1_path = f"{path_root}/v1{suffix}"
        plain_path = f"{path_root}{suffix}"
        if allow_plain_variant:
            if style_hint == "v1":
                path_variants = [("v1", v1_path), ("plain", plain_path)]
            elif style_hint == "plain":
                path_variants = [("plain", plain_path), ("v1", v1_path)]
            else:
                path_variants = [("plain", plain_path), ("v1", v1_path)]
        else:
            path_variants = [("v1", v1_path)]

    variants: list[tuple[str, str]] = []
    seen: set[str] = set()
    for route_style, path in path_variants:
        url = urlunparse(parsed._replace(path=path, params="", query="", fragment=""))
        if url in seen:
            continue
        seen.add(url)
        variants.append((route_style, url))
    return variants

def build_endpoint_url(base_url: str, endpoint: str) -> str:
    return build_endpoint_url_variants(base_url, endpoint)[0][1]

def is_localish_base_url(base_url: str) -> bool:
    parsed = urlparse(base_url)
    host = (parsed.hostname or "").lower()
    if host in {"127.0.0.1", "localhost", "::1", "host.docker.internal", "host.containers.internal"}:
        return True
    if host.endswith(".local") or host.endswith(".lan") or host.endswith(".internal"):
        return True
    if host.startswith("10.") or host.startswith("192.168."):
        return True
    match = re.match(r"^172\.(\d{1,2})\.", host)
    if match:
        try:
            second = int(match.group(1))
        except ValueError:
            second = -1
        if 16 <= second <= 31:
            return True
    return False

def load_toml(path: Path) -> dict[str, Any] | None:
    try:
        import tomllib

        return tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

def read_json_file(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None

def read_codex_config(codex_home: Path, provider_name: str | None = None) -> dict[str, Any]:
    config_path = codex_home / "config.toml"
    auth_path = codex_home / "auth.json"
    result: dict[str, Any] = {}

    if config_path.exists():
        parsed = load_toml(config_path)
        if parsed:
            result["default_model"] = parsed.get("model")
            provider = provider_name or parsed.get("model_provider")
            providers = parsed.get("model_providers") or {}
            provider_cfg = providers.get(provider) if provider else None
            if isinstance(provider_cfg, dict):
                result["base_url"] = provider_cfg.get("base_url")
                result["endpoint_style_hint"] = infer_endpoint_style_hint(provider_cfg.get("base_url"))
                result["provider"] = provider
                result["max_resolution"] = provider_cfg.get("image_max_resolution") or provider_cfg.get("max_image_resolution")
                result["responses_model"] = provider_cfg.get("image_responses_model") or provider_cfg.get("responses_model")
                result["chat_model"] = provider_cfg.get("image_chat_model") or provider_cfg.get("chat_model")
                result["wire_api"] = provider_cfg.get("wire_api")
                result["requires_openai_auth"] = coerce_bool(provider_cfg.get("requires_openai_auth"))
                result["api_key_hint"] = provider_cfg.get("experimental_bearer_token")
        else:
            raw = config_path.read_text(encoding="utf-8", errors="replace")
            provider = provider_name
            if not provider:
                marker = 'model_provider = "'
                if marker in raw:
                    provider = raw.split(marker, 1)[1].split('"', 1)[0]
            if provider:
                block = f"[model_providers.{provider}]"
                if block in raw:
                    tail = raw.split(block, 1)[1]
                    if 'base_url = "' in tail:
                        result["base_url"] = tail.split('base_url = "', 1)[1].split('"', 1)[0]
                        result["endpoint_style_hint"] = infer_endpoint_style_hint(result["base_url"])
                    result["provider"] = provider

    if auth_path.exists():
        try:
            auth = json.loads(auth_path.read_text(encoding="utf-8"))
            result["api_key"] = auth.get("OPENAI_API_KEY") or auth.get("api_key")
            if isinstance(auth.get("tokens"), dict):
                result["codex_tokens_present"] = True
        except Exception:
            pass

    return result

def decode_jwt_claims(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    try:
        payload_raw = parts[1] + "=" * (-len(parts[1]) % 4)
        decoded = base64.urlsafe_b64decode(payload_raw.encode("utf-8")).decode("utf-8", errors="replace")
        payload = json.loads(decoded)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}

def decode_jwt_expiry_ms(token: str) -> int | None:
    claims = decode_jwt_claims(token)
    exp = claims.get("exp")
    if isinstance(exp, (int, float)) and exp > 0:
        return int(exp * 1000)
    return None

def token_is_expiring(token: str, skew_seconds: int = CODEX_TOKEN_REFRESH_SKEW_SECONDS) -> bool:
    expiry_ms = decode_jwt_expiry_ms(token)
    if expiry_ms is None:
        return False
    return expiry_ms <= int(time.time() * 1000) + (skew_seconds * 1000)

def extract_chatgpt_account_id(token: str | None) -> str | None:
    if not token:
        return None
    claims = decode_jwt_claims(token)
    direct = claims.get("chatgpt_account_id")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    nested = claims.get("https://api.openai.com/auth")
    if isinstance(nested, dict):
        account_id = nested.get("chatgpt_account_id")
        if isinstance(account_id, str) and account_id.strip():
            return account_id.strip()
    flat = claims.get("https://api.openai.com/auth.chatgpt_account_id")
    if isinstance(flat, str) and flat.strip():
        return flat.strip()
    return None

def sanitize_originator(value: str | None) -> str:
    return (value or DEFAULT_MANAGED_ORIGINATOR).strip() or DEFAULT_MANAGED_ORIGINATOR

def sanitize_client_version(value: str | None) -> str:
    return (value or DEFAULT_MANAGED_CLIENT_VERSION).strip() or DEFAULT_MANAGED_CLIENT_VERSION

def looks_like_managed_sentinel(value: str | None) -> bool:
    return isinstance(value, str) and value.strip() in MANAGED_AUTH_SENTINELS

def safe_canonical_string(path: Path) -> str:
    try:
        resolved = path.expanduser().resolve()
    except Exception:
        resolved = path.expanduser()
    return str(resolved)

def compute_codex_keyring_account(codex_home: Path) -> str:
    digest = hashlib.sha256(safe_canonical_string(codex_home).encode("utf-8")).hexdigest()
    return f"cli|{digest[:16]}"

def extract_chatgpt_account_id_from_claims(claims: Any) -> str | None:
    if not isinstance(claims, dict):
        return None
    direct = claims.get("chatgpt_account_id")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    nested = claims.get("https://api.openai.com/auth")
    if isinstance(nested, dict):
        account_id = nested.get("chatgpt_account_id")
        if isinstance(account_id, str) and account_id.strip():
            return account_id.strip()
    flat = claims.get("https://api.openai.com/auth.chatgpt_account_id")
    if isinstance(flat, str) and flat.strip():
        return flat.strip()
    return None

def normalize_codex_auth_mode(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower().replace("-", "_")
    aliases = {
        "apikey": "api_key",
        "api": "api_key",
        "chatgptauthtokens": "chatgpt_auth_tokens",
        "agentidentity": "agent_identity",
    }
    return aliases.get(normalized, normalized) or None

def decode_possible_jwt_claims(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        return decode_jwt_claims(value.strip())
    return {}

def format_rfc3339_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def codex_windows_target_names(service: str, account: str) -> list[str]:
    target = f"{account}.{service}"
    return [target, f"LegacyGeneric:target={target}"]

def read_windows_generic_credential(target_names: list[str]) -> tuple[str, str] | None:
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return None

    CRED_TYPE_GENERIC = 1

    class FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

    class CREDENTIALW(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.c_void_p),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    advapi32 = ctypes.WinDLL("Advapi32.dll")
    cred_read = advapi32.CredReadW
    cred_read.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
    cred_read.restype = wintypes.BOOL
    cred_free = advapi32.CredFree
    cred_free.argtypes = [ctypes.c_void_p]
    cred_free.restype = None

    for target_name in target_names:
        pointer = ctypes.c_void_p()
        if not cred_read(target_name, CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)):
            continue
        try:
            credential = ctypes.cast(pointer, ctypes.POINTER(CREDENTIALW)).contents
            raw = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
            try:
                secret = raw.decode("utf-16-le")
            except UnicodeDecodeError:
                secret = raw.decode("utf-8", errors="replace")
            return secret, str(credential.TargetName or target_name)
        finally:
            cred_free(pointer)
    return None

def write_windows_generic_credential(target_name: str, username: str, secret: str) -> None:
    import ctypes
    from ctypes import wintypes

    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2

    class FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

    class CREDENTIAL_ATTRIBUTEW(ctypes.Structure):
        _fields_ = [
            ("Keyword", wintypes.LPWSTR),
            ("Flags", wintypes.DWORD),
            ("ValueSize", wintypes.DWORD),
            ("Value", ctypes.c_void_p),
        ]

    class CREDENTIALW(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.c_void_p),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.POINTER(CREDENTIAL_ATTRIBUTEW)),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    encoded = secret.encode("utf-16-le")
    buffer = ctypes.create_string_buffer(encoded)
    credential = CREDENTIALW()
    credential.Flags = 0
    credential.Type = CRED_TYPE_GENERIC
    credential.TargetName = target_name
    credential.Comment = service_comment = CODEX_KEYRING_SERVICE
    credential.CredentialBlobSize = len(encoded)
    credential.CredentialBlob = ctypes.cast(buffer, ctypes.c_void_p)
    credential.Persist = CRED_PERSIST_LOCAL_MACHINE
    credential.AttributeCount = 0
    credential.Attributes = None
    credential.TargetAlias = None
    credential.UserName = username

    advapi32 = ctypes.WinDLL("Advapi32.dll")
    cred_write = advapi32.CredWriteW
    cred_write.argtypes = [ctypes.POINTER(CREDENTIALW), wintypes.DWORD]
    cred_write.restype = wintypes.BOOL
    if not cred_write(ctypes.byref(credential), 0):
        raise OSError("CredWriteW failed while updating Codex auth keyring entry.")

def read_macos_keychain_password(service: str, account: str) -> str | None:
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-a", account, "-w"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None

def write_macos_keychain_password(service: str, account: str, secret: str) -> None:
    result = subprocess.run(
        ["security", "add-generic-password", "-U", "-s", service, "-a", account, "-w", secret],
        capture_output=True,
        text=True,
        timeout=8,
        check=False,
    )
    if result.returncode != 0:
        raise OSError((result.stderr or result.stdout or "security add-generic-password failed").strip())

def read_secret_tool_password(service: str, account: str) -> str | None:
    if not shutil.which("secret-tool"):
        return None
    try:
        result = subprocess.run(
            ["secret-tool", "lookup", "service", service, "username", account],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None

def write_secret_tool_password(service: str, account: str, secret: str) -> None:
    if not shutil.which("secret-tool"):
        raise OSError("secret-tool is not available for updating the Codex keyring entry.")
    result = subprocess.run(
        ["secret-tool", "store", "--label", service, "service", service, "username", account],
        input=secret,
        capture_output=True,
        text=True,
        timeout=8,
        check=False,
    )
    if result.returncode != 0:
        raise OSError((result.stderr or result.stdout or "secret-tool store failed").strip())

def read_codex_auth_payload_from_keyring(codex_home: Path) -> tuple[dict[str, Any], dict[str, Any]] | None:
    account = compute_codex_keyring_account(codex_home)
    raw: str | None = None
    metadata: dict[str, Any] | None = None

    if sys.platform == "win32":
        found = read_windows_generic_credential(codex_windows_target_names(CODEX_KEYRING_SERVICE, account))
        if found:
            raw, target_name = found
            metadata = {
                "store_kind": "keyring",
                "platform": "windows",
                "service": CODEX_KEYRING_SERVICE,
                "account": account,
                "target_name": target_name,
            }
    elif sys.platform == "darwin":
        raw = read_macos_keychain_password(CODEX_KEYRING_SERVICE, account)
        if raw:
            metadata = {
                "store_kind": "keyring",
                "platform": "macos",
                "service": CODEX_KEYRING_SERVICE,
                "account": account,
            }
    else:
        raw = read_secret_tool_password(CODEX_KEYRING_SERVICE, account)
        if raw:
            metadata = {
                "store_kind": "keyring",
                "platform": "secret-service",
                "service": CODEX_KEYRING_SERVICE,
                "account": account,
            }

    if not raw or metadata is None:
        return None
    try:
        payload = json.loads(raw)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return payload, metadata

def write_codex_auth_payload_to_store(store: dict[str, Any], payload: dict[str, Any], codex_home: Path) -> None:
    store_kind = store.get("store_kind")
    if store_kind == "file":
        path = Path(str(store["path"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return

    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    platform_kind = str(store.get("platform", "") or "")
    service = str(store.get("service") or CODEX_KEYRING_SERVICE)
    account = str(store.get("account") or compute_codex_keyring_account(codex_home))
    if platform_kind == "windows":
        target_name = str(store.get("target_name") or codex_windows_target_names(service, account)[0])
        write_windows_generic_credential(target_name, account, serialized)
        return
    if platform_kind == "macos":
        write_macos_keychain_password(service, account, serialized)
        return
    if platform_kind == "secret-service":
        write_secret_tool_password(service, account, serialized)
        return
    raise OSError("Unsupported Codex auth storage backend for write-back.")

def build_codex_auth_record(
    payload: dict[str, Any],
    *,
    source: str,
    store: dict[str, Any],
) -> dict[str, Any] | None:
    auth_mode = normalize_codex_auth_mode(payload.get("auth_mode"))
    stored_api_key = str(payload.get("OPENAI_API_KEY") or payload.get("api_key") or "").strip()
    path_hint = store.get("path") or store.get("target_name")
    if stored_api_key and not looks_like_managed_sentinel(stored_api_key):
        return {
            "kind": "api-key",
            "api_key": stored_api_key,
            "source": source,
            "store": store,
            "auth_mode_raw": auth_mode,
            "path": str(path_hint) if path_hint else None,
        }

    tokens = payload.get("tokens")
    if isinstance(tokens, dict):
        access_token = str(tokens.get("access_token", "") or "").strip()
        refresh_token = str(tokens.get("refresh_token", "") or "").strip()
        id_token_claims = decode_possible_jwt_claims(tokens.get("id_token"))
        account_id = (
            str(tokens.get("account_id", "") or "").strip()
            or extract_chatgpt_account_id_from_claims(id_token_claims)
            or extract_chatgpt_account_id(access_token)
        )
        if access_token:
            return {
                "kind": "chatgpt-oauth" if refresh_token else "chatgpt-access-token",
                "api_key": access_token,
                "refresh_token": refresh_token or None,
                "account_id": account_id or None,
                "id_token_claims": id_token_claims,
                "source": source,
                "store": store,
                "payload": payload,
                "auth_mode_raw": auth_mode,
                "token_expiring": token_is_expiring(access_token),
                "path": str(path_hint) if path_hint else None,
            }

    agent_identity = str(payload.get("agent_identity", "") or "").strip()
    if agent_identity:
        agent_claims = decode_jwt_claims(agent_identity)
        account_id = (
            str(agent_claims.get("account_id", "") or "").strip()
            or extract_chatgpt_account_id_from_claims(agent_claims)
            or extract_chatgpt_account_id(agent_identity)
        )
        return {
            "kind": "agent-identity",
            "api_key": agent_identity,
            "account_id": account_id or None,
            "source": source,
            "store": store,
            "payload": payload,
            "auth_mode_raw": auth_mode,
            "token_expiring": token_is_expiring(agent_identity),
            "path": str(path_hint) if path_hint else None,
        }
    return None

def resolve_openclaw_state_dir(explicit_state_dir: str | None = None) -> Path:
    if explicit_state_dir:
        return Path(explicit_state_dir).expanduser()
    env_override = os.environ.get(OPENCLAW_STATE_ENV)
    if env_override:
        return Path(env_override).expanduser()
    home = Path.home()
    new_dir = home / ".openclaw"
    legacy_dir = home / ".clawdbot"
    if new_dir.exists() or not legacy_dir.exists():
        return new_dir
    return legacy_dir

def resolve_openclaw_oauth_dir(explicit_state_dir: str | None = None) -> Path:
    override = os.environ.get(OPENCLAW_OAUTH_DIR_ENV)
    if override:
        return Path(override).expanduser()
    return resolve_openclaw_state_dir(explicit_state_dir) / "credentials"

def read_openclaw_secret_payload(secret_path: Path, *, profile_id: str, provider: str) -> dict[str, Any] | None:
    payload = read_json_file(secret_path)
    if not payload:
        return None
    if payload.get("version") != 1 or payload.get("profileId") != profile_id or payload.get("provider") != provider:
        return None
    access = payload.get("access")
    refresh = payload.get("refresh")
    id_token = payload.get("idToken")
    if not isinstance(access, str) or not access.strip():
        return None
    if not isinstance(refresh, str) or not refresh.strip():
        return None
    return {
        "access": access.strip(),
        "refresh": refresh.strip(),
        "id_token": id_token.strip() if isinstance(id_token, str) and id_token.strip() else None,
    }

def candidate_openclaw_auth_paths(*, agent_dir: str | None, state_dir: str | None) -> list[Path]:
    candidates: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        key = str(path.expanduser().resolve()) if path.exists() else str(path.expanduser())
        if key in seen:
            return
        seen.add(key)
        candidates.append(path.expanduser())

    for explicit in (agent_dir, os.environ.get(OPENCLAW_AGENT_ENV), os.environ.get(OPENCLAW_ALT_AGENT_ENV)):
        if explicit:
            add(Path(explicit) / "auth-profiles.json")

    openclaw_state_dir = resolve_openclaw_state_dir(state_dir)
    add(openclaw_state_dir / "agents" / "main" / "agent" / "auth-profiles.json")
    return candidates

def read_codex_cli_oauth(codex_home: Path) -> dict[str, Any] | None:
    auth_path = codex_home / "auth.json"
    payload = read_json_file(auth_path)
    if isinstance(payload, dict):
        record = build_codex_auth_record(
            payload,
            source="codex-auth-json",
            store={"store_kind": "file", "path": str(auth_path)},
        )
        if record:
            return record

    keyring_payload = read_codex_auth_payload_from_keyring(codex_home)
    if keyring_payload:
        payload, store = keyring_payload
        record = build_codex_auth_record(payload, source="codex-auth-keyring", store=store)
        if record:
            return record
    return None

def read_hermes_codex_oauth(hermes_home: str | None = None) -> dict[str, Any] | None:
    base = Path(hermes_home or os.environ.get(HERMES_HOME_ENV) or Path.home() / ".hermes").expanduser()
    auth_path = base / "auth.json"
    payload = read_json_file(auth_path)
    if not payload:
        return None
    providers = payload.get("providers")
    if not isinstance(providers, dict):
        return None
    state = providers.get("openai-codex")
    if not isinstance(state, dict):
        return None
    tokens = state.get("tokens")
    if not isinstance(tokens, dict):
        return None
    access_token = str(tokens.get("access_token", "") or "").strip()
    refresh_token = str(tokens.get("refresh_token", "") or "").strip()
    if not access_token or not refresh_token:
        return None
    return {
        "api_key": access_token,
        "refresh_token": refresh_token,
        "account_id": str(tokens.get("account_id", "") or "").strip() or extract_chatgpt_account_id(access_token),
        "source": "hermes-auth-json",
        "path": str(auth_path),
        "token_expiring": token_is_expiring(access_token),
    }

def read_openclaw_codex_oauth(*, agent_dir: str | None = None, state_dir: str | None = None) -> dict[str, Any] | None:
    for auth_path in candidate_openclaw_auth_paths(agent_dir=agent_dir, state_dir=state_dir):
        payload = read_json_file(auth_path)
        if not payload:
            continue
        profiles = payload.get("profiles")
        if not isinstance(profiles, dict):
            continue
        for profile_id in ("openai-codex:default", *sorted(profiles.keys())):
            credential = profiles.get(profile_id)
            if not isinstance(credential, dict):
                continue
            if credential.get("provider") != "openai-codex":
                continue
            if credential.get("type") != "oauth":
                continue
            access_token = str(credential.get("access", "") or "").strip()
            refresh_token = str(credential.get("refresh", "") or "").strip()
            if access_token and refresh_token:
                return {
                    "api_key": access_token,
                    "refresh_token": refresh_token,
                    "account_id": str(credential.get("accountId", "") or "").strip() or extract_chatgpt_account_id(access_token),
                    "id_token": str(credential.get("idToken", "") or "").strip() or None,
                    "source": "openclaw-auth-profiles",
                    "path": str(auth_path),
                    "profile_id": profile_id,
                    "token_expiring": token_is_expiring(access_token),
                }
            oauth_ref = credential.get("oauthRef")
            if isinstance(oauth_ref, dict):
                ref_source = oauth_ref.get("source")
                ref_provider = oauth_ref.get("provider")
                ref_id = oauth_ref.get("id")
                if ref_source == "openclaw-credentials" and ref_provider == "openai-codex" and isinstance(ref_id, str) and re.fullmatch(r"[a-f0-9]{32}", ref_id):
                    secret_path = resolve_openclaw_oauth_dir(state_dir) / "auth-profiles" / f"{ref_id}.json"
                    secret_payload = read_openclaw_secret_payload(secret_path, profile_id=profile_id, provider="openai-codex")
                    if secret_payload:
                        secret_access = secret_payload["access"]
                        return {
                            "api_key": secret_access,
                            "refresh_token": secret_payload["refresh"],
                            "account_id": str(credential.get("accountId", "") or "").strip() or extract_chatgpt_account_id(secret_access),
                            "id_token": secret_payload.get("id_token") or str(credential.get("idToken", "") or "").strip() or None,
                            "source": "openclaw-oauth-secret-file",
                            "path": str(secret_path),
                            "auth_profiles_path": str(auth_path),
                            "profile_id": profile_id,
                            "token_expiring": token_is_expiring(secret_access),
                        }
    return None

def refresh_codex_chatgpt_tokens(record: dict[str, Any], codex_home: Path) -> dict[str, Any]:
    refresh_token = str(record.get("refresh_token") or "").strip()
    payload = record.get("payload")
    store = record.get("store")
    if not refresh_token or not isinstance(payload, dict) or not isinstance(store, dict):
        return record

    refresh_request = {
        "client_id": CODEX_OAUTH_CLIENT_ID,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    response = post_json(CODEX_OAUTH_TOKEN_URL, refresh_request, headers, 60)
    if not isinstance(response, dict):
        raise RequestFailure("Codex OAuth refresh returned a non-JSON payload.", attempts=1)

    new_access = str(response.get("access_token", "") or "").strip()
    new_refresh = str(response.get("refresh_token", "") or "").strip() or refresh_token
    if not new_access:
        raise RequestFailure("Codex OAuth refresh did not return access_token.", attempts=1)

    tokens = payload.get("tokens")
    if not isinstance(tokens, dict):
        tokens = {}
        payload["tokens"] = tokens
    tokens["access_token"] = new_access
    tokens["refresh_token"] = new_refresh
    id_token_value = response.get("id_token")
    if isinstance(id_token_value, str) and id_token_value.strip():
        tokens["id_token"] = id_token_value.strip()
    if record.get("account_id"):
        tokens["account_id"] = record["account_id"]
    payload["last_refresh"] = format_rfc3339_utc_now()

    if not payload.get("auth_mode"):
        payload["auth_mode"] = "chatgpt"

    if isinstance(id_token_value, str) and id_token_value.strip() and not tokens.get("account_id"):
        refreshed_account_id = extract_chatgpt_account_id(id_token_value.strip())
        if refreshed_account_id:
            tokens["account_id"] = refreshed_account_id

    write_codex_auth_payload_to_store(store, payload, codex_home)

    refreshed_record = build_codex_auth_record(payload, source=str(record.get("source") or "codex-auth-refresh"), store=store)
    if not refreshed_record:
        raise RequestFailure("Codex OAuth refresh succeeded but rebuilt auth payload is unusable.", attempts=1)
    refreshed_record["refreshed"] = True
    refreshed_record["refresh_source"] = str(record.get("source") or "codex-auth")
    return refreshed_record

def maybe_refresh_codex_auth_record(record: dict[str, Any] | None, codex_home: Path) -> dict[str, Any] | None:
    if not record:
        return None
    if record.get("kind") != "chatgpt-oauth":
        return record
    if not record.get("token_expiring"):
        return record
    try:
        return refresh_codex_chatgpt_tokens(record, codex_home)
    except Exception:
        return record

def resolve_auth_context(args: argparse.Namespace, cfg: dict[str, Any], codex_home: Path) -> dict[str, Any]:
    explicit_api_key = (args.api_key or first_value(API_KEY_ENV) or cfg.get("api_key") or cfg.get("api_key_hint") or "").strip()
    explicit_account_id = (args.chatgpt_account_id or first_value(ACCOUNT_ID_ENV) or "").strip() or None
    explicit_originator = sanitize_originator(args.originator or first_value(ORIGINATOR_ENV))
    explicit_client_version = sanitize_client_version(args.client_version or first_value(CLIENT_VERSION_ENV))
    requires_openai_auth = bool(coerce_bool(cfg.get("requires_openai_auth")))
    wire_api = str(cfg.get("wire_api", "") or "").strip().lower() or None
    codex_backend = is_chatgpt_codex_base_url(args.base_url)
    official_openai = is_official_openai_base_url(args.base_url)
    local_codex_proxy = is_local_openai_auth_proxy(args.base_url, requires_openai_auth=requires_openai_auth)

    base_context = {
        "requires_openai_auth": requires_openai_auth,
        "wire_api": wire_api,
        "is_codex_backend": codex_backend,
        "is_local_codex_proxy": local_codex_proxy,
        "endpoint_style_hint": cfg.get("endpoint_style_hint"),
        "originator": explicit_originator,
        "client_version": explicit_client_version,
        "account_id": explicit_account_id,
        "user_agent": f"{explicit_originator}/{explicit_client_version} (hellomedia)",
    }

    if explicit_api_key and not looks_like_managed_sentinel(explicit_api_key) and not local_codex_proxy:
        return {
            **base_context,
            "api_key": explicit_api_key,
            "auth_mode": "api-key",
            "auth_source": "explicit",
            "account_id": explicit_account_id or extract_chatgpt_account_id(explicit_api_key),
        }

    if explicit_api_key and looks_like_managed_sentinel(explicit_api_key) and not codex_backend and not official_openai and not local_codex_proxy:
        return {
            **base_context,
            "api_key": explicit_api_key,
            "auth_mode": "relay-managed",
            "auth_source": "managed-sentinel",
        }

    managed_sentinel_requires_local_auth = bool(
        explicit_api_key and looks_like_managed_sentinel(explicit_api_key) and (codex_backend or official_openai or local_codex_proxy)
    )

    for resolver in (
        lambda: maybe_refresh_codex_auth_record(read_codex_cli_oauth(codex_home), codex_home),
        lambda: read_hermes_codex_oauth(args.hermes_home),
        lambda: read_openclaw_codex_oauth(agent_dir=args.openclaw_agent_dir, state_dir=args.openclaw_state_dir),
    ):
        resolved = resolver()
        if not resolved:
            continue
        if resolved.get("unresolved"):
            return {
                **base_context,
                "api_key": None,
                "auth_mode": "missing",
                "auth_source": resolved["source"],
                "auth_error": "OpenClaw profile only contains oauthRef indirection; hellomedia cannot read the secret payload directly.",
            }
        if resolved.get("kind") == "api-key":
            return {
                **base_context,
                "api_key": resolved["api_key"],
                "auth_mode": "api-key",
                "auth_source": resolved["source"],
                "auth_path": resolved.get("path"),
                "auth_profile_id": resolved.get("profile_id"),
                "account_id": explicit_account_id or resolved.get("account_id"),
            }
        if resolved.get("kind") == "agent-identity":
            return {
                **base_context,
                "api_key": resolved["api_key"],
                "auth_mode": "codex-agent-identity",
                "auth_source": resolved["source"],
                "auth_path": resolved.get("path"),
                "auth_profile_id": resolved.get("profile_id"),
                "token_expiring": resolved.get("token_expiring"),
                "account_id": explicit_account_id or resolved.get("account_id"),
            }
        return {
            **base_context,
            "api_key": resolved["api_key"],
            "auth_mode": "codex-oauth",
            "auth_source": resolved["source"],
            "auth_path": resolved.get("path"),
            "auth_profile_id": resolved.get("profile_id"),
            "token_expiring": resolved.get("token_expiring"),
            "account_id": explicit_account_id or resolved.get("account_id") or extract_chatgpt_account_id(resolved["api_key"]),
            "refreshed": resolved.get("refreshed"),
            "refresh_source": resolved.get("refresh_source"),
        }

    if explicit_api_key and not looks_like_managed_sentinel(explicit_api_key):
        return {
            **base_context,
            "api_key": explicit_api_key,
            "auth_mode": "api-key",
            "auth_source": "explicit-fallback" if local_codex_proxy else "explicit",
            "account_id": explicit_account_id or extract_chatgpt_account_id(explicit_api_key),
            "auth_warning": (
                "Provider requested local OpenAI/Codex auth, but no local OAuth credential was found; using explicit API key fallback."
                if local_codex_proxy
                else None
            ),
        }

    if explicit_api_key and looks_like_managed_sentinel(explicit_api_key) and not codex_backend and not official_openai and not local_codex_proxy:
        return {
            **base_context,
            "api_key": explicit_api_key,
            "auth_mode": "relay-managed",
            "auth_source": "managed-sentinel",
        }

    return {
        **base_context,
        "api_key": None if managed_sentinel_requires_local_auth else (explicit_api_key or None),
        "auth_mode": "missing"
        if (codex_backend or local_codex_proxy or requires_openai_auth or not explicit_api_key or managed_sentinel_requires_local_auth)
        else "api-key",
        "auth_source": "managed-sentinel" if managed_sentinel_requires_local_auth else ("none" if not explicit_api_key else "explicit"),
        "auth_error": (
            "Current provider auth is a managed relay sentinel, but the selected official OpenAI / Codex backend requires local official credentials."
            if managed_sentinel_requires_local_auth
            else None
        ),
    }

def request_headers(auth: dict[str, Any], *, accept: str = "application/json", content_type: str = "application/json") -> dict[str, str]:
    api_key = auth.get("api_key")
    if not api_key:
        raise ValueError("Missing API key for request headers.")
    headers = {"Authorization": f"Bearer {api_key}", "Accept": accept, "Content-Type": content_type}
    if auth.get("auth_mode") in {"codex-oauth", "codex-agent-identity"} or auth.get("is_codex_backend") or auth.get("is_local_codex_proxy"):
        headers["User-Agent"] = auth.get("user_agent") or f"{DEFAULT_MANAGED_ORIGINATOR}/{DEFAULT_MANAGED_CLIENT_VERSION} (hellomedia)"
        headers["originator"] = auth.get("originator") or DEFAULT_MANAGED_ORIGINATOR
        headers["version"] = auth.get("client_version") or DEFAULT_MANAGED_CLIENT_VERSION
        account_id = auth.get("account_id")
        if isinstance(account_id, str) and account_id.strip():
            headers["ChatGPT-Account-ID"] = account_id.strip()
    return headers

