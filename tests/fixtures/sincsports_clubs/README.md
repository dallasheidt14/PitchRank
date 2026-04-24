# SincSports Clubs Search — Live Observations (2026-04-24)

Reconnaissance captured by driving the live page with Playwright + request replay,
per plan Step 3. Fixtures in this directory back the unit tests at
`tests/unit/test_sincsports_clubs.py` and the machine-readable sidecar at
`observations.json`.

## Fixtures

| File | Purpose |
|------|---------|
| `search_page_initial.html` | Raw GET of `sicclubs.aspx?sinc=Y`. Tests `_extract_form_state` against every `<input type="hidden">`. |
| `results_page_1.html` | URL-decoded callback payload for `state=NC, age=12 (U12), gender=M, cblType$0=on, all cblLevel checked`. 127 clubs, 116 teams. Tests row parsing. |
| `results_page_1_raw.xml` | Raw `<Data><Output><![CDATA[...]]></Output></Data>` envelope as received from the server. Tests envelope decoding. |
| `results_az_u12_boys.html` | URL-decoded callback payload for AZ U12 Boys. 74 clubs, 202 teams (multi-team clubs). Tests row parsing for clubs with multiple teams. |
| `results_ca_u14_boys.html` | URL-decoded payload for CA U14 Boys. 569 clubs, 702 teams in one response. Pagination stress test confirming single-response scope. |
| `results_empty.html` | URL-decoded payload for WY U04 Girls — confirmed real "no results" response. Authoritative reference for distinguishing empty vs block. |
| `results_empty_raw.xml` | Raw envelope for the empty case. |

## Human narrative

### State field type

Single `<select>` (no `multiple` attribute). 57 options: 50 US states + DC, plus
Puerto Rico, Canada, Mexico, Cost Rica, and XX-International (out of scope).
`state_field_mode: "single"` in `observations.json` → driver uses **Mode A**
(one POST per `(state, age, gender)` combo, 1,020 total for full grid).

HTML fragment:
```html
<select name="ctl00$ContentPlaceHolder1$ddlStates" id="ctl00_ContentPlaceHolder1_ddlStates">
  <option value="ZZ">All States</option>
  <option value="AL">Alabama</option>
  <option value="AK">Alaska</option>
  ...
</select>
```

### Submit mechanism

The "Search Teams" link (`<a id="searchbtn" onclick="return Search();">`) calls
a JS `Search()` function that invokes `eo_Callback("CBPTeams", "teams")`.
`eo_Callback` is an EssentialObjects (EO.Web) framework helper that populates
two synthetic form fields (`eo_cb_id` and `eo_cb_param`) and submits the form.

The key insight, captured from the real browser POST body: this is **not** a
standard ASP.NET `__doPostBack` — `__EVENTTARGET` and `__EVENTARGUMENT` stay
empty. Instead:

