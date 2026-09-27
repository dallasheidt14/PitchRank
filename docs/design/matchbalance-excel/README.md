# MatchBalance director workbook design

[Download the Excel design sample](director-workbook-sample.xlsx).

This workbook is the editable companion to the tournament director's PDF.
It contains two illustrative cohort tabs, U10 Boys and U12 Girls. All names,
scores, ranks, and recommendations are sample data.

Each cohort presents the continuous published seed order, team names,
PitchRank scores, state ranks, strength markers, and placement status. Yellow
columns let the director enter the final division, pool, seed, and notes while
retaining the reference order. Tables support sorting and filtering, with
frozen headings and identifying columns. Teams awaiting placement remain
visible without a suggested seed.

The Streamlit export uses the same selected cohorts, team order, rating
snapshot, placement statuses, notes, and draft state as the PDF. Strength
markers describe competitive differences; they do not assign divisions or
pools. Pricing, matching diagnostics, and database identifiers stay out of the
director's workbook.

The workbook, both worksheet images, and the public PDF/PNG sample are built
from one frozen synthetic fixture. Regenerate them with
`python scripts/regenerate_matchbalance_samples.py`; its committed manifest
keeps renderer changes from leaving these examples stale.

## U10 Boys

![U10 Boys worksheet](u10-boys.png)

## U12 Girls

![U12 Girls worksheet](u12-girls.png)
