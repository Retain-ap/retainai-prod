"""Parse contact files (CSV and vCard) into RetainAI lead fields.

Pure functions only: no storage, sessions or network. The import routes in
app_imports.py validate, deduplicate and save the rows this module returns.
"""

import csv
import datetime
import io
import quopri
import re

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_ROWS = 5000
MAX_FIELD_CHARS = {
    "name": 160, "first_name": 80, "last_name": 80, "email": 254, "phone": 32,
    "company": 160, "title": 120, "notes": 2000, "birthday": 10,
}
FIELDS = ("name", "first_name", "last_name", "email", "phone", "company", "title", "notes", "birthday")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Header aliases, compared after normalising case, punctuation and spacing.
# Order matters: the first alias present in a file wins.
ALIASES = {
    "name": ["name", "full name", "display name", "contact name", "person name", "customer", "contact",
             "customer name", "client name", "lead name"],
    "first_name": ["first name", "firstname", "given name", "first", "contact first name", "person first name"],
    "last_name": ["last name", "lastname", "surname", "family name", "last", "contact last name",
                  "person last name"],
    "email": ["email", "email address", "e mail", "e mail address", "email 1", "e mail 1 value",
              "email 1 value", "primary email", "work email", "personal email", "person email",
              "person email work", "person email home", "person email other", "contact email",
              "email address 1", "e mail 2 address", "home email", "other email"],
    "phone": ["mobile", "mobile phone", "mobile phone number", "cell", "cell phone", "whatsapp",
              "whatsapp number", "phone", "phone number", "phone 1", "phone 1 value", "primary phone",
              "telephone", "person phone", "person phone mobile", "person phone work",
              "person phone home", "person phone other", "work phone", "business phone",
              "home phone", "other phone", "contact phone"],
    "company": ["company", "company name", "organization", "organization name", "organisation",
                "account name", "account", "business", "business name", "person organization",
                "organization 1 name", "company 1"],
    "title": ["title", "job title", "role", "position", "organization title", "organization 1 title",
              "job"],
    "notes": ["notes", "note", "description", "comments", "comment", "person notes", "lead notes"],
    "birthday": ["birthday", "birth date", "birthdate", "date of birth", "dob"],
}

# Signature headers used only to label the detected export, never to restrict it.
PRESETS = [
    ("pipedrive", "Pipedrive", {"person name", "person email", "person phone"}),
    ("hubspot", "HubSpot", {"record id", "first name", "last name", "email"}),
    ("hubspot", "HubSpot", {"contact owner", "lifecycle stage", "email"}),
    ("salesforce", "Salesforce", {"account name", "mailing street", "first name"}),
    ("salesforce", "Salesforce", {"contact id", "account name", "first name"}),
    ("zoho", "Zoho CRM", {"contact owner", "account name", "first name", "mobile"}),
    ("zoho", "Zoho CRM", {"lead owner", "first name", "mobile"}),
    ("google", "Google Contacts", {"e mail 1 value", "phone 1 value"}),
    ("google", "Google Contacts", {"given name", "family name", "e mail 1 value"}),
    ("outlook", "Outlook", {"e mail address", "mobile phone", "first name"}),
    ("outlook", "Outlook", {"e mail address", "business phone", "first name"}),
]


class ContactImportError(ValueError):
    """A file the importer cannot read; the message is safe to show users."""


def normalize_header(value):
    text = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower())
    return re.sub(r"\s+", " ", text).strip()


def _decode(raw):
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", errors="replace")
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", errors="replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def detect_format(filename, text):
    name = str(filename or "").lower()
    if name.endswith((".vcf", ".vcard")) or text.lstrip().upper().startswith("BEGIN:VCARD"):
        return "vcard"
    if name.endswith((".csv", ".tsv", ".txt")):
        return "csv"
    raise ContactImportError("Choose a CSV (.csv) or vCard (.vcf) contact file.")


def suggest_mapping(headers):
    normalized = {normalize_header(header): header for header in headers}
    mapping = {}
    for field, aliases in ALIASES.items():
        mapping[field] = next((normalized[alias] for alias in aliases if alias in normalized), "")
    return mapping


def detect_preset(headers):
    present = {normalize_header(header) for header in headers}
    for key, label, signature in PRESETS:
        if signature <= present:
            return {"key": key, "label": label}
    return {"key": "generic", "label": "Spreadsheet (CSV)"}


