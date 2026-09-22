# Club-name cleanup: the calls left for the owner

Every US state now has a deliberate pass. What follows is everything the passes refused
to decide, grouped by the kind of decision rather than by state, because most of these
answer in bulk — the first group alone settles eleven items in one sentence.

Each is commented in place beside its own state in `CLUB_CANONICAL_OVERRIDES`;
`grep -n "open question" scripts/full_club_analysis.py` lists all 24 blocks.

---

## 1. Rows whose club field names no club — one policy answers eleven

These values are provider dropdown entries or programme labels, not clubs. Each pools
teams from unrelated clubs under one name, which is the shape
`src/utils/placeholder_clubs.py` exists for, and the reason none of them can ever become
a rule.

| value | teams | what its teams actually are |
|---|---|---|
| `U.S. Futsal` + `U.S. Futsal Club` | 66 (CA) | Sole Sisters, Galacticos, NLA Select, Rangers Fut Academy |
| `Tournament Team` + `Tournament Team - PA` | 48 (PA) | Berks Rebellion, Cutter FC, Hellbender FC, Forza, KOSA — 42 different clubs |
| `AYSO` + `AYSO Alliance` | 18 (CA) | Imperial Valley SA, SC Chicks, Huntington Beach Breakers |
| `Real` | 6 (CA) | Inland Empire, Sporting, Deportivo Arizona, Greens STXCL |
| `Test Club` | (OK) | actual test data |
| `No Club Selection` | 1,594 national | already known; never a rule |

**The question:** add the first four to `PLACEHOLDER_CLUB_NAMES`, so every repair path
that looks for a *missing* club stops walking past them?

Related and already decided the other way, for the record: Arkansas', Oklahoma's,
Arizona's and Illinois' `No Club Selection` rows stay untouched.

---

## 2. Splitting a parent into branches it already has — two instances, same shape

Neither is a name fold. Both are per-team moves with their own undo log, and **nothing
in the weekly cleanup would maintain either**, so a later import can undo them.

### New Jersey — Players Development Academy (104 teams)

151 teams sit on the parent. Their own names put:

| destination | teams moving | already holds |
|---|---|---|
| PDA White (Shore) | 44 | 42 |
| PDA Blue (North) | 32 | 35 |
| PDA Hibernian | 25 | 18 |
| PDA South | 3 | 59 |
| *stays on the parent* | 47 | — |

The rule reads the place or partner word **before** any colour word, which is what keeps
`Hibernian Adams White U12` under Hibernian and `PDA South Blue ECNL RL 2009` under
South. A proposal file is built and applies nothing.

### California — Total Futbol Academy (308 rows)

The same shape, larger. Twelve branch values already exist (`TFA-SGV` 18, `TFA-IE` 15,
`TFA-VC` 13, `TFA-SELA` 10, `tfa-pro` 10, `TFA-AV` 9, `tfa-glendale` 8, and five more
at 2–4 each), and the 308-row parent holds teams from all of them — its own team names
read TFA-SELA, TFA-AV, TFA-Pro, TFA-Central LA.

**The question, for both:** split, or leave the parent as one club and accept that the
branch values are a partial record?

---

## 3. A club whose teams all name a different club that already exists

This is the shape the crosscheck finds and that you have approved before — Oak Hills
Youth Athletics → Oak Hills Premier, Dreamers FC → Lincoln Surf, Saginaw Township SA →
Detroit City FC North. Each of these is the same argument, unapplied because the
evidence stops short of the ones already taken.

| club value | teams | what its teams read | share |
|---|---|---|---|
| South Lakes SC (OK) | 110 | "Oklahoma Cosmos …" | all |
| Greater Libertyville SA (IL) | 80 | "FC 1974 Libertyville" | 52 of 80 |
| Milpitas YSL (CA) | 47 | "FC Milpitas …" | 31 of 47 |
| Wilmette Wings SC (IL) | 38 | "Chicago Rush North Shore" | 25 of 38 |
| Shelby County Youth Soccer (OH) | — | "Western Ohio United" | all |
| Dearborn SC (MI) | — | "Michigan Juniors FC Dearborn" | all |
| Northwest Cincy Soccer Coalition (OH) | 14 | "Northwest Cincy SC" | 13 of 14 |
| Club Independent (AL) | — | "Hampton Cove SC" | all |
| Brooklyn Force SC (NY) | 10 | "Metropolitan Oval Academy Brooklyn" | 7 of 10 |
| Sturgis SC (MI) | — | "Midwest United FC - Sturgis" | 7 |

---

## 4. Two clubs, or one club spelled two ways

No decisive team-name evidence either way. Each needs local knowledge.

- **WSA (NJ, 80 teams)** — should it read **Westfield SA**? Every team reads "Westfield
  SA …" or "Union County FC …", and neither brand is in the club value. This is the
  Maryland SAC/Baltimore Armour shape: two brands, one partnership.
- **City SC (CA, 256, Carlsbad)** against **CITY FC (CA, 11)**.
- **West Sacramento Soccer Club (36)** against **West Sacramento Futbol Club (20)** —
  both field a team called Heat; neither names the other.
- **Lincoln Youth Soccer Club (CA, 8)** against **Lincoln FC (31)** — the club's own
  retired tag read `Lincoln FC (lincoln Ysc/lysc)`, but LYSC's rows are rec sides
  (Lady Hawks, Defenders, Blue Angels).
