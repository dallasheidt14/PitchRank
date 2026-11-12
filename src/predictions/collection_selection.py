"""One sampler for fixture intake, coverage previews and the pending forecast worker."""

import hashlib
from collections import defaultdict, deque


def select_fixture_candidates(candidates, limit, selection="balanced"):
    ordered = sorted(candidates, key=lambda item: (
        item[1]["game_date"], hashlib.sha256(item[1]["fixture_key"].encode()).hexdigest()))
    if selection == "chronological":
        return ordered[:limit]
    if selection != "balanced":
        raise ValueError("Unknown fixture selection policy")
    pools = defaultdict(lambda: defaultdict(deque))
    for item in ordered:
        row = item[1]
        payload = row.get("fixture_payload") or {}
        cohort = str(payload.get("cohort") or "unknown|unknown").split("|", 1)
        stratum = payload.get("collection_stratum") or {
            "age_group": cohort[0], "gender": cohort[-1], "rating_history_band": "unknown",
        }
        key = tuple(str(stratum.get(name) or "unknown") for name in ("age_group", "gender", "rating_history_band"))
        pools[row["provider_code"]][key].append(item)
    # Provider rotation precedes cohort rotation so many cohorts cannot crowd out a small provider.
    providers = deque((provider, deque(sorted(strata))) for provider, strata in sorted(pools.items()))
    selected = []
    while providers and len(selected) < limit:
        provider, strata = providers.popleft()
        stratum = strata.popleft()
        selected.append(pools[provider][stratum].popleft())
        if pools[provider][stratum]:
            strata.append(stratum)
        if strata:
            providers.append((provider, strata))
    return selected
