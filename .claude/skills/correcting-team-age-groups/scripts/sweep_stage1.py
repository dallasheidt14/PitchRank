"""Stage 1 (read-only): features + tier-1 and GotSport-agrees plans for every non-CA team the review flagged."""
import csv, importlib.util, sys, collections, pickle, re
sys.path.insert(0, r'C:\PitchRank')
SK = r'C:\PitchRank\.claude\skills\correcting-team-age-groups\scripts\review_age_labels.py'
spec = importlib.util.spec_from_file_location('ral', SK)
ral = importlib.util.module_from_spec(spec); spec.loader.exec_module(ral)
from supabase import create_client
from config.settings import SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
c = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
R = ral.Reader()
OUT = r'C:\PitchRank\data\exports'
REVIEW = OUT + r'\age_label_review_allbutCA.csv'
SINCE = '2026-08-01'
rows = list(csv.DictReader(open(REVIEW, encoding='utf-8')))
SKIP = {'prior_fix_stands', 'held_opponents_far_from_name'}


def cohort_set(name):
    b = R.band(name)
    if b:
        return {b}, 'band'
    ul, yrs = R.labels(name)
    if len(ul) == 1:
        return set(ul), 'label'
    if not ul and len(yrs) == 1:
        y = next(iter(yrs)); fits = ral.YEAR_FITS.get(y)
        if fits:
            return set(fits), 'year'
    return set(), ''


def cands(r):
    return [g for g in r['key_age'].split('/') if g]


