# utils.py
import os
import time
import json
import requests
from pathlib import Path
from difflib import get_close_matches
import phonenumbers

from pingbix import fetch_pingbix_templates  # must exist in pingbix.py

TEMPLATE_CACHE_TTL = int(os.getenv("TEMPLATE_CACHE_TTL", 300))

# -------------------------------------------------
# NORMALIZE PHONE NUMBERS TO E.164
# -------------------------------------------------
def normalize_msisdn(raw_number, default_country="IN"):
    """Return E.164 format or None."""
    if not raw_number:
        return None

    raw = raw_number.strip().replace(" ", "").replace("-", "")

    # Try parsing as national number first
    try:
        num = phonenumbers.parse(raw, default_country)
        if phonenumbers.is_valid_number(num):
            return phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)
    except Exception:
        pass

    # Try adding + prefix if missing
    try:
        if not raw.startswith("+"):
            raw_plus = "+" + raw
            num = phonenumbers.parse(raw_plus)
            if phonenumbers.is_valid_number(num):
                return phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)
    except Exception:
        pass

    return None

# -------------------------------------------------
# LOCAL TEMPLATES (NOT USED BY CACHE, JUST UTILITY)
# -------------------------------------------------
def load_local_templates(path="templates_media.json"):
    """
    Optional utility to load templates from a local JSON file.
    Not used by TemplateCache (Pingbix-only), but kept for tools
    that may want a local mapping (e.g., header media).
    """
    p = Path(path)
    if not p.exists():
        return []

    try:
        txt = p.read_text(encoding="utf8").strip()
        if not txt:
            return []

        data = json.loads(txt)
        out = []

        # case 1: dict {"template_name": {...}}
        if isinstance(data, dict):
            for name, info in data.items():
                out.append({
                    "name": name,
                    "display": info.get("display") or name,
                    "params": int(info.get("params", 0)),
                    "header": info.get("header"),
                    "raw": info
                })
            return out

        # case 2: list
        if isinstance(data, list):
            for t in data:
                name = t.get("name") or t.get("templateName")
                if name:
                    out.append({
                        "name": name,
                        "display": t.get("display") or name,
                        "params": int(t.get("params", 0)),
                        "header": t.get("header"),
                        "raw": t
                    })
            return out

        return []

    except Exception as e:
        print(f"[warn] Could not load local templates: {e}")
        return []

# -------------------------------------------------
# TEMPLATE CACHE (PINGBIX ONLY)
# -------------------------------------------------
class TemplateCache:
    def __init__(self, source_url=None, ttl=TEMPLATE_CACHE_TTL, auth_token=None):
        """
        source_url, auth_token are preserved for compatibility but NOT used
        by get_templates(), since we now fetch only from Pingbix.
        """
        self.source_url = source_url
        self.ttl = ttl
        self.auth_token = auth_token
        self._cache = []
        self._ts = 0

    def get_templates(self, force=False):
        """
        Fetch templates ONLY from Pingbix (via fetch_pingbix_templates()).
        If Pingbix fails or returns empty, return [] (no local/aggregator fallback).
        """
        now = time.time()

        # Use cached templates if still fresh
        if not force and (now - self._ts) < self.ttl and self._cache:
            return self._cache

        try:
            pingbix_templates = fetch_pingbix_templates()
            if pingbix_templates:
                self._cache = pingbix_templates
                self._ts = now
                print(f"✓ Cached {len(self._cache)} templates from Pingbix")
                return self._cache
            else:
                print("ℹ Pingbix returned no templates")
        except Exception as e:
            print(f"✖ Pingbix fetch failed: {e}")

        # If Pingbix fails or returns empty, return empty
        self._cache = []
        self._ts = now
        return []

# -------------------------------------------------
# FUZZY TEMPLATE MATCHING
# -------------------------------------------------
def fuzzy_match_template(query_name, templates, n=5, cutoff=0.6):
    """
    Fuzzy match a spoken template name against available templates.
    Returns: (best_template_dict or None, score_float, suggestions_list)
    """
    if not query_name or not templates:
        return None, 0.0, []

    q = query_name.strip().lower()

    candidates = []
    mapping = {}

    for t in templates:
        name = (t.get("name") or "").strip().lower()
        display = (t.get("display") or "").strip().lower()

        if name:
            candidates.append(name)
            mapping[name] = t

        if display and display not in mapping:
            candidates.append(display)
            mapping[display] = t

    # exact match
    if q in mapping:
        return mapping[q], 1.0, []

    # fuzzy close matches
    matches = get_close_matches(q, candidates, n=n, cutoff=cutoff)

    suggestions = []
    if matches:
        for m in matches:
            t = mapping.get(m)
            if t:
                suggestions.append({"name": t["name"], "display": t.get("display")})
        best = mapping[matches[0]]
        return best, 0.8, suggestions

    # fallback substring match
    subs = [c for c in candidates if q in c or c in q]
    if subs:
        s = subs[0]
        t = mapping[s]
        suggestions.append({"name": t["name"], "display": t.get("display")})
        return t, 0.7, suggestions

    return None, 0.0, []