def parse_csv(text):
    sample = text[:20000]
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        delimiter = "\t" if sample.count("\t") > sample.count(",") else ","
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    try:
        header_row = next(reader)
    except StopIteration:
        raise ContactImportError("The file is empty.")
    headers, seen = [], {}
    for index, value in enumerate(header_row):
        header = str(value or "").strip() or f"Column {index + 1}"
        if header in seen:
            seen[header] += 1
            header = f"{header} ({seen[header]})"
        else:
            seen[header] = 1
        headers.append(header)
    if not any(normalize_header(h) for h in headers):
        raise ContactImportError("The first row must contain column names.")
    rows, truncated = [], False
    for values in reader:
        if not any(str(v or "").strip() for v in values):
            continue
        if len(rows) >= MAX_ROWS:
            truncated = True
            break
        rows.append({header: str(values[i] if i < len(values) else "").strip() for i, header in enumerate(headers)})
    return headers, rows, truncated


def _unfold(text):
    # RFC 6350/2425 folding: continuation lines start with a space or tab.
    # vCard 2.1 quoted-printable soft breaks end with "=".
    lines, current = [], None
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if current is not None and line[:1] in (" ", "\t"):
            current += line[1:]
            continue
        if current is not None and current.endswith("=") and "QUOTED-PRINTABLE" in current.upper().split(":", 1)[0]:
            current = current + "\n" + line
            continue
        if current is not None:
            lines.append(current)
        current = line
    if current is not None:
        lines.append(current)
    return lines


def _vcard_value(params, value):
    upper = [p.upper() for p in params]
    charset = next((p.split("=", 1)[1] for p in params if p.upper().startswith("CHARSET=")), "utf-8")
    if "ENCODING=QUOTED-PRINTABLE" in upper or "QUOTED-PRINTABLE" in upper:
        try:
            value = quopri.decodestring(value.replace("=\n", "").encode("latin-1", errors="ignore")).decode(charset, errors="replace")
        except LookupError:
            value = quopri.decodestring(value.replace("=\n", "").encode("latin-1", errors="ignore")).decode("utf-8", errors="replace")
    value = value.replace("\\n", "\n").replace("\\N", "\n")
    return re.sub(r"\\([,;:\\])", r"\1", value).strip()


def _split_unescaped(value, sep=";"):
    return [part.replace("\\" + sep, sep) for part in re.split(r"(?<!\\)" + re.escape(sep), value)]


def _types(params):
    found = set()
    for param in params:
        key, _, val = param.partition("=")
        items = val if _ else key
        if _ and key.upper() not in ("TYPE",):
            continue
        found.update(t.strip('"').upper() for t in items.split(",") if t)
    return found


def parse_vcard(text):
    rows, current, truncated = [], None, False
    for line in _unfold(text):
        if not line.strip():
            continue
        head, sep, raw_value = line.partition(":")
        if not sep:
            continue
        parts = head.split(";")
        prop = parts[0].split(".")[-1].upper()  # drop Apple "item1." group prefixes
        params = parts[1:]
        if prop == "BEGIN" and raw_value.strip().upper() == "VCARD":
            current = {"emails": [], "phones": []}
            continue
        if current is None:
            continue
        if prop == "END" and raw_value.strip().upper() == "VCARD":
            if len(rows) >= MAX_ROWS:
                truncated = True
                break
            rows.append(_card_to_row(current))
            current = None
            continue
        value = _vcard_value(params, raw_value)
        if prop == "FN":
            current["fn"] = value
        elif prop == "N":
            pieces = _split_unescaped(raw_value) + ["", ""]
            current["last"] = _vcard_value(params, pieces[0])
            current["first"] = _vcard_value(params, pieces[1])
        elif prop == "EMAIL" and value:
            current["emails"].append((_types(params), value.removeprefix("mailto:")))
        elif prop == "TEL" and value:
            current["phones"].append((_types(params), value.removeprefix("tel:")))
        elif prop == "ORG":
            current["org"] = _split_unescaped(value)[0].strip()
        elif prop == "TITLE":
            current["title"] = value
        elif prop == "NOTE":
            current["note"] = value
        elif prop == "BDAY":
            current["bday"] = value
    headers = ["Full name", "First name", "Last name", "Email", "Phone", "Organization", "Title", "Notes", "Birthday"]
    return headers, rows, truncated


def _pick(entries, preferred):
    for wanted in preferred:
        for types, value in entries:
            if wanted in types:
                return value
    for types, value in entries:
        if "PREF" in types:
            return value
    return entries[0][1] if entries else ""


def _card_to_row(card):
    return {
        "Full name": card.get("fn", ""),
        "First name": card.get("first", ""),
        "Last name": card.get("last", ""),
        "Email": _pick(card["emails"], ("PREF", "HOME", "WORK", "INTERNET")),
        "Phone": _pick(card["phones"], ("CELL", "MOBILE", "IPHONE", "PREF", "WORK", "HOME")),
        "Organization": card.get("org", ""),
        "Title": card.get("title", ""),
        "Notes": card.get("note", ""),
        "Birthday": card.get("bday", ""),
    }


