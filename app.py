"""
WhatsApp Voice Sender - Flask Backend
Integrates with template_builder.py to dynamically build payloads for all template types
"""

import os
from flask import Flask, request, jsonify, send_from_directory
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Imports from local modules
from utils import TemplateCache, load_local_templates, fuzzy_match_template, normalize_msisdn
from pingbix import send_template
from template_builder import build_template_payload, get_template_info, list_all_templates

# -------------------------
# CONFIG
# -------------------------
FLASK_HOST = os.getenv("FLASK_HOST", "0.0.0.0")
FLASK_PORT = int(os.getenv("FLASK_PORT", "5001"))

VOICE_UI_API_KEY = os.getenv("VOICE_UI_API_KEY", "changeme123")
WABA_NUMBER = os.getenv("PINGBIX_WABA_NUMBER")

TEMPLATE_SOURCE_URL = os.getenv("TEMPLATE_SOURCE_URL", "https://aggregator.cpaas.ai/api/v1/whatsapp/whatsappTemplateList")
TEMPLATE_AUTH_TOKEN = os.getenv("TEMPLATE_AUTH_TOKEN", "")

TEMPLATE_CACHE_TTL = int(os.getenv("TEMPLATE_CACHE_TTL", "300"))

# Cache: Pingbix → Aggregator → Local
template_cache = TemplateCache(
    source_url=TEMPLATE_SOURCE_URL,
    ttl=TEMPLATE_CACHE_TTL,
    auth_token=TEMPLATE_AUTH_TOKEN
)

# LOCAL templates
LOCAL_TEMPLATES = load_local_templates()

# -------------------------
# FLASK APP
# -------------------------
app = Flask(__name__, static_folder="static", static_url_path="/static")


def require_api_key(req):
    key = req.headers.get("X-API-KEY") or req.headers.get("Authorization")
    if not key:
        return False

    if isinstance(key, str) and key.lower().startswith("bearer "):
        key = key.split(" ", 1)[1]

    return key == VOICE_UI_API_KEY


def _get_templates(force=False):
    templates = template_cache.get_templates(force=force)
    if templates:
        return templates
    return LOCAL_TEMPLATES or []

# -------------------------
# HEALTH CHECK
# -------------------------
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True})

# -------------------------
# STATIC UI
# -------------------------
@app.route("/", methods=["GET"])
def index():
    html_path = os.path.join(app.root_path, "static", "voice_send.html")
    if os.path.exists(html_path):
        return send_from_directory("static", "voice_send.html")

    return "<h3>WhatsApp Voice Sender</h3><p>UI not found.</p>"

# -------------------------
# DEBUG: Show templates from template_config.json
# -------------------------
@app.route("/debug/templates", methods=["GET"])
def debug_templates():
    """Show all templates loaded from template_config.json"""
    if not require_api_key(request):
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    templates = list_all_templates()
    return jsonify({"ok": True, "count": len(templates), "templates": templates})

# -------------------------
# FETCH TEMPLATES (legacy compatibility)
# -------------------------
@app.route("/templates/fetch", methods=["GET"])
def fetch_templates():
    if not require_api_key(request):
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    force = request.args.get("force", "").lower() in ("1", "true", "yes")
    templates = _get_templates(force=force)

    out = []
    for t in templates:
        name = t.get("name")
        if not name:
            continue
        out.append({
            "name": name,
            "display": t.get("display", name),
            "params": int(t.get("params", 0) or 0),
            "header": t.get("header")
        })

    return jsonify({"ok": True, "templates": out})

