#!/bin/bash
set -e

# 🏙️ Local CI Verification Script
# This script mirrors the .github/workflows/build.yml logic.

echo "--- 🛠️  Installing/Syncing Dependencies ---"
uv sync --all-extras --dev

echo "--- 🧪 Running Pytest (including Capture Validation) ---"
uv run pytest -v -m "not e2e"

echo "--- 🚀 Verifying CLI Launch ---"
uv run python scripts/verify_launch.py

echo "--- 📦 Building Package ---"
uv build

echo "--- ✅ All Local Checks Passed! ---"
