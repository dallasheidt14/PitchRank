import sys, pickle, csv, time, os
sys.path.insert(0, r'C:\PitchRank')
from supabase import create_client
from config.settings import SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
from src.utils.gotsport_team_details import TeamDetailsResolver
c = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
d = pickle.load(open(r'C:\PitchRank\data\exports\_all_rest.pkl', 'rb'))
ids = [r['team_id'] for r, b, why in d['rest'] if not why.startswith('move would')]
OUTP = r'C:\PitchRank\data\exports\all_gotsport_fresh.csv'
done = set()
if os.path.exists(OUTP):
    done = {x['team_id'] for x in csv.DictReader(open(OUTP, encoding='utf-8')) if x['status'] != 'empty_or_blocked'}
meta = {}
for i in range(0, len(ids), 100):
    for m in c.table('teams').select('team_id_master,provider_id,provider_team_id').in_('team_id_master', ids[i:i+100]).execute().data:
        meta[m['team_id_master']] = m
GS = 'e6102baf-6095-4fc8-805a-ed0d71cbee1e'
res = TeamDetailsResolver()
new = not os.path.exists(OUTP)
out = open(OUTP, 'a', newline='', encoding='utf-8'); w = csv.writer(out)
if new: w.writerow(['team_id', 'gs_id', 'status', 'gs_name', 'gs_age_group', 'gs_raw_age', 'gs_gender'])
fails = 0
for n, t in enumerate(ids):
    if t in done: continue
    m = meta.get(t, {})
    if m.get('provider_id') != GS or not m.get('provider_team_id'):
        w.writerow([t, '', 'no_gotsport_id', '', '', '', '']); continue
    r = res.resolve(m['provider_team_id'])
    if r:
        fails = 0; w.writerow([t, m['provider_team_id'], 'ok', r['name'], r['age_group'], r['raw_age_group'], r['gender']])
    else:
        fails += 1; w.writerow([t, m['provider_team_id'], 'empty_or_blocked', '', '', '', ''])
        if fails >= 10: print('ABORT at', n, flush=True); sys.exit(2)
    out.flush(); time.sleep(3)
print('done', len(ids), flush=True)
