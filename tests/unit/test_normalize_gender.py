import numpy as np
import pandas as pd

from src.rankings.shared import normalize_gender


def test_normalize_gender_maps_labels():
    series = pd.Series(["Boys", "girl", " MALE ", "Female"])

    assert normalize_gender(series).tolist() == ["male", "female", "male", "female"]


def test_normalize_gender_keeps_nulls_null():
    series = pd.Series(["Boys", None, np.nan, "Girls"])

    result = normalize_gender(series)

    assert result.isna().tolist() == [False, True, True, False]
    # Nulls must not be stringified into phantom "nan"/"none" cohorts
    assert set(result.dropna()) == {"male", "female"}
