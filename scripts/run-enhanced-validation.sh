#!/bin/bash
#
# Wrapper script to run enhanced prediction validation
#
# Usage:
#   ./scripts/run-enhanced-validation.sh
#
# Or with explicit credentials:
#   NEXT_PUBLIC_SUPABASE_URL="..." NEXT_PUBLIC_SUPABASE_ANON_KEY="..." ./scripts/run-enhanced-validation.sh
#

set -e

# Check if .env.backup exists and source it if credentials not already set
if [ -z "$NEXT_PUBLIC_SUPABASE_URL" ] && [ -f .env.backup ]; then
    echo "Loading credentials from .env.backup..."
    # Read and export Supabase vars from .env.backup
    export NEXT_PUBLIC_SUPABASE_URL=$(grep SUPABASE_URL .env.backup | cut -d'=' -f2- | tr -d '"' | tr -d "'" | tr -d '\r')
    export NEXT_PUBLIC_SUPABASE_ANON_KEY=$(grep SUPABASE_KEY .env.backup | cut -d'=' -f2- | tr -d '"' | tr -d "'" | tr -d '\r')
fi

# Check if credentials are set
if [ -z "$NEXT_PUBLIC_SUPABASE_URL" ] || [ -z "$NEXT_PUBLIC_SUPABASE_ANON_KEY" ]; then
    echo "❌ Error: Supabase credentials not found"
    echo ""
    echo "Please set environment variables:"
    echo "  export NEXT_PUBLIC_SUPABASE_URL=\"your_url\""
    echo "  export NEXT_PUBLIC_SUPABASE_ANON_KEY=\"your_key\""
    echo ""
    echo "Or create .env.backup file with SUPABASE_URL and SUPABASE_KEY"
    exit 1
fi

echo "✅ Credentials loaded"
echo ""

# Copy script to frontend and run
cp scripts/validate-predictions-enhanced.js frontend/
cd frontend
node validate-predictions-enhanced.js
