#!/usr/bin/env python3
import argparse, csv, re
from pathlib import Path

# ---- tune these as you see patterns ----
TIER_WORDS = ["ECNL", "ECNL-RL", "ECNLRL", "GA", "GIRLS ACADEMY", "MLS NEXT", "MLSNEXT", "DPL", "NPL", "E64", "USYS", "EDP"]

def clean(s: str) -> str:
    s = s.strip()
    s = re.sub(r"\s+", " ", s)
    return s

def slugify(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s

def normalize_club(raw: str):
    up = clean(raw).upper()

    # remove common tier words from club name (we track tier separately later if you want)
    for w in TIER_WORDS:
        up = re.sub(rf"\b{re.escape(w)}\b", " ", up)

    # strip common team tokens that shouldn't define club identity
    up = re.sub(r"\b(BOYS|GIRLS)\b", " ", up)
    up = re.sub(r"\bU[0-9]{1,2}\b", " ", up)              # U15 etc
    up = re.sub(r"\b20(0[5-9]|1[0-9]|2[0-6])\b", " ", up)  # 2005-2026
    up = re.sub(r"\b([BG])\s*([0-9]{2})\b|\b([0-9]{2})\s*([BG])\b", " ", up)  # B12/12B

    # punctuation cleanup
    up = re.sub(r"[(){}\[\],/\\\-]+", " ", up)
    up = clean(up)

    # confidence heuristic (tighten later)
    confidence = 85 if up else 40
    action = "keep" if confidence >= 85 else "needs-review"
    notes = ""

    return up, slugify(up), confidence, action, notes

def guess_club_field(fieldnames):
    # common possibilities
    candidates = ["club_name", "club", "clubName", "Club", "ClubName", "team_name", "team", "name"]
    for c in candidates:
        if c in fieldnames:
            return c
    return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--club-col", default="")
    args = ap.parse_args()

    inp = Path(args.input)
    outp = Path(args.output)
    outp.parent.mkdir(parents=True, exist_ok=True)

    with inp.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        club_col = args.club_col or guess_club_field(reader.fieldnames or [])
        if not club_col:
            raise SystemExit(f"Could not find club column. Columns: {reader.fieldnames}")
        rows = list(reader)

    # write normalized view
    fieldnames = list(rows[0].keys())
    extra = ["club_col_used", "club_raw", "club_normalized", "club_id", "club_confidence", "club_action", "club_notes"]
    out_fields = fieldnames + extra

    with outp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=out_fields)
        w.writeheader()
        for r in rows:
            raw = r.get(club_col, "") or ""
            norm, club_id, conf, action, notes = normalize_club(raw)
            r2 = dict(r)
            r2.update({
                "club_col_used": club_col,
                "club_raw": raw,
                "club_normalized": norm,
                "club_id": club_id,
                "club_confidence": conf,
                "club_action": action,
                "club_notes": notes,
            })
            w.writerow(r2)

    print(f"Wrote {len(rows)} rows -> {outp}")

if __name__ == "__main__":
    main()
