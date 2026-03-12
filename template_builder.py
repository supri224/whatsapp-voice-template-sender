"""
Dynamic template payload builder.
Reads from template_config.json and builds correct payload structure.
Works with ALL template types: authentication, text with/without headers.
"""

import json
import os


def load_template_config():
    """Load template configuration from JSON file."""
    # Try multiple paths for flexibility
    possible_paths = [
        os.path.join(os.path.dirname(__file__), "template_config.json"),
        "template_config.json",
        os.path.join(os.getcwd(), "template_config.json")
    ]
    
    for config_path in possible_paths:
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    templates = config.get('templates', {})
                    print(f"✓ Loaded {len(templates)} templates from {config_path}")
                    return templates
            except Exception as e:
                print(f"[warn] Failed to load {config_path}: {e}")
                continue
    
    print("[error] template_config.json not found in any expected location")
    return {}


def build_template_payload(to, template_name, params=None, otp=None):
    """
    Build complete template payload based on configuration.
    Works with ALL template types.
    
    Args:
        to: Phone number
        template_name: Template name (e.g., "otp_verification", "crmtest", "toprewards")
        params: List of parameters for body (e.g., ["John Doe"])
        otp: OTP code (only for authentication templates)
    
    Returns:
        Dictionary with complete payload ready for Pingbix API, or None if template not found
    """
    templates_config = load_template_config()
    
    if not templates_config:
        print("[error] No templates loaded from config")
        return None
    
    if template_name not in templates_config:
        print(f"[error] Template '{template_name}' not found in config")
        print(f"[info] Available templates: {', '.join(templates_config.keys())}")
        return None
    
    template_info = templates_config[template_name]
    print(f"[info] Building payload for '{template_name}'")
    
    # Normalize phone number
    if isinstance(to, str):
        to = to.strip().replace("+", "").replace("-", "").replace(" ", "")
    
    # Base payload (always needed)
    payload = {
        "recipient_type": "individual",
        "to": to,
        "type": "template",
        "templateName": template_name,
        "campaignName": "voice-api"
    }
    
    # Handle authentication (OTP) templates
    if template_info.get("type") == "authentication":
        if otp:
            payload["otp"] = str(otp)
        else:
            payload["otp"] = "000000"
        
        payload["language"] = {"code": "en"}
        print(f"[info] Authentication template - OTP code: {payload['otp']}")
        return payload
    
    # Handle regular text templates with components (headers, body params)
    components = {}
    
    # Add header if template has one
    if template_info.get("has_header"):
        header_type = template_info.get("header_type", "text")
        
        if header_type == "text":
            components["header"] = {
                "type": "text",
                "text": template_info.get("header_text", "Default Header")
            }
            print(f"[info] Added text header")
        
        elif header_type == "image":
            components["header"] = {
                "type": "image",
                "image": {
                    "link": template_info.get("header_image", "https://example.com/image.jpg")
                }
            }
            print(f"[info] Added image header: {template_info.get('header_image')}")
        
        elif header_type == "video":
            components["header"] = {
                "type": "video",
                "video": {
                    "link": template_info.get("header_video_url", "https://example.com/video.mp4")
                }
            }
            print(f"[info] Added video header")
        
        elif header_type == "document":
            components["header"] = {
                "type": "document",
                "document": {
                    "link": template_info.get("header_document_url", "https://example.com/doc.pdf"),
                    "filename": template_info.get("header_document_filename", "document.pdf")
                }
            }
            print(f"[info] Added document header")
    
    # Add body parameters if needed
    expected_params_count = template_info.get("params_count", 0)
    
    if expected_params_count > 0:
        # Use provided params or generate defaults
        if not params:
            params = [f"param{i+1}" for i in range(expected_params_count)]
        
        # Trim to expected count
        params = params[:expected_params_count]
        
        components["body"] = {
            "params": params
        }
        
        print(f"[info] Added body params ({len(params)} params): {params}")
    
    # Add components to payload if any exist
    if components:
        payload["components"] = components
        print(f"[info] Payload structure: {list(components.keys())}")
    else:
        print(f"[info] No components - simple text template")
    
    return payload


def get_template_info(template_name):
    """
    Get info about a template without building payload.
    
    Returns: dict with template info or None
    """
    templates_config = load_template_config()
    if not templates_config:
        return None
    return templates_config.get(template_name)


def list_all_templates():
    """
    List all available templates with their details.
    
    Returns: dict of all templates
    """
    templates_config = load_template_config()
    return templates_config


# Test function
if __name__ == "__main__":
    print("Testing template_builder with 3 templates...\n")
    
    test_cases = [
        ("919380589263", "otp_verification", None, "123456"),
        ("919380589263", "crmtest", ["John Doe"], None),
        ("919380589263", "toprewards", ["Premium Member"], None),
    ]
    
    for to, template, params, otp in test_cases:
        print(f"\n{'='*60}")
        print(f"Testing: {template}")
        print(f"{'='*60}")
        payload = build_template_payload(to, template, params, otp)
        if payload:
            print("✓ Payload built successfully:")
            print(json.dumps(payload, indent=2))
        else:
            print("✗ Failed to build payload")
        print()