# -------------------------
# NEW: UNIFIED TEMPLATE SENDER (JSON API)
# -------------------------
@app.route("/send/template-unified", methods=["POST"])
def send_template_unified():
    """
    Unified template sender that works with template_config.json
    Automatically handles:
    - Authentication templates (OTP) - REQUIRES otp field
    - Text templates with no header
    - Text templates with image/video/document headers

    Request:
    {
        "to": "919876543210",
        "template_name": "otp_verification",
        "params": ["param1", "param2"],
        "otp": "123456"  (only for authentication templates)
    }
    """
    if not require_api_key(request):
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    try:
        data = request.get_json() or {}

        # Extract fields
        to_number = data.get("to", "").strip()
        template_name = data.get("template_name") or data.get("templateName") or data.get("template")
        params = data.get("params") or []
        otp = data.get("otp")

        # Validate required fields
        if not to_number:
            return jsonify({"ok": False, "error": "Missing 'to' field"}), 400
        if not template_name:
            return jsonify({"ok": False, "error": "Missing 'template_name' field"}), 400

        # Normalize phone number (digits only; pingbix.send_template will E.164 it)
        to_number = to_number.replace("+", "").replace("-", "").replace(" ", "")
        if not to_number.isdigit() or len(to_number) < 10:
            return jsonify({"ok": False, "error": "Invalid phone number format"}), 400

        # Optional: build payload just for debug / validation
        payload = build_template_payload(to_number, template_name, params=params, otp=otp)
        if not payload:
            return jsonify({
                "ok": False,
                "error": f"Template '{template_name}' not found or failed to build payload"
            }), 400

        print(f"[info] Built payload for template: {template_name}")
        print(f"[DEBUG] Payload preview: {payload}")

        # Send via Pingbix (single source of truth for API payload)
        status_code, response = send_template(
            to_number,
            template_name,
            params=params,
            otp=otp
        )

        return jsonify({
            "ok": 200 <= status_code < 300,
            "status_code": status_code,
            "response": response,
            "template": template_name,
            "to": to_number
        }), status_code

    except Exception as e:
        print(f"[error] /send/template-unified exception: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500

# -------------------------
# VOICE TEMPLATE SENDER (with auto-correct)
# -------------------------
@app.route('/send/template-voice', methods=['POST'])
def send_template_voice():
    """
    Send WhatsApp template via voice-recognized command.
    Auto-corrects template name using fuzzy matching.

    IMPORTANT: For authentication templates (OTP), you MUST provide the OTP code!

    Request examples:

    1. OTP Template (REQUIRES otp):
    {
        "to": "919876543210",
        "spoken_template": "otp verification",
        "otp": "123456"
    }

    2. Marketing Templates (with params):
    {
        "to": "919876543210",
        "spoken_template": "crm test",
        "params": ["John Doe"]
    }

    3. Templates with headers:
    {
        "to": "919876543210",
        "spoken_template": "top rewards",
        "params": ["Premium Member"]
    }
    """
    if not require_api_key(request):
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    try:
        data = request.get_json(force=True, silent=True) or {}

        # Extract fields
        to_number = data.get("to", "").strip()
        spoken_template = data.get('spoken_template', '').strip()
        params = data.get("params") or []
        otp = data.get("otp")  # may be None for non-OTP templates

        if not to_number:
            return jsonify({"ok": False, "error": "Missing 'to' field"}), 400
        if not spoken_template:
            return jsonify({"ok": False, "error": "Missing 'spoken_template' field"}), 400

        # Auto-correct template name using fuzzy matching
        from template_matcher import find_best_matching_template

        matched_template = find_best_matching_template(spoken_template)
        if matched_template:
            spoken_template = matched_template
            print(f"[info] Template auto-corrected to: {spoken_template}")
        else:
            return jsonify({
                "ok": False,
                "error": "Template not found",
                "suggestion": "Could not match template. Try speaking clearer or check template name."
            }), 400

        # Normalize phone number to digits; pingbix.send_template will E.164 it
        to_number = to_number.replace("+", "").replace("-", "").replace(" ", "")
        if not to_number.isdigit() or len(to_number) < 10:
            return jsonify({"ok": False, "error": "Invalid phone number"}), 400

        # Check if this is an authentication template
        template_info = get_template_info(spoken_template)
        if template_info and template_info.get("type") == "authentication":
            if not otp:
                return jsonify({
                    "ok": False,
                    "error": "OTP is Required For Authentication Template Messages.!",
                    "template_type": "authentication",
                    "suggestion": f"Template '{spoken_template}' requires OTP. Please provide 'otp' field in request."
                }), 400
            print(f"[info] Authentication template detected - OTP: {otp}")

        # Optional: build payload just for debug / validation
        payload_preview = build_template_payload(to_number, spoken_template, params=params, otp=otp)
        if not payload_preview:
            return jsonify({
                "ok": False,
                "error": f"Failed to build payload for template '{spoken_template}'"
            }), 400

        print(f"[DEBUG] Payload preview: {payload_preview}")

        # Send via Pingbix (this will add 'from', normalize 'to', attach otp/params)
        status_code, response = send_template(
            to_number,
            spoken_template,
            params=params,
            otp=otp
        )

        return jsonify({
            "ok": 200 <= status_code < 300,
            "response": response,
            "status_code": status_code,
            "template": spoken_template,
            "to": to_number
        }), status_code

    except Exception as e:
        print(f"[error] /send/template-voice exception: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500

# -------------------------
# STANDARD TEMPLATE SENDER (legacy compatibility)
# -------------------------
@app.route("/send/template", methods=["POST"])
def send_template_api():
    """Legacy endpoint - maintained for backward compatibility"""
    if not require_api_key(request):
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    data = request.get_json() or {}

    raw_to = data.get("to") or data.get("recipient") or data.get("msisdn")
    template_name = data.get("template") or data.get("template_name") or data.get("templateName")

    params = data.get("params")
    if not params:
        params = []
        for i in range(1, 11):
            k = f"param{i}"
            if k in data:
                params.append(data[k])

    if not raw_to:
        return jsonify({"ok": False, "error": "missing_to"}), 400
    if not template_name:
        return jsonify({"ok": False, "error": "missing_template"}), 400

    to = normalize_msisdn(raw_to)
    if not to:
        return jsonify({"ok": False, "error": "invalid_phone_number"}), 400

    try:
        status, resp = send_template(to, template_name, params=params)
        return jsonify({"ok": 200 <= status < 300, "status_code": status, "response": resp}), status
    except Exception as e:
        return jsonify({"ok": False, "error": "send_failed", "reason": str(e)}), 500

# -------------------------
# START SERVER
# -------------------------
if __name__ == "__main__":
    print("🚀 Starting WhatsApp Voice Sender...")
    print(f"HOST={FLASK_HOST}, PORT={FLASK_PORT}")
    print(f"Templates loaded from template_config.json: {list_all_templates()}")
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=True)