work = [r for r in rows if r['cat'] not in SKIP]
ids = [r['team_id'] for r in work]
games = collections.defaultdict(list)
for i in range(0, len(ids), 40):
    b = ids[i:i + 40]
    for col in ('home_team_master_id', 'away_team_master_id'):
        q = c.table('games').select('game_date,home_team_master_id,away_team_master_id,division_name')\
            .in_(col, b).gte('game_date', SINCE)
        off = 0
        while True:
            page = q.range(off, off + 999).execute().data
            for x in page:
                t = x[col]
                o = x['away_team_master_id'] if col == 'home_team_master_id' else x['home_team_master_id']
                games[t].append((o, x['division_name'] or ''))
            if len(page) < 1000:
                break
            off += 1000
    if (i // 40) % 25 == 0:
        print('games', i, '/', len(ids), flush=True)
opp_ids = sorted({o for g in games.values() for o, _ in g if o})
names = {}
for i in range(0, len(opp_ids), 100):
    for o in c.table('teams').select('team_id_master,team_name').in_('team_id_master', opp_ids[i:i + 100]).execute().data:
        names[o['team_id_master']] = o['team_name']
print('opp names', len(names), flush=True)

PF = ral.PLAN_FIELDS
# a name carrying a past-season marker may state last season's label
STALE = re.compile(r'(spring|fall|summer|winter)\s*20\d\d|\b2[0-9]\s*/\s*2[0-9]\b|\b20(2[0-5])\b', re.I)
tier = {'band': 'A_own_name_band', 'ulabel': 'U_own_name_ulabel_opponent_confirmed', 'year': 'Y_single_year'}


def prow(r, P, why, evid=None):
    return {'state_code': r['state'], 'team_id_master': r['team_id'], 'team_name': r['name'], 'club_name': r['club'],
            'gender': r['gender'], 'gotsport_team_name': r['gotsport_name'], 'band': r['key_age'] if r['kind'] == 'band' else '',
            'old_age_group': r['stored'], 'new_age_group': P, 'action': 'would_update', 'collision_with': '',
            'evidence_tier': evid or tier[r['kind']], 'fixture_verdict': why, 'opp_games_proposed': '', 'opp_games_current': ''}


plan1, plan_gs, rest, hold_H, hold_other = [], [], [], [], []
for r in rows:
    if r['cat'] in SKIP:
        hold_other.append((r, r['cat'])); continue
    S = r['stored']; g = games.get(r['team_id'], [])
    best = None; feats = {}
    for P in cands(r):
        if P == S:
            continue
        cnt = collections.Counter(); sup_opps = set()
        for o, div in g:
            cs, kind = cohort_set(names.get(o, ''))
            if not cs:
                continue
            k = 'ind' if kind in ('band', 'year') else 'lab'
            if S in cs and P in cs: cnt[k + '_N'] += 1
            elif P in cs: cnt[k + '_P'] += 1; sup_opps.add(o)
            elif S in cs: cnt[k + '_S'] += 1
            else: cnt[k + '_O'] += 1
        dv = collections.Counter()
        for o, div in g:
            if div:
                cs, _ = cohort_set(div)
                for x in cs: dv[x] += 1
        sup = cnt['ind_P'] + cnt['lab_P']; con = cnt['ind_S'] + cnt['lab_S']; oth = cnt['ind_O'] + cnt['lab_O']
        div_contra = dv.get(S, 0) > 0 and dv.get(P, 0) == 0
        ok = sup >= 4 and len(sup_opps) >= 3 and con == 0 and oth <= 1 and not div_contra and cnt['ind_P'] >= 1
        score = sup - con
        if best is None or score > best['score']:
            best = dict(P=P, sup=sup, con=con, ok=ok, ind=cnt['ind_P'], lab_P=cnt['lab_P'], lab_S=cnt['lab_S'], ind_S=cnt['ind_S'], score=score)
        elif ok and not best['ok']:
            best = dict(P=P, sup=sup, con=con, ok=ok, ind=cnt['ind_P'], lab_P=cnt['lab_P'], lab_S=cnt['lab_S'], ind_S=cnt['ind_S'], score=score)
    if not g:
        hold_H.append((r, 'no_games_since_aug1')); continue
    if r['cat'] == 'held_duplicate_landing':
        rest.append((r, best)); continue
    if r['group'] in ('1', '2', '3') and r['proposed']:
        plan1.append(prow(r, r['proposed'], f"review_group_{r['group']}")); continue
    if r['group'] == '4' and r['proposed'] and (r['proposed'] in (r['band_opps_say'], r['div_says']) or (best and best['ok'] and best['P'] == r['proposed'])):
        plan1.append(prow(r, r['proposed'], 'review_group_4 corroborated')); continue
    if best and best['ok']:
        plan1.append(prow(r, best['P'], f"opponents sup={best['sup']} con={best['con']} ind={best['ind']}")); continue
    rest.append((r, best))

# GotSport-agrees stage (existing reconcile record)
rest2 = []
for r, best in rest:
    if r['cat'] == 'held_duplicate_landing':
        rest2.append((r, best, 'move would duplicate an existing team')); continue
    if not best:
        rest2.append((r, best, 'no candidate')); continue
    G = r['gotsport_age']; P = best['P']; S = r['stored']
    backS = best['lab_S'] + best['ind_S'] > 0 and best['lab_S'] + best['ind_S'] >= best['sup']
    play_up = r['cat'] == 'ulabel_plays_up'
    if G and G == P and (not backS or play_up) and not STALE.search(r['name']):
        plan_gs.append(prow(r, P, 'name+gotsport agree', 'U_own_name_ulabel_gotsport_agrees'))
    else:
        rest2.append((r, best, ''))

for nm, pl in (('t1', plan1), ('gs', plan_gs)):
    with open(OUT + rf'\fix_band_cohorts_plan_all_{nm}.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=PF); w.writeheader(); w.writerows(pl)
pickle.dump({'rest': rest2, 'hold_H': hold_H, 'hold_other': hold_other}, open(OUT + r'\_all_rest.pkl', 'wb'))
print('plan t1', len(plan1), 'plan gs', len(plan_gs), 'rest', len(rest2), 'H', len(hold_H), 'other', len(hold_other))
