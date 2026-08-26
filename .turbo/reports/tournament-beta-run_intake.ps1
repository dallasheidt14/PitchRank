# Launch the tournament_intake Streamlit app for backtest scraping.
# Usage: ./run_intake.ps1   (then open the printed URL in a browser)

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
