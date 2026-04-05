#!/usr/bin/env bash
# index.sh — Build compact cache index files from retrieved metadata
#
# Produces cache/ files that let Claude answer structural questions
# (what fields exist, what a flow writes, what Apex reads) without
# reading 430MB of raw XML — typically a 20-50x token reduction.
#
# Usage:
#   bash scripts/index.sh        # run from project root
#   (called automatically by retrieve.sh after Phase 1)

set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

if [ ! -f "metadata/.retrieved_at" ]; then
  echo "ERROR: metadata not retrieved yet. Run: bash scripts/retrieve.sh"
  exit 1
fi

echo ""
echo "Building metadata index..."
python3 scripts/index.py
echo ""
echo "✅ Index complete. Cache files are in ./cache/"
