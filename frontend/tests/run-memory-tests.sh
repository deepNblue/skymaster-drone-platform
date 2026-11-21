#!/usr/bin/env bash
# Standalone runner for E2.3 copilot memory tests.
set -euo pipefail
export PATH="$HOME/.nvm/versions/node/v20.20.1/bin:$PATH"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="/tmp/memtest-$$"
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
    "$ROOT/lib/copilot_memory.ts",
    "$ROOT/tests/copilot_memory.test.ts"
  ]
}
EOF

cd "$ROOT"
node_modules/.bin/tsc -p "$OUT/tsc.json" 2>&1 \
  | grep -v 'node:assert\|Cannot find name .process\|node:test' \
  || true

sed -i "s|'../lib/copilot_memory'|'../lib/copilot_memory.js'|g" \
  "$OUT/out/tests/copilot_memory.test.js"
echo '{"type":"module"}' > "$OUT/out/package.json"

cd "$OUT/out"
node --test tests/copilot_memory.test.js
