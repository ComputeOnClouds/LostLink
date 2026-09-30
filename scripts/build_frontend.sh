#!/usr/bin/env bash
# Install deps and build the React app to frontend/dist.
set -euo pipefail
cd "$(dirname "$0")/../frontend"
if [ ! -d node_modules ]; then
  npm install
fi
npm run build
echo "Built frontend/dist:"
ls -la dist