- `eo_cb_id = "ctl00_ContentPlaceHolder1_CBPTeams"` (note: underscores, the
  control's client ID — not the `$`-separated server name)
- `eo_cb_param = "teams"` (callback argument; `"club"` selects Search Clubs)
- `ctl00$ContentPlaceHolder1$ThisPageMasterFile = "/Sinc26.master"` is also
  required (observed in the browser POST but not present in the initial hidden
  fields — the scraper must append it)

Response is returned as a custom EO envelope:

```xml
<Data><Output><![CDATA[<percent-encoded-html>]]></Output></Data>
```

The inner HTML fragment must be `unquote()`-decoded before parsing. `requests`
gives the raw envelope as the response body; the scraper extracts the CDATA
payload with `re.search(r"<Output><!\[CDATA\[(.+?)\]\]></Output>", r.text, re.DOTALL)`
and URL-decodes with `urllib.parse.unquote`.

### Pagination mechanism

**None.** Single-response model. Even the heaviest observed query (CA U14 Boys —
569 clubs, 702 teams, 643 KB of HTML) is returned in one payload. No
`__doPostBack('...$lnkPageN', '')` anchors, no "Show More" button, no page-size
dropdown, no infinite-scroll hooks. Regex scan of the CA payload for
`__doPostBack`, `lnkPage`, `ShowMore`, `load more`, `pager`, and `PageIndex`
all returned zero matches.

Implication for the scraper: `_has_more_results` always returns `False` and
there is no `_fetch_next_results_batch` loop to run. Stale-viewstate detection
degenerates to the single-POST retry case.

### Form field names (from live devtools inspection)

| Purpose | `name` attribute |
|---------|------------------|
| State | `ctl00$ContentPlaceHolder1$ddlStates` (single-select `<select>`) |
| Age | `ctl00$ContentPlaceHolder1$ddlAge` (single-select `<select>`) |
| Gender | `ctl00$ContentPlaceHolder1$ddlGender` (single-select `<select>`; M/F/X) |
| Type = Club Team | `ctl00$ContentPlaceHolder1$cblType$0=on` (checkbox in CheckBoxList) |
| USA Rank tiers | `ctl00$ContentPlaceHolder1$cblLevel$0..6=on` (7 checkboxes) |
| Search Teams (pseudo-submit) | `eo_cb_id=ctl00_ContentPlaceHolder1_CBPTeams`, `eo_cb_param=teams` |

Age value map: the `<option value>` is the numeric age string — e.g. `"10"`
for U10, `"12"` for U12, `"19"` for U19, `"99"` for All Ages. The scraper
converts from its internal `"u10"`–`"u19"` keys via the `age_value_map` in
`observations.json`.

Gender value map: `Male → "M"`, `Female → "F"`. Storage on `TeamRecord.gender`
uses the canonical `"Male"`/`"Female"` forms (matches the matcher's expected
vocabulary at `sincsports_matcher.py:616`).

Rank checkboxes `cblLevel$0..6` correspond to:
0=Gold, 1=Silver, 2=Bronze, 3=Red, 4=Blue, 5=Green, 6=Non-Ranked.
All seven are submitted `=on` per the plan's explicit-checkbox rule.

### Response markers — populated vs empty vs block

- **Populated**: `<h3>Under {age} {Gender} from {State}</h3>` header, followed
  by `<div id="masonry" class='form-row row'>` with one or more `.cbox` divs
  as children. Each cbox contains a club (`<h3><a href="sicClub.aspx?id=X">`)
  and a `<div class="teamlist">` holding zero or more
  `<a href="team/team.aspx?id=X">TEAM_NAME</a>` anchors.

  **Team URL pattern note:** the discovery endpoint uses
  `team/team.aspx?id=NCM14762` — `id=`, not `teamid=`. The existing
  `src/scrapers/sincsports.py` scraper uses `team/games.aspx?teamid=...`
  (games endpoint) — a different URL on the same site. `provider_team_id`
  format is identical (e.g., `NCM14762`).

- **Empty**: Same `<h3>` header format (`"Under 4 Girls from Wyoming"` etc.),
  but `<div id="masonry">` is empty (no `.cbox` children). This is the
  authoritative empty-result fingerprint. Fixture: `results_empty.html`.

- **Block / captcha**: not observed during reconnaissance.
  `observations.json::response_markers.block` is `null`. Per the plan,
  `_validate_response_shape` falls back to "populated marker present OR empty
  marker present = valid response; otherwise suspect block." The populated/empty
  distinction above both satisfy: a valid response always has the
  `<h3>Under … from …</h3>` title fragment, so the scraper treats that as the
  canonical "valid shape" gate, routing anything else into
  `_consecutive_block_count`.

### `Retry-After` header

Not observed during reconnaissance (no throttling triggered). `_validate_response_shape`
honors the header if the server emits one, but this is an untested code path.

## Derived provider_team_id format

Anchor text inside the teamlist decodes to tokens like
`"Queen City Mutiny 2014 Pre-mls Next I"` — age/gender prefixes are SincSports'
standard pattern, already handled by `_normalize_team_name` in
`src/models/sincsports_matcher.py`. Provider team IDs observed so far match
`^[A-Z]{3}[A-Z0-9]+$` (e.g., `NCM14762`, `NCE47`, `SCM14140`, `CAM12903`,
`AZF14001`).

## Unknowns surfaced for Step 4 / Step 6

- **Block page fingerprint** is un-captured. The scraper's
  `_validate_response_shape` defaults to "title header present = valid" —
  after the first production run, tune this heuristic from observed failures
  rather than synthesizing a stub fixture now.
- **Retry-After behavior** is unverified; trust the header's presence only.
- **Rate-limit threshold** is unknown. The existing game scraper uses a
  `2.0–3.0s` delay without reported issues; reuse that for discovery.
