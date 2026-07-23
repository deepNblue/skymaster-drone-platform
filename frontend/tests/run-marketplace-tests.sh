#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.nvm/versions/node/v20.20.1/bin:$PATH"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="/tmp/mkttest-$$"
trap "rm -rf $OUT" EXIT

mkdir -p "$OUT"
cat > "$OUT/tsc.json" <<EOF
{
  "compilerOptions": {
    "target": "ES2020",
    "module": "ESNext",
    "moduleResolution": "node",
    "esModuleInterop": true,
    "strict": true,
    "skipLibCheck": true,
    "outDir": "$OUT/out"
  },
  "files": [
    "$ROOT/lib/copilot_workflow_marketplace.ts",
    "$ROOT/tests/copilot_workflow_marketplace.test.ts"
  ]
}
EOF

cd "$ROOT"
node_modules/.bin/tsc -p "$OUT/tsc.json" 2>&1 || true

sed -i "s|'../lib/copilot_workflow_marketplace'|'../lib/copilot_workflow_marketplace.js'|g" \
  "$OUT/out/tests/copilot_workflow_marketplace.test.js"
echo '{"type":"module"}' > "$OUT/out/package.json"

cd "$OUT/out"
node --test tests/copilot_workflow_marketplace.test.js