- **Glen Rock Shooting Stars (NJ, 21)** against **Glen Rock United (9)** — three
  Shooting Stars rows read "Glen Rock United", and every Glen Rock United row is an
  "- Elite" side. One club with a tier, or two?
- **FC Allstars (NJ, 6)** against **Allstars F.C (4)** — the same name in two word
  orders; neither names the other.
- **Long Island City Soccer Club (9)** against **Long Island CIty Youth Soccer Academy
  (8)** — both write LIC; no crossing team name.
- **CNY Coliseum Soccer Club (5)** against **Coliseum (26)** — both field 2009G, 2010G
  and 2011G sides, and each names itself.
- **Abington Soccer Club (PA)** against **AC United** — one Abington row reads "AC
  United 2012b Madness" and the mascots overlap.
- **SoCal Athletic Soccer Club (44)**, **Socal Academy (2)**, **SOCAL (1)**.
- **APEX FC** against **Stillwater SC (OK)** — Stillwater fields "APEX FC U14 Boys
  Orange".
- **Illinois FC / Illinois Alliance** — each holds the other's teams.
- Smaller pairs listed in place: Hastings FC/SC (NE), Chaos Soccer/Chaos FC (MI),
  Legacy FC/SC (IL), Ohio Valley SL/FC (OH), Vermillion SC/Youth SL (SD),
  Tahlequah SL/SC (OK), Dorchester United (SC), Calhoun FC/FC Calhoun (GA),
  Southern States (GA), Old Dominion / Manassas United / Herndon (VA, three pairs).

---

## 5. A rebrand spanning several club values — California's Athletic SC

All nine `Athletic SC - Bay Area` rows read "AYSO United Bay Area"; the Santa Clarita
and South Bay rows read "United Socal". `Athletic Soccer Club` holds 171 teams and
`United Socal` 305.

Folding the branches would move teams into two large values on the strength of their
team names. **The question:** is Athletic SC now AYSO United and United SoCal, or are
these separate clubs whose teams were mislabelled?

---

## 6. Which state, not which name

These rows hold a club from another state, so they ask a state question and belong to
the `assigning-team-states` skill rather than here.

- `Union Soccer Club (NJ)` on one Pennsylvania team.
- `Augusta Arsenal SC (ga)` on South Carolina teams; `Augusta Arsenal Soccer Club (SC)`
  on Georgia teams.
- `FC Stars` in New York, whose teams read "FC Stars Acton" and "FC Stars Lancaster" —
  Massachusetts sides.
- `Athletic SC Arizona` and `New England Surf` in California.
- `Chisholm Trail SA (CTSA)` (OK) and `SAYSA` (WI), each holding Loudoun VA sides.
- `Wichita Regional Soccer Association` (NE), a Kansas name on Grand Island teams.
- `Watertown Youth Soccer Assn` (WI), holding one South Dakota team.

---

## 7. Junk and single-team rows

Each is one or two teams with a club value that names nothing.

`Arizona (000)`, `Utah (000)`, `Washington (000)`, `SAN JOSE` (CA), `California` (CA),
`Franklin` (NJ), `Peninsula City SC` (NJ), `Nesa` (NJ — **not** Nutley Elite SA, which
the scan pairs it with on the acronym; two of its teams read "CSA Newark"), the one
`Cedar Stars` row (NY), `Esko Soccer Club` (MN), `Bridgewater FC` (MA),
`Highline SC` (WA), `Prodigy Warriors` (AR), `Pearl FC` (MS), `Schuyler Predators` (NE),
`Arundel FC` and `Maryland Independent M.U.S.C.` (MD), `Grand Junction Fire FC` (CO),
the bare `Rush` row (CO), `Metro Tulsa SC United` (OK), `NORTHWOOD SC Pumas` (IN),
`Forza` and `Nationals SC Union` (MI), `WSSC …` and `PacFW-R …` (WA),
`Harvard FC`, `Allegiant FC` and `Young SPORTSMENS SL (YSSL)` (IL),
`Alabama FC` North/South/Huntsville and the five bare `AFC …` rows (AL),
`Vero FC` (AL, 95 teams naming three different clubs),
`Phoenix Football Club` (MD/AL), `Hudson SA/Western WI Soccer/FC` (WI),
the four Legacy values (WI), `FC Milwaukee Torrent Wales Soccer` (WI),
`Georgia Storm Madison` and `Georgia Storm Lake Country United FC` (GA),
`Northern Indiana FC`, `Northern Indiana Express` and `NIFC Academy` (IN),
`SOUTHWEST KANSAS` (KS), `Northern Nevada Youth Soccer League` (NV),
`Plymouth` (WI), `Orlando City Youth Soccer` and the two St. John's rows (FL),
the wider Miami group (FL), Texas' 32 annotated groups.

---

## 8. Two things outside this job

- **The caps pass re-cases a provider placeholder.** California has one team under
  `no club`, and the weekly cleanup queues `'no club' -> 'NO Club'`. Same shape as the
  Del Rio-laughlin and Club DE Futbol damage, on a value `is_placeholder_club` already
  recognises. Cosmetic today — the lowered form still matches — but
  `merge_case_variants` should skip a placeholder outright.
- **Five Long Island clubs write their league tag in lower case** — Garden City,
  Floral Park, Greater Long Beach, Farmingdale SC and Manorville — where thirty-odd
  others write `(LIJSL)`. Where a club had two spellings anyway the canonical took the
  league's case; these have only one spelling each, so nothing forced the question.
  About 200 teams. Sweep, or leave?
