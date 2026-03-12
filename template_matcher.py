"""
Smart template name matcher.
Converts voice input to actual template names.
Reads from template_config.json instead of hardcoded list.

Example: "send otp verification to..." → finds "otp_verification"
"""

import re
from difflib import SequenceMatcher
from template_builder import list_all_templates


def get_all_templates_from_config():
    """
    Fetch all templates from template_config.json via template_builder.
    This ensures we always match against actual registered templates.
    """
    templates_config = list_all_templates()

    if not templates_config:
        print("[warn] No templates found in template_config.json")
        return []

    # Extract template names (keys from config)
    template_names = list(templates_config.keys())
    print(f"[info] Loaded {len(template_names)} templates from config: {template_names}")

    return template_names


def normalize_template_name(spoken_text):
    """
    Convert spoken text to lowercase, remove extra spaces/punctuation.

    Examples:
    - "OTP Verification" → "otpverification"
    - "CRM Test" → "crmtest"
    - "Top Rewards" → "toprewards"
    """
    if not spoken_text:
        return ""

    # Remove punctuation, convert to lowercase
    normalized = re.sub(r"[^\w\s]", "", spoken_text.lower())
    # Remove all spaces
    normalized = re.sub(r"\s+", "", normalized)

    return normalized


def find_best_matching_template(spoken_template_name, templates_list=None):
    """
    Find the closest matching template from the config.
    Uses fuzzy matching (SequenceMatcher).

    Args:
        spoken_template_name: What the user said (e.g., "otp verification")
        templates_list: Optional list of templates. If None, loads from config.

    Returns:
        Best matching template name from config, or None if confidence too low.

    Examples:
    - "otp verification" → "otp_verification"
    - "crm test" → "crmtest"
    - "top rewards" → "toprewards"
    - "qr template" → "qr"
    - "diwali campaign" → "diwali_campaign"
    """
    # Load templates from config if not provided
    if templates_list is None:
        templates_list = get_all_templates_from_config()

    if not templates_list:
        print("[error] No templates available for matching")
        return None

    if not spoken_template_name or not spoken_template_name.strip():
        print("[warn] Empty spoken template name")
        return None

    spoken_normalized = normalize_template_name(spoken_template_name)
    spoken_lower = spoken_template_name.strip().lower()

    print(f"\n[Template Match]")
    print(f"  Spoken input: '{spoken_template_name}'")
    print(f"  Normalized: '{spoken_normalized}'")

    # -------------------------
    # 1) Keyword aliases (fast paths)
    # -------------------------
    # Handle common phrases that should map directly

    # "qr template", "send qr template", etc. → qr
    if "qr" in spoken_lower and "template" in spoken_lower:
        if "qr" in templates_list:
            print("  [alias] Detected 'qr template' phrase → forcing template 'qr'")
            return "qr"

    # Anything mentioning "diwali" → diwali_campaign (if present)
    if "diwali" in spoken_lower:
        if "diwali_campaign" in templates_list:
            print("  [alias] Detected 'diwali' phrase → forcing template 'diwali_campaign'")
            return "diwali_campaign"

    # -------------------------
    # 2) Fuzzy similarity for all templates
    # -------------------------
    scores = []
    for template in templates_list:
        template_normalized = normalize_template_name(template)

        # Use SequenceMatcher to find similarity ratio (0.0 to 1.0)
        ratio = SequenceMatcher(None, spoken_normalized, template_normalized).ratio()
        scores.append((template, ratio))

    # Sort by score (highest first)
    scores.sort(key=lambda x: x[1], reverse=True)

    best_match, best_score = scores[0]

    print(f"  Best match: '{best_match}' (confidence: {best_score*100:.1f}%)")
    print(f"  Top matches:")
    for i, (tmpl, score) in enumerate(scores[:3], 1):
        print(f"    {i}. {tmpl} ({score*100:.1f}%)")

    # -------------------------
    # 3) Adaptive confidence threshold
    # -------------------------
    # Default minimum confidence
    min_conf = 0.6

    # For very short inputs like "qr" or "mo", allow lower threshold
    if len(spoken_normalized) <= 4:
        min_conf = 0.4

    if best_score >= min_conf:
        print(f"  ✓ Match accepted (confidence >= {min_conf*100:.0f}%)")
        return best_match
    else:
        print(f"  ✗ Match rejected (confidence {best_score*100:.1f}% < {min_conf*100:.0f}%)")
        return None


# Test examples
if __name__ == "__main__":
    print("Testing template_matcher with template_config.json...\n")

    test_cases = [
        "otp verification",
        "otp verify",
        "crm test",
        "crmtest",
        "top rewards",
        "toprewards",
        "cram test",        # Should match crmtest
        "reward",           # Should match toprewards
        "qr",               # Should match qr
        "qr template",      # Should match qr via alias
        "diwali campaign",  # Should match diwali_campaign via alias
        "random xyz",       # Should NOT match
        "tpx",              # Should NOT match
    ]

    print("=" * 60)
    for test in test_cases:
        result = find_best_matching_template(test)
        print(f"Final result: {result}")
        print("=" * 60)
