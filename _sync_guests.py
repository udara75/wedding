"""Sync guests-test.txt → guests.js + invite-links (+ Apps Script list)

Source format:
  1. Mr. Udara Kavinda | C
  53. Mr. New Guest
  132. Mrs. Weranga Kaweesha | END
  51. Mr. Aruna Edirimanne | END:6

Codes: C / R / 1–18 / NA (not attending) / END (additional, RSVP Nov 30)
       END:6 = additional + seated at table 6

FIXED list numbers: saved in guest-numbers.json — never renumber existing guests.
FIXED hex codes: saved in guest-codes.json — never change existing invite links.
"""
import json
import re
from pathlib import Path

root = Path(__file__).resolve().parent
site = "https://udara75.github.io/wedding/"
codes_path = root / "guest-codes.json"
numbers_path = root / "guest-numbers.json"

HEX_OFFSET_N = 42
HEX_LETTERS = "abcdef"
HEX_LETTER_BASE = len(HEX_LETTERS)
HEX_LETTER_LEN = 3
HEX_LETTER_CAPACITY = HEX_LETTER_BASE**HEX_LETTER_LEN


def letter_hex_from_slot(slot: int) -> str:
    n = slot + HEX_OFFSET_N
    if n < 0 or n >= HEX_LETTER_CAPACITY:
        raise ValueError(f"slot {slot} with offset {HEX_OFFSET_N} out of range")
    digits = []
    for _ in range(HEX_LETTER_LEN):
        digits.append(HEX_LETTERS[n % HEX_LETTER_BASE])
        n //= HEX_LETTER_BASE
    return "0x" + "".join(reversed(digits))


def normalize_hex_code(raw):
    if raw is None:
        return None
    s = str(raw).strip().lower()
    m = re.fullmatch(r"(?:0x)?([a-f]{3})", s)
    if not m:
        return None
    return f"0x{m.group(1)}"


def slot_from_letter_hex(code):
    norm = normalize_hex_code(code)
    if not norm:
        return None
    n = 0
    for ch in norm[2:]:
        n = n * HEX_LETTER_BASE + HEX_LETTERS.index(ch)
    return n - HEX_OFFSET_N


