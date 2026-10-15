"""Automatic icons for HLD nodes: real product logos first, generic built-in pictograms second.

A node without `icon` gets one picked from its label. Product names (nginx, postgres, kafka, ...) resolve to a logo from
the Simple Icons CDN, cached under ~/.cache/diagramkit/logos; offline or unknown names silently fall back to a built-in
pictogram (database, user, server, ...). Opt out per node with `icon: none`, or for the whole diagram with `icons: none`.
Environment: DIAGRAMKIT_OFFLINE=1 never touches the network (cache only).
"""
from __future__ import annotations

import os
import re
import urllib.request
from pathlib import Path

# label word -> Simple Icons slug (https://simpleicons.org)
LOGOS = {
    "nginx": "nginx", "apache": "apache", "haproxy": "haproxy", "traefik": "traefikproxy", "envoy": "envoyproxy", "istio": "istio",
    "react": "react", "reactjs": "react", "vue": "vuedotjs", "angular": "angular", "nextjs": "nextdotjs", "svelte": "svelte",
    "node": "nodedotjs", "nodejs": "nodedotjs", "python": "python", "django": "django", "flask": "flask", "fastapi": "fastapi",
    "java": "openjdk", "spring": "springboot", "go": "go", "golang": "go", "rust": "rust", "php": "php", "laravel": "laravel",
    "dotnet": "dotnet", "kotlin": "kotlin", "flutter": "flutter", "odoo": "odoo",
    "postgres": "postgresql", "postgresql": "postgresql", "pgvector": "postgresql", "pg_vector": "postgresql",
    "mysql": "mysql", "mariadb": "mariadb", "mongodb": "mongodb", "redis": "redis", "sqlite": "sqlite", "oracle": "oracle",
    "elasticsearch": "elasticsearch", "opensearch": "opensearch", "clickhouse": "clickhouse", "snowflake": "snowflake",
    "kafka": "apachekafka", "rabbitmq": "rabbitmq", "nats": "natsdotio", "minio": "minio",
    "docker": "docker", "kubernetes": "kubernetes", "k8s": "kubernetes", "terraform": "terraform", "ansible": "ansible",
    "jenkins": "jenkins", "github": "github", "gitlab": "gitlab", "argocd": "argo", "helm": "helm",
    "grafana": "grafana", "prometheus": "prometheus", "loki": "grafana", "tempo": "grafana", "kibana": "kibana",
    "jaeger": "jaeger", "opentelemetry": "opentelemetry", "sentry": "sentry", "datadog": "datadog",
    "keycloak": "keycloak", "vault": "vault", "consul": "consul", "auth0": "auth0", "okta": "okta",
    "linux": "linux", "ubuntu": "ubuntu", "debian": "debian", "redhat": "redhat", "rhel": "redhat", "centos": "centos",
    "cloudflare": "cloudflare", "googlecloud": "googlecloud", "gcp": "googlecloud", "vercel": "vercel",
    "dify": "dify", "anthropic": "anthropic", "claude": "anthropic", "huggingface": "huggingface", "ollama": "ollama",
    "stripe": "stripe", "slack": "slack", "telegram": "telegram", "whatsapp": "whatsapp", "firebase": "firebase",
}

# label word -> built-in pictogram (see `diagramkit icons`), used when no logo matches
BUILTIN = [
    (r"user|actor|customer|shopper|visitor|admin user|operator", "user"),
    (r"browser|web|frontend|front-end|spa|portal|storefront|ui", "browser"),
    (r"mobile|android|ios|phone", "mobile"),
    (r"database|db|datastore|warehouse|storage|bucket|vector", "database"),
    (r"cache|session", "cache"),
    (r"queue|bus|broker|stream|event", "queue"),
    (r"gateway|proxy|router|load balancer|ingress", "gateway"),
    (r"cloud|external|provider|saas", "cloud"),
    (r"auth|security|firewall|iam|secret|lock", "lock"),
    (r"shield|waf|guard", "shield"),
    (r"alert|notification|notify|bell", "bell"),
    (r"mail|email|sms|message", "mail"),
    (r"chart|metric|analytics|dashboard|report|evaluation", "chart"),
    (r"monitor|observability|tracing|logging|logs", "monitor"),
    (r"api|sdk|rest|graphql", "api"),
    (r"payment|billing|invoice|checkout", "payment"),
    (r"setting|config|automation|admin|console", "settings"),
    (r"key|token|certificate", "key"),
    (r"server|service|engine|worker|runtime|vm|host", "server"),
]

CACHE = Path(os.environ.get("DIAGRAMKIT_CACHE", Path.home() / ".cache" / "diagramkit")) / "logos"


def _words(label: str) -> list:
    return re.findall(r"[a-z0-9_]+", label.lower())


def logo_slug(label: str):
    words = _words(label)
    joined = "".join(words)
    for w in words:
        if w in LOGOS:
            return LOGOS[w]
    for key, slug in LOGOS.items():  # glued names such as "postgresql", "nodejs"
        if len(key) > 4 and key in joined:
            return slug
    return None


def fetch_logo(slug: str):
    """Path of the cached logo file, downloading it on first use. None when unavailable."""
    path = CACHE / f"{slug}.svg"
    if path.exists() and path.stat().st_size > 0:
        return path
    if os.environ.get("DIAGRAMKIT_OFFLINE"):
        return None
    try:
        req = urllib.request.Request(f"https://cdn.simpleicons.org/{slug}", headers={"User-Agent": "diagramkit"})
        with urllib.request.urlopen(req, timeout=4) as r:  # noqa: S310 - fixed https host
            data = r.read()
        if b"<svg" not in data[:2000]:
            return None
        CACHE.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path
    except Exception:  # noqa: BLE001 - offline / unknown slug: fall back to a pictogram
        return None


def auto_icon(label: str):
    """Icon source for a node label: cached logo path, else 'builtin:<name>', else None."""
    slug = logo_slug(label)
    if slug:
        p = fetch_logo(slug)
        if p:
            return str(p)
    low = " ".join(_words(label))
    for pat, name in BUILTIN:
        if re.search(r"\b(?:%s)\b" % pat, low):
            return f"builtin:{name}"
    return None
