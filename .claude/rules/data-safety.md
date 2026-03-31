# Data & Pandas Safety

## pandas fillna(None) will crash
`fillna(None)` raises TypeError in modern pandas. Use `where(col.notna(), None)` or conditional assignment instead. Also: columns initialized with `None` stay as `object` dtype even after filling with numeric values — set the dtype explicitly.

## Batch sizing
Don't over-correct batch sizes after a single timeout or failure. Balance reliability with runtime. Dropping from 1000 to 100 rows per batch turns a 5-minute job into a 50-minute one. Investigate the actual failure before shrinking batches.
