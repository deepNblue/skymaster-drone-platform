#!/usr/bin/env bash
# Standalone test runner for lib/copilot_tool_policy.ts (v2.1 F4.4).
set -euo pipefail
export PATH="$HOME/.nvm/versions/node/v20.20.1/bin:$PATH"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="/tmp/toolpolicytest-$$"
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
    "$ROOT/lib/copilot_tool_policy.ts",
    "$ROOT/tests/copilot_tool_policy.test.ts"
  ]
}
EOF

cd "$ROOT"
node_modules/.bin/tsc -p "$OUT/tsc.json" 2>&1 \
  | grep -v 'node:assert\|Cannot find name .process\|node:test' \
  || true

sed -i "s|'../lib/copilot_tool_policy'|'../lib/copilot_tool_policy.js'|g" \
  "$OUT/out/tests/copilot_tool_policy.test.js"
echo '{"type":"module"}' > "$OUT/out/package.json"

cd "$OUT/out"
node --test tests/copilot_tool_policy.test.js
