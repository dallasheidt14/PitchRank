"""Provider team ids that mean "the provider did not identify this team".

``str(obj.get("team_id", ""))`` turns a present JSON ``null`` into the truthy string ``"None"``,
so test ids with ``is_blank_provider_id``, never truthiness. An approved alias keyed on a
placeholder attaches every game carrying it to one team, and every opponent of those games is
then rated against a phantom.

``frontend/lib/validation.ts`` holds a copy of this set; change both.
"""

from __future__ import annotations

BLANK_PROVIDER_IDS = frozenset({"", "none", "null"})


def is_blank_provider_id(value: object) -> bool:
    return value is None or str(value).strip().lower() in BLANK_PROVIDER_IDS


def clean_provider_id(value: object) -> str:
    if is_blank_provider_id(value):
        return ""
    return str(value).strip()
