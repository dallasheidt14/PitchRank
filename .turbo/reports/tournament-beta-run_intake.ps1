# ARCHIVED COPY -- does not run from where it sits.
#
# This is run_intake.ps1 from the C:/PitchRank_tournament_beta worktree, retired on
# 2026-08-26. Everything below this header block is unchanged; only this comment was
# added. Every path below is
# resolved from $PSScriptRoot, which was the repository root there and is
# .turbo/reports here. Run it in place and it changes directory to .turbo/reports,
# finds no .env.local, and fails on a missing tournament_intake.py.
#
# To use it: copy it to the repository root first, then run it from there.
#   cp .turbo/reports/tournament-beta-run_intake.ps1 ./run_intake.ps1
#
# It also expects the tournament_intake app and a shell/gotsport-tier-section-parser-02
# checkout; see tournament-beta-worktree-2026-08-26.md for how to rebuild that worktree.
#
# Launch the tournament_intake Streamlit app for backtest scraping.
# Original usage (from the repository root): ./run_intake.ps1

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# Load .env.local (KEY=VALUE per line; ignore blanks and # comments)
$envFile = Join-Path $PSScriptRoot ".env.local"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^\s*#') { return }
        if ($_ -match '^\s*$') { return }
        $kv = $_ -split '=', 2
        if ($kv.Length -eq 2) {
            $key = $kv[0].Trim()
            $val = $kv[1].Trim().Trim('"').Trim("'")
            [Environment]::SetEnvironmentVariable($key, $val, "Process")
        }
    }
    # Bridge: scrapers read SUPABASE_KEY but .env.local stores SUPABASE_SERVICE_ROLE_KEY
    if (-not $env:SUPABASE_KEY -and $env:SUPABASE_SERVICE_ROLE_KEY) {
        $env:SUPABASE_KEY = $env:SUPABASE_SERVICE_ROLE_KEY
    }
}

python -m streamlit run tournament_intake.py
