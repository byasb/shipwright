"""Seed apps/{app_id} in Firestore with the operator facts the API cannot know.
Usage: .venv/bin/python scripts/seed_app.py [--print]
"""
import json
import sys

SNIPSTASH = {
    "app_id": "6803901837",
    "bundle_id": "com.utenx.snipstash",
    "brand": "SnipStash",
    "company": "Ankit Singh Bhandari",
    "primary_category": "PRODUCTIVITY",
    "secondary_category": "UTILITIES",
    "content_rights": "DOES_NOT_USE_THIRD_PARTY_CONTENT",
    "support_url": "https://byasb.com/snipstash",
    "privacy_url": "https://byasb.com/snipstash/privacy",
    "contact_phone": "",  # operator fills; Apple requires country code
    "age_rating": {},     # all defaults (NONE/false) — no objectionable content
    "brand_colors": {"bg_top": "#5856D6", "bg_bottom": "#8E5CF6", "text": "#FFFFFF"},
    "facts": """
SnipStash is a clipboard and snippet manager for iPhone.
What it does: keeps everything you copy in one searchable vault — text, links, code, images, files.
Core mechanic: tap any saved snippet to copy it back to the clipboard instantly (haptic confirm).
Features (ship in v1.0):
- Save from anywhere via the iOS Share Sheet (text, URL, image)
- "Save clipboard?" banner when the app opens with something new on the clipboard (reads clipboard ONLY after the user taps Save — no paste-permission nag)
- Smart auto-title and auto-tags (URL / code / email / phone detection, on-device heuristics)
- Pinned + Recent sections, full-text search, colour-coded tags (personal/work/code/links), tag manager
- Home Screen widget listing pinned snippets; tapping one copies it
- Siri Shortcuts / App Intents: "Save Snippet" and "Search Snippets"
- Free tier: 25 snippets. SnipStash Pro (monthly subscription or one-time lifetime) unlocks unlimited snippets.
Privacy: all data stored on-device (SwiftData); no account, no server, no analytics SDK. Nothing leaves the phone.
Permissions: none required. Clipboard is read only on explicit Save tap.
Audience: developers, support staff, sales reps, anyone who pastes the same things daily (addresses, UPI IDs, sign-offs, links).
Not in v1.0: iCloud sync, OCR, custom keyboard, Mac app. Do not mention these.
Monetisation facts for review notes: paywall reachable from Settings → SnipStash Pro, and when adding the 26th snippet. Restore Purchases button is on the paywall. Prices load from StoreKit.
""".strip(),
    "review_notes_extra": "Sample data: the app seeds 10 demo snippets on first launch so every screen is populated. No demo account is needed — there is no login.",
    "screens": {
        "list": "main list: Pinned + Recent snippets with colour kind-chips, search bar, floating add button",
        "edit": "add/edit snippet sheet with content field and tag picker",
        "tags": "tag manager with colour-coded tags",
        "settings": "settings: storage usage bar (n/25), SnipStash Pro card, sample data controls",
        "paywall": "SnipStash Pro paywall: feature rows, plan tiles (monthly / lifetime), Restore button",
    },
}

if __name__ == "__main__":
    if "--print" in sys.argv:
        print(json.dumps(SNIPSTASH, indent=2)); sys.exit()
    from shipwright import store
    store.put_app(SNIPSTASH["app_id"], SNIPSTASH)
    print("seeded apps/" + SNIPSTASH["app_id"])