def fix_title(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip()
    name = re.sub(r"^(Mr)\.?\s*&\s*(Mrs)\.?\s+", r"Mr. & Mrs. ", name, flags=re.I)
    name = re.sub(r"^(Dr)\.?\s+", r"Dr. ", name, flags=re.I)
    name = re.sub(r"^(Mr)\.?\s+", r"Mr. ", name, flags=re.I)
    name = re.sub(r"^(Miss)\.?\s+", r"Miss. ", name, flags=re.I)
    name = re.sub(r"^(Mrs)\.?\s+", r"Mrs. ", name, flags=re.I)
    name = re.sub(r"^dr\.", "Dr.", name, flags=re.I)
    name = re.sub(r"^mr\. & mrs\.", "Mr. & Mrs.", name, flags=re.I)
    name = re.sub(r"^mr\.", "Mr.", name, flags=re.I)
    name = re.sub(r"^miss\.", "Miss.", name, flags=re.I)
    name = re.sub(r"^mrs\.", "Mrs.", name, flags=re.I)
    return name


def to_id(n: str) -> str:
    n = re.sub(
        r"^(dr|mr\.?\s*&\s*mrs\.?|mr|mrs|miss|ms)\.?\s+",
        "",
        n,
        flags=re.I,
    )
    n = n.lower()
    return re.sub(r"[^a-z0-9]+", "-", n).strip("-")


def parse_assignment(raw: str):
    """Return (section, seat). END:6 = Additional + Table 6."""
    raw = (raw or "").strip()
    raw = re.sub(r"(?i)^table\s*", "", raw).strip()
    if not raw or raw in {"_", "-", "?", "tbd", "none", "null"}:
        return None, None
    code = re.sub(r"\s+", "", raw.upper())

    end_seat = re.fullmatch(r"(END|MORE|ADD|EXTRA)[:\-](\d+|[CR]|COUPLE)", code)
    if end_seat:
        seat = end_seat.group(2)
        if seat in {"C", "S", "COUPLE"}:
            seat = "C"
        elif seat in {"R", "R1", "R2"}:
            seat = "R"
        return "END", seat

    if code in {"END", "MORE", "ADD", "EXTRA"}:
        return "END", None
    if code in {"NA", "N/A", "NOT", "NO", "INVITE"}:
        return "NA", None
    if code in {"C", "S", "COUPLE"}:
        return "C", "C"
    if code in {"R", "R1", "R2"}:
        return "R", "R"
    u = re.match(r"^U(\d+)$", code)
    if u:
        return u.group(1), u.group(1)
    return code, code


def is_separator(line: str) -> bool:
    return bool(re.match(r"^-{3,}", line.strip()))


def normalize_rsvp_by(raw):
    """Optional custom RSVP deadline text, e.g. Dec 1 → December 1, 2026."""
    if raw is None:
        return None
    s = re.sub(r"\s+", " ", str(raw)).strip()
    if not s or s in {"_", "-", ""}:
        return None
    key = s.lower().replace(",", "").replace(".", "")
    aliases = {
        "dec 1": "December 1, 2026",
        "dec 01": "December 1, 2026",
        "december 1": "December 1, 2026",
        "december 1 2026": "December 1, 2026",
        "1 dec": "December 1, 2026",
        "1 december": "December 1, 2026",
        "nov 30": "November 30, 2026",
        "november 30": "November 30, 2026",
        "november 30 2026": "November 30, 2026",
        "nov 20": "November 20, 2026",
        "november 20": "November 20, 2026",
        "november 20 2026": "November 20, 2026",
    }
    if key in aliases:
        return aliases[key]
    return s


def parse_line(line: str):
    line = line.strip()
    if not line or line.startswith("#") or is_separator(line):
        return None

    section, seat, rsvp_by = None, None, None
    if "|" in line:
        parts = [p.strip() for p in line.split("|")]
        name_part = parts[0]
        if len(parts) > 1:
            section, seat = parse_assignment(parts[1])
        if len(parts) > 2:
            rsvp_by = normalize_rsvp_by(parts[2])
    else:
        name_part = line

    file_num = None
    num_match = re.match(r"^(\d+)\.\s*(.*)$", name_part)
    if num_match:
        file_num = int(num_match.group(1))
        name_part = num_match.group(2).strip()
    else:
        name_part = re.sub(r"^\d+\.\s*", "", name_part).strip()

    if not name_part:
        return None

    return fix_title(name_part), section, seat, file_num, rsvp_by


def section_label(section):
    if section is None:
        return "Unassigned"
    if section == "C":
        return "Couple"
    if section == "R":
        return "Reserved"
    if section == "NA":
        return "Not attending but invite"
    if section == "END":
        return "Additional"
    return f"Table {section}"


def table_group_key(section):
    if section == "C":
        return (0, 0)
    if section == "R":
        return (1, 0)
    if section is None:
        return (9, 0)
    if section == "NA":
        return (10, 0)
    if section == "END":
        return (11, 0)
    try:
        return (2, int(section))
    except (TypeError, ValueError):
        return (3, str(section))


def file_table_tag(section, seat):
    if section == "END" and seat:
        return f"END:{seat}"
    if section == "END":
        return "END"
    if section == "NA":
        return "NA"
    if section is None:
        return None
    return section


lines = (root / "guests-test.txt").read_text(encoding="utf-8").splitlines()
guests = []
seen_ids = {}
seen_names = set()
for i, line in enumerate(lines):
    parsed = parse_line(line)
    if not parsed:
        continue
    name, section, seat, file_num, rsvp_by = parsed
    name_key = re.sub(r"\s+", " ", name).strip().lower()
    if name_key in seen_names:
        continue
    seen_names.add(name_key)

    gid = to_id(name)
    if not gid:
        continue
    if gid in seen_ids:
        gid = f"{gid}-{i + 1}"
    seen_ids[gid] = True
    # Additional (END) default RSVP Nov 30 unless a custom date was set
    if rsvp_by is None and section == "END":
        rsvp_by = "November 30, 2026"
    guests.append(
        {
            "id": gid,
            "name": name,
            "section": section,
            "seat": seat,
            "file_num": file_num,
            "rsvp_by": rsvp_by,
        }
    )

# Sort by section group, keep relative order within group
indexed = list(enumerate(guests))
indexed.sort(key=lambda it: (*table_group_key(it[1]["section"]), it[0]))
guests = [g for _, g in indexed]

# FIXED list numbers — never renumber existing guests
saved_numbers = {}
if numbers_path.exists():
    try:
        raw_nums = json.loads(numbers_path.read_text(encoding="utf-8"))
        saved_numbers = {k: int(v) for k, v in raw_nums.items()}
    except (json.JSONDecodeError, TypeError, ValueError):
        saved_numbers = {}

used_numbers = set(saved_numbers.values())
# Seed from file prefixes for anyone not saved yet (first run / recovery)
for g in guests:
    if g["id"] in saved_numbers:
        continue
    n = g.get("file_num")
    if n is not None and n not in used_numbers:
        saved_numbers[g["id"]] = n
        used_numbers.add(n)

next_num = max(used_numbers) + 1 if used_numbers else 1


def alloc_number():
    global next_num
    while next_num in used_numbers:
        next_num += 1
    n = next_num
    used_numbers.add(n)
    next_num += 1
    return n


number_map = {}
for g in guests:
    if g["id"] in saved_numbers:
        num = saved_numbers[g["id"]]
    else:
        num = alloc_number()
    number_map[g["id"]] = num
    g["num"] = num

numbers_path.write_text(
    json.dumps(number_map, indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
)

# Within each section, show guests in number order (stable)
guests.sort(key=lambda g: (*table_group_key(g["section"]), g["num"]))

# FIXED letter-hex codes
saved_codes = {}
if codes_path.exists():
    try:
        saved_codes = json.loads(codes_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        saved_codes = {}

used_slots = set()
for raw in saved_codes.values():
    slot = slot_from_letter_hex(raw)
    if slot is not None and slot >= 0:
        used_slots.add(slot)

next_slot = 0


def alloc_letter_hex():
    global next_slot
    while next_slot in used_slots:
        next_slot += 1
    if next_slot + HEX_OFFSET_N >= HEX_LETTER_CAPACITY:
        raise RuntimeError("Ran out of 3-letter hex codes (a–f)")
    slot = next_slot
    used_slots.add(slot)
    next_slot += 1
    return letter_hex_from_slot(slot)


code_map = {}
for g in guests:
    existing = normalize_hex_code(saved_codes.get(g["id"]))
    if existing:
        code = existing
        slot = slot_from_letter_hex(code)
        if slot is not None and slot >= 0:
            used_slots.add(slot)
    else:
        code = alloc_letter_hex()
    code_map[g["id"]] = code
    g["code"] = code
    g["param"] = f"guest_{code}"
    g["token"] = f"{g['param']}={g['id']}"

codes_path.write_text(
    json.dumps(code_map, indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
)

out_lines = [
    "# Format: 1. Guest Name | TableCode",
    "# Optional RSVP date: 51. Name | 6 | December 1, 2026",
    "# Codes: C = Couple, R = Reserved, 1–18 = guest tables",
    "# NA = Not attending but invite | END = Additional (RSVP Nov 30) | END:6 = Additional + Table 6",
    "# List numbers are FIXED (guest-numbers.json). Do not renumber by hand.",
    "# Save this file, then run: python _sync_guests.py",
    "",
]
_SENTINEL = object()
current_section = _SENTINEL
for g in guests:
    if g["section"] != current_section:
        if current_section is not _SENTINEL:
            out_lines.append("")
        out_lines.append(f"------------------ {section_label(g['section'])} ------------------")
        current_section = g["section"]
    tag = file_table_tag(g["section"], g["seat"])
    # Don't rewrite END's default Nov 30 into the file (it's implied)
    rsvp_out = g.get("rsvp_by")
    if rsvp_out == "November 30, 2026" and g["section"] == "END":
        rsvp_out = None
    if tag is None and not rsvp_out:
        out_lines.append(f"{g['num']}. {g['name']}")
    elif tag is None and rsvp_out:
        out_lines.append(f"{g['num']}. {g['name']} | _ | {rsvp_out}")
    elif rsvp_out:
        out_lines.append(f"{g['num']}. {g['name']} | {tag} | {rsvp_out}")
    else:
        out_lines.append(f"{g['num']}. {g['name']} | {tag}")
(root / "guests-test.txt").write_text("\n".join(out_lines) + "\n", encoding="utf-8")

guest_js_rows = []
for g in guests:
    table_js = "null" if g["seat"] is None else f'"{g["seat"]}"'
    if g.get("rsvp_by"):
        guest_js_rows.append(
            f'  {{ id: "{g["id"]}", code: "{g["code"]}", name: "{g["name"]}", table: {table_js}, rsvpBy: "{g["rsvp_by"]}" }}'
        )
    else:
        guest_js_rows.append(
            f'  {{ id: "{g["id"]}", code: "{g["code"]}", name: "{g["name"]}", table: {table_js} }}'
        )

(root / "guests.js").write_text(
    f"""// Guest personalization — fixed letter-hex codes (a–f only, offset by n)
// Link format: ?guest_0xacf=<slug>
// Example: index.html?guest_0xacf=udara-kavinda
// Codes + list numbers stay fixed across syncs.
//
// Auto-generated from guests-test.txt — edit that file, then sync/watch.

const GUESTS = [
{",\n".join(guest_js_rows)},
];

const TABLE_LABELS = ["C", "R", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14", "15", "16", "17", "18"];

const SITE_URL = "{site}";

const RSVP_SCRIPT_URL =
  "https://script.google.com/macros/s/AKfycbx19BZ3IEICQu4u9wmkgE_7YI8p6kagOYgi2TDLtvFqMKT5UhayzkXrwdwz64gjp42_/exec";
""",
    encoding="utf-8",
)

link_lines = [
    "UDARA & SHAINY — INVITE LINKS TO SEND",
    "Format: guest_0x***=<guest-slug>  (letter-hex a–f only, fixed — does not change on re-sync)",
    "List numbers are FIXED. Moving a guest between sections does NOT change their number or link.",
    f"Offset n = {HEX_OFFSET_N}  |  Example: ?guest_0xacf=udara-kavinda",
    "Check each link, then send the matching one to that guest.",
    "",
    f"Base site: {site}",
    f"Total guests: {len(guests)}",
    "",
]
current_section = _SENTINEL
for g in guests:
    if g["section"] != current_section:
        if current_section is not _SENTINEL:
            link_lines.append("")
        link_lines.append(f"================== {section_label(g['section']).upper()} ==================")
        link_lines.append("")
        current_section = g["section"]
    if g["section"] == "NA":
        seat = "Not attending but invite"
    elif g["seat"]:
        seat = f"Table {g['seat']}"
        if g["section"] == "END":
            seat += " (Additional · RSVP by Nov 30)"
    elif g["section"] == "END":
        seat = "Additional · RSVP by Nov 30 · Table TBD"
    else:
        seat = "Table TBD"
    link_lines.append(f"{g['num']}. {g['name']}")
    link_lines.append(f"   Seat: {seat}")
    link_lines.append(f"   Code: {g['code']}")
    link_lines.append(f"   Slug: {g['id']}")
    link_lines.append(f"   Link: {site}?{g['token']}")
    link_lines.append(f"   [ ] Checked   [ ] Sent")
    link_lines.append("")
(root / "invite-links-test.txt").write_text("\n".join(link_lines), encoding="utf-8")
(root / "invite-links-to-send.txt").write_text("\n".join(link_lines), encoding="utf-8")

gs_path = root / "google-sheet-rsvp.gs"
if gs_path.exists():
    gs = gs_path.read_text(encoding="utf-8")
    invitees = ",\n".join(
        f'  {{ id: "{g["param"]}", name: "{g["name"]}" }}' for g in guests
    )
    new_block = f"const INVITEES = [\n{invitees},\n];"
    gs2 = re.sub(r"const INVITEES = \[[\s\S]*?\];", new_block, gs, count=1)
    gs_path.write_text(gs2, encoding="utf-8")

assigned = sum(1 for g in guests if g["seat"] is not None)
print(
    f"Synced {len(guests)} guests "
    f"({assigned} with table, {len(guests) - assigned} without seat) "
    f"+ fixed numbers + letter-hex codes"
)
