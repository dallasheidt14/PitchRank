#!/bin/bash
# Test all Mission Control API endpoints
# Run with: bash scripts/test-mission-control-api.sh

BASE_URL="http://localhost:3000"

echo "🧪 Testing Mission Control API Endpoints"
echo "========================================"
echo ""

# Test 1: Agent Activity
echo "1️⃣  Testing /api/agent-activity"
curl -s "$BASE_URL/api/agent-activity" | jq -r '.count, .error' | head -2
echo ""

# Test 2: Tasks List
echo "2️⃣  Testing /api/tasks (GET)"
curl -s "$BASE_URL/api/tasks" | jq -r '.tasks | length'
echo ""

# Test 3: Seed Tasks Preview
echo "3️⃣  Testing /api/tasks/seed (GET - Preview)"
curl -s "$BASE_URL/api/tasks/seed" | jq -r '.count'
echo ""

# Test 4: Announcements
echo "4️⃣  Testing /api/announcements"
curl -s "$BASE_URL/api/announcements" | jq -r '.announcements | length'
echo ""

# Test 5: Chat
echo "5️⃣  Testing /api/chat"
curl -s "$BASE_URL/api/chat" | jq -r '.messages | length'
echo ""

# Test 6: Agent Webhook Health
echo "6️⃣  Testing /api/agent-webhook (Health Check)"
curl -s "$BASE_URL/api/agent-webhook" | jq -r '.status, .endpoint'
echo ""

echo "✅ Test complete!"
echo ""
echo "To seed initial tasks, run:"
echo "  curl -X POST $BASE_URL/api/tasks/seed"
