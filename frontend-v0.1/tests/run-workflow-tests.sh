#!/usr/bin/env bash
# Standalone test runner for lib/copilot_workflows.ts (v2.1 T10.6).
# Uses the same tsc → node --input-type=module pattern as run-ply-tests.sh.

set -euo pipefail
export PATH="$HOME/.nvm/versions/node/v20.20.1/bin:$PATH"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="/tmp/wftest-$$"
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
    "outDir": "$OUT/out",
    "lib": ["ES2020", "DOM"]
  },
  "files": [
    "$ROOT/lib/copilot_workflows.ts",
    "$ROOT/tests/copilot_workflows.test.ts"
  ]
}
EOF

cd "$ROOT"
node_modules/.bin/tsc -p "$OUT/tsc.json" 2>&1 \
    | grep -v 'node:assert\|Cannot find name .process\|Cannot find name .global' \
    || true

# ESM needs explicit .js extension
sed -i "s|'../lib/copilot_workflows'|'../lib/copilot_workflows.js'|g" \
    "$OUT/out/tests/copilot_workflows.test.js"
echo '{"type":"module"}' > "$OUT/out/package.json"

cd "$OUT/out"
node tests/copilot_workflows.test.js