def parse_file(filename, raw):
    if not raw:
        raise ContactImportError("The file is empty.")
    if len(raw) > MAX_FILE_BYTES:
        raise ContactImportError("Contact files must be 5 MB or smaller.")
    text = _decode(raw)
    kind = detect_format(filename, text)
    try:
        if kind == "vcard":
            headers, rows, truncated = parse_vcard(text)
            preset = {"key": "vcard", "label": "vCard (Apple, iCloud, Outlook, Android, WhatsApp)"}
        else:
            headers, rows, truncated = parse_csv(text)
            preset = detect_preset(headers)
    except (csv.Error, UnicodeError, ValueError) as exc:
        if isinstance(exc, ContactImportError):
            raise
        raise ContactImportError(
            "This file could not be read. Save it again as CSV (one row of column names) or vCard and retry."
        ) from None
    if not rows:
        raise ContactImportError("The file did not contain any contacts.")
    return {"format": kind, "preset": preset, "headers": headers, "rows": rows,
            "mapping": suggest_mapping(headers), "truncated": truncated}


def clean_phone(value, country_code="+1"):
    raw = str(value or "").strip()
    if not raw:
        return ""
    raw = re.split(r"(?i)\s*(?:ext\.?|x|#)\s*\d+$", raw)[0]
    has_plus = raw.startswith("+") or raw.startswith("00")
    digits = re.sub(r"\D", "", raw)
    if raw.startswith("00"):
        digits = digits[2:]
    if not digits:
        return ""
    if has_plus:
        return f"+{digits}"
    prefix = re.sub(r"\D", "", str(country_code or "+1"))
    if len(digits) == 10 and prefix:
        return f"+{prefix}{digits}"
    if len(digits) == 11 and digits.startswith("1") and prefix == "1":
        return f"+{digits}"
    return f"+{digits}"


# The whole trimmed value must be one of these; nothing is accepted by prefix.
BIRTHDAY_FORMATS = (
    re.compile(r"(\d{4})-(\d{2})-(\d{2})"),  # YYYY-MM-DD
    re.compile(r"(\d{4})(\d{2})(\d{2})"),    # YYYYMMDD
    re.compile(r"(--)(\d{2})-?(\d{2})"),      # vCard/Google no-year: --MM-DD or --MMDD
)


def normalize_birthday(value):
    """ISO dates only: YYYY-MM-DD, YYYYMMDD, or --MM-DD / --MMDD without a year.

    Slash dates such as 02/03/1990 are not guessed: they could be day-first or
    month-first. Impossible dates (February 31) and values with anything else
    around the date are rejected.
    """
    text = str(value or "").strip()
    for pattern in BIRTHDAY_FORMATS:
        match = pattern.fullmatch(text)
        if not match:
            continue
        year = "0000" if match.group(1) == "--" else match.group(1)
        month, day = int(match.group(2)), int(match.group(3))
        try:
            # A missing year is checked against a leap year so 29 February stays valid.
            datetime.date(2000 if year == "0000" else int(year), month, day)
        except ValueError:
            return ""
        return f"{year}-{month:02d}-{day:02d}"
    return ""


def build_contact(raw, mapping, country_code="+1"):
    """Return (contact, problem) for one source row and a field mapping.

    contact is None when the row has neither a valid email nor a valid phone;
    otherwise problem names a value that was dropped (or is empty).
    """
    def take(field):
        column = mapping.get(field) or ""
        value = str((raw or {}).get(column, "") if column else "").strip()
        return value[:MAX_FIELD_CHARS[field]]

    first, last = take("first_name"), take("last_name")
    name = take("name") or f"{first} {last}".strip()
    email = take("email").lower()
    if "," in email or ";" in email:
        email = re.split(r"[,;]", email)[0].strip()
    phone_raw = take("phone")
    if "," in phone_raw or ";" in phone_raw:
        phone_raw = re.split(r"[,;]", phone_raw)[0].strip()
    phone = clean_phone(phone_raw, country_code)
    problem = ""
    if email and not EMAIL_RE.match(email):
        problem, email = "invalid_email", ""
    digits = re.sub(r"\D", "", phone)
    if phone and not 7 <= len(digits) <= 15:
        problem, phone = problem or "invalid_phone", ""
    if not (email or phone):
        return None, problem or "missing_email_or_phone"
    # Validate the whole source value: truncating first could leave a valid prefix.
    birthday_column = mapping.get("birthday") or ""
    birthday_raw = str((raw or {}).get(birthday_column, "") if birthday_column else "").strip()
    birthday = normalize_birthday(birthday_raw)
    if birthday_raw and not birthday:
        # The contact is still imported; the unreadable birthday is reported.
        problem = problem or "invalid_birthday"
    contact = {
        "name": (name or email or phone)[:MAX_FIELD_CHARS["name"]],
        "email": email,
        "phone": phone,
        "company": take("company"),
        "title": take("title"),
        "notes": take("notes"),
        "birthday": birthday,
    }
    # A contact with one usable channel is kept; the dropped value is reported.
    return contact, problem
