# pingbix.py
import os
import time
import requests
import json
from dotenv import load_dotenv

load_dotenv()


def _cfg():
    return {
        "url": os.getenv("PINGBIX_API_URL", "https://api.pingbix.ai/v1/whatsapp"),
        "key": os.getenv("PINGBIX_API_KEY"),
        "sender": os.getenv("PINGBIX_SENDER") or os.getenv("PINGBIX_WABA_NUMBER"),
        "waba_id": os.getenv("PINGBIX_WABA_ID"),
        "template_lang": os.getenv("PINGBIX_TEMPLATE_LANGUAGE", "en"),
    }


def list_wa_templates(waba_id: str = None) -> dict:
    """
    Fetch WhatsApp templates from Pingbix using the correct endpoint.
    Send EMPTY payload (no wabaId).
    """
    cfg = _cfg()
    if not cfg["key"]:
        raise RuntimeError("PINGBIX_API_KEY not set")

    url = "https://api.pingbix.ai/v1/whatsapp/waTemplateList"

    headers = {
        "apikey": cfg["key"],
        "Content-Type": "application/json",
    }

    payload = {}

    print(f"[info] Fetching templates from: {url}")
    print(f"[info] Payload: (empty)")

    try:
        r = requests.post(url, json=payload, headers=headers, timeout=15)
        print(f"[info] Response status: {r.status_code}")

        if r.status_code == 200:
            try:
                body = r.json()
            except Exception:
                body = {"text": r.text}

            try:
                dbg = json.dumps(body, indent=2, ensure_ascii=False)
                print(f"[DEBUG] Raw response (first 1000 chars): {dbg[:1000]}")
            except Exception:
                print(f"[DEBUG] Raw response (non-serializable): {repr(body)[:1000]}")
            return body
        else:
            print(f"[error] API returned {r.status_code}: {r.text[:500]}")
            return {"error": f"API returned {r.status_code}", "text": r.text[:1000]}

    except requests.exceptions.RequestException as e:
        print(f"[error] Request failed: {e}")
        return {"error": str(e)}


def fetch_pingbix_templates():
    """
    Return list of templates as:
    [{name, display, params, header, raw}, ...]
    """
    raw = list_wa_templates()

    if isinstance(raw, dict) and raw.get("error"):
        print(f"[DEBUG] list_wa_templates returned error: {raw.get('error')}")

    items = None

    if isinstance(raw, dict):
        for key in ("templates", "data", "templateList", "waTemplates", "result"):
            if isinstance(raw.get(key), list):
                items = raw[key]
                print(f"[info] Found templates under key: '{key}'")
                break
        if items is None:
            for v in raw.values():
                if isinstance(v, list):
                    items = v
                    print(f"[info] Found templates as first list value")
                    break
    elif isinstance(raw, list):
        items = raw
        print(f"[info] Response is already a list")

    items = items or []
    print(f"[info] Processing {len(items)} items from response")

    out = []
    for t in items:
        if not isinstance(t, dict):
            continue

        name = (t.get("name") or t.get("templateName") or t.get("template_name") or "").strip()
        if not name:
            continue

        display = t.get("displayName") or name

        params_count = 0
        if isinstance(t.get("params"), list):
            params_count = len(t["params"])
        elif isinstance(t.get("paramsCount"), (int, str)):
            try:
                params_count = int(t["paramsCount"])
            except Exception:
                params_count = 0

        header = t.get("headerUrl") or t.get("mediaUrl") or t.get("header")

        out.append({
            "name": name,
            "display": display,
            "params": params_count,
            "header": header,
            "raw": t
        })

    print(f"✓ Normalized {len(out)} templates from Pingbix")
    return out


def send_template(to, template_name, params=None, waba=None, otp=None):
    """
    Send a WhatsApp template message via Pingbix API.

    - 'from' comes from .env (PINGBIX_SENDER)
    - 'to' is normalized to +91 format
    - For normal templates: params -> components.body.params
    - For authentication templates: otp -> otp field
    """
    from utils import normalize_msisdn
    from template_builder import get_template_info  # to know template type

    cfg = _cfg()
    if not cfg["key"]:
        return 500, {"error": "Missing PINGBIX_API_KEY"}

    sender = cfg.get("sender")
    if not sender:
        print("[error] PINGBIX_SENDER not configured in .env")
        return 500, {"error": "Missing PINGBIX_SENDER in .env"}

    # Sender already has +91 in your .env, keep as-is
    sender = sender.strip()

    # Normalize recipient to E.164 format (+91...)
    to = (to or "").strip()
    if to.startswith("+"):
        to = to[1:]
    to = normalize_msisdn(to)
    if not to:
        return 400, {"error": "invalid_phone_number"}
    if not to.startswith("+"):
        to = "+" + to

    if not params:
        params = []

    # Base payload
    payload = {
        "recipient_type": "individual",
        "from": sender,         # ALWAYS SET
        "to": to,
        "type": "template",
        "templateName": template_name,
        "campaignName": "voice-api",
    }

    # Determine template metadata from config
    tmpl_info = get_template_info(template_name) or {}

    # ---------------- Header handling (image / text) ----------------
    if tmpl_info.get("has_header"):
        payload.setdefault("components", {})
        header_type = tmpl_info.get("header_type")

        # Image / media header
        if header_type == "image":
            header_link = tmpl_info.get("header_image")
            if header_link:
                payload["components"]["header"] = {
                    "type": "image",
                    "image": {"link": header_link}
                }
                print(f"[info] Added header image to payload: {header_link}")

        # Text header (for 'qr' etc.)
        elif header_type == "text":
            header_text = tmpl_info.get("header_text")
            if header_text:
                payload["components"]["header"] = {
                    "type": "text",
                    "text": header_text
                }
                print(f"[info] Added text header to payload: {header_text}")

    # ---------------- Authentication vs normal templates -------------
    if tmpl_info.get("type") == "authentication":
        # OTP templates
        if not otp:
            return 400, {"error": "OTP is Required For Authentication Template Messages.!"}
        payload["otp"] = str(otp)
        payload["language"] = {"code": "en"}
    else:
        # Normal templates with params
        if params:
            payload.setdefault("components", {})
            
            # Special case: diwali_campaign has dynamic URL ONLY in button, not body
            if template_name == "diwali_campaign":
                payload["components"]["buttons"] = [
                    {
                        "type": "url",
                        "url_parameter_value": params[0] if params else ""
                    }
                ]
                print(f"[info] Added URL param to button for diwali_campaign: {params[0]}")
            else:
                # All other templates use body params
                payload["components"]["body"] = {"params": params}
                print(f"[info] Added body params for {template_name}: {params}")

    headers = {
        "apikey": cfg["key"],
        "Content-Type": "application/json",
    }

    url = cfg["url"]
    print(f"[info] Sending template '{template_name}' to {to} from {sender}")
    print(f"[DEBUG] Payload: {json.dumps(payload, indent=2)}")

    try:
        r = requests.post(url, json=payload, headers=headers, timeout=15)
        try:
            body = r.json()
        except Exception:
            body = {"text": r.text}
        print(f"[info] Send response status: {r.status_code}")
        print(f"[DEBUG] Response: {json.dumps(body, indent=2)[:500]}")
        return r.status_code, body
    except requests.exceptions.RequestException as e:
        print(f"[error] send_template request failed: {e}")
        return 500, {"error": str(e)}
