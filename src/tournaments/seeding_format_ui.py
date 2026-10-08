"""Optional format settings for the internal seeding operator."""

import json

import streamlit as st

from src.tournaments.seeding_format_library import DEFAULT_LIBRARY_PATH
from src.tournaments.seeding_format_preferences import PREFERENCE_DEFAULTS, effective_preferences, validate_preferences


def render_format_preferences(pack, save, invalidate, *, cohort=None):
    prefix = f"_format_{cohort or 'event'}"
    saved = (
        {**PREFERENCE_DEFAULTS, **effective_preferences(pack, cohort)}
        if cohort
        else {**PREFERENCE_DEFAULTS, **pack.get("format_preferences", {})}
    )
    title = "Age-group format preferences (optional)" if cohort else "Tournament preferences (optional)"
    with st.expander(title, expanded=False):
        st.caption(
            "Automatic recommendations need no settings. "
            "MatchBalance uses this cohort's team count and strength evidence."
        )
        with st.form(prefix):
            inherit = (
                st.checkbox("Use tournament preferences", value=cohort not in pack.get("cohort_format_preferences", {}))
                if cohort
                else False
            )
            require_minimum = st.checkbox("Apply minimum game requirement", value=saved["minimum_games"] is not None)
            minimum = st.number_input(
                "Minimum guaranteed games", min_value=1, value=saved["minimum_games"] or 3, step=1
            )
            limit_maximum = st.checkbox("Apply maximum game limit", value=saved["maximum_games"] is not None)
            maximum = st.number_input("Maximum games per team", min_value=1, value=saved["maximum_games"] or 5, step=1)
            st.caption("Only checked game requirements apply. Uncheck a requirement to remove its limit.")
            repeat_labels = {"allowed": "Allowed", "prohibited": "Prohibited"}
            repeat = st.selectbox(
                "Repeat opponents",
                list(repeat_labels),
                index=list(repeat_labels).index(saved["repeat_opponents"]),
                format_func=repeat_labels.get,
            )
            playoff_labels = {"any": "No preference", "required": "Required", "excluded": "Excluded"}
            playoffs = st.selectbox(
                "Playoffs",
                list(playoff_labels),
                index=list(playoff_labels).index(saved["playoffs"]),
                format_func=playoff_labels.get,
            )
            submitted = st.form_submit_button("Save format preferences")
        if submitted:
            values = validate_preferences(
                {
                    "minimum_games": minimum if require_minimum else None,
                    "maximum_games": maximum if limit_maximum else None,
                    "repeat_opponents": repeat,
                    "playoffs": playoffs,
                }
            )
            if cohort:
                overrides = pack.setdefault("cohort_format_preferences", {})
                if inherit:
                    overrides.pop(cohort, None)
                else:
                    overrides[cohort] = values
            else:
                pack["format_preferences"] = values
            st.session_state["_seeding_pack"] = pack
            invalidate()
            st.session_state["_seeding_pack_unsaved"] = not save()
            st.rerun()
        if not cohort and pack.get("format_library", {}).get("schema_version", 1) < 2:
            st.caption(
                "This saved analysis keeps its original formats. "
                "Updating formats keeps its saved ratings and predictions."
            )
            if st.button("Use expanded formats for this saved analysis", key=f"{prefix}_update"):
                pack["format_library"] = json.loads(DEFAULT_LIBRARY_PATH.read_text(encoding="utf-8"))
                pack.pop("format_profile_id", None)
                st.session_state["_seeding_pack"] = pack
                invalidate()
                st.session_state["_seeding_pack_unsaved"] = not save()
                st.rerun()
