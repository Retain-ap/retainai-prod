"""Check or add the unsubscribe footer in RetainAI's customer-facing SendGrid templates.

RetainAI already sends a signed ``unsubscribe_url`` in the dynamic data and the
List-Unsubscribe headers, but a dynamic template only shows a visible link if
its HTML uses that variable. This tool reports which templates lack it and can
add one.

Usage (run it yourself; the API key is read from SENDGRID_API_KEY or a hidden
prompt and is never printed):

    python backend/sendgrid_unsubscribe_footer.py            # report only
    python backend/sendgrid_unsubscribe_footer.py --apply    # add missing footers

--apply never edits the live version in place. It creates a new code-editor
version with the footer and makes it active, so the previous version stays in
SendGrid and can be re-activated from the dashboard to roll back.
"""

import argparse
import datetime
import getpass
import os
import re
import sys

import requests


API = "https://api.sendgrid.com/v3"

# Templates whose recipients are a business's customers (not RetainAI users).
CUSTOMER_TEMPLATES = {
    "d-94133232d9bd48e0864e21dce34158d3": "Birthday",
    "d-b40c227ed00e4cd29fdeb10dcc71a268": "AI follow-up",
    "d-9c6ac36680c8473a84dda817fb58e7b7": "AI re-engage",
    "d-64abfc217ce443d59c2cb411fc85cc74": "AI apology",
    "d-a7a2c04c57e344aebd6a94559ae71ea9": "AI upsell",
}

# Matches app._append_unsubscribe_footer so every customer email looks the same.
HTML_FOOTER = (
    "{{#if unsubscribe_url}}"
    "<div style=\"margin-top:28px;padding-top:16px;border-top:1px solid #ddd;"
    "font-size:12px;line-height:1.5;color:#666\">"
    "You received this message from {{business_name}}. "
    "<a href=\"{{unsubscribe_url}}\">Unsubscribe from email follow-ups</a>."
    "</div>"
    "{{/if}}"
)
TEXT_FOOTER = (
    "{{#if unsubscribe_url}}\n\n"
    "Unsubscribe from email follow-ups: {{unsubscribe_url}}"
    "{{/if}}"
)
_HAS_LINK = re.compile(r"\{\{\{?\s*(unsubscribe_url|unsubscribe_link)\b")


def has_unsubscribe_link(html_content):
    return bool(_HAS_LINK.search(html_content or ""))


def add_footer(html_content, plain_content):
    """Return (html, plain) with the footer added before </body> or at the end."""
    html_body = html_content or ""
    if re.search(r"</body\s*>", html_body, flags=re.I):
        html_body = re.sub(r"</body\s*>", HTML_FOOTER + "</body>", html_body, count=1, flags=re.I)
    else:
        html_body += HTML_FOOTER
    plain = plain_content or ""
    if plain and not _HAS_LINK.search(plain):
        plain += TEXT_FOOTER
    return html_body, plain


def _active_version(template):
    versions = template.get("versions") or []
    return next((v for v in versions if v.get("active") == 1), None)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true", help="add the footer where it is missing")
    args = parser.parse_args()

    key = os.getenv("SENDGRID_API_KEY") or getpass.getpass("SendGrid API key (hidden): ")
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {key.strip()}"

    missing = 0
    for template_id, label in CUSTOMER_TEMPLATES.items():
        response = session.get(f"{API}/templates/{template_id}", timeout=30)
        if response.status_code != 200:
            print(f"[{label}] could not load {template_id}: HTTP {response.status_code}")
            missing += 1
            continue
        version = _active_version(response.json())
        if not version:
            print(f"[{label}] has no active version")
            missing += 1
            continue
        if has_unsubscribe_link(version.get("html_content")):
            print(f"[{label}] OK: already shows an unsubscribe link")
            continue

        missing += 1
        if not args.apply:
            print(f"[{label}] MISSING unsubscribe link (active version: {version.get('name')})")
            continue

        html_body, plain = add_footer(version.get("html_content"), version.get("plain_content"))
        stamp = datetime.date.today().isoformat()
        new_version = {
            "active": 1,
            "name": f"{(version.get('name') or label)[:70]} + unsubscribe {stamp}",
            "subject": version.get("subject") or "{{subject}}",
            "html_content": html_body,
            "editor": "code",
        }
        if plain:
            new_version["plain_content"] = plain
        else:
            new_version["generate_plain_content"] = True
        created = session.post(f"{API}/templates/{template_id}/versions", json=new_version, timeout=30)
        if created.status_code in (200, 201):
            print(f"[{label}] FIXED: new active version '{new_version['name']}' "
                  f"(previous '{version.get('name')}' kept for rollback)")
            missing -= 1
        else:
            print(f"[{label}] update failed: HTTP {created.status_code} {created.text[:200]}")

    if missing and not args.apply:
        print("\nRe-run with --apply to add the footer to the templates marked MISSING.")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
