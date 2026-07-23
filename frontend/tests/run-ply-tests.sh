#!/usr/bin/env bash
# Standalone test runner for lib/ply-parser.ts (v2.1 T1.4).
# We compile with tsc → node --input-type=module, avoiding a heavy vitest/jest
# setup for a single pure-function module.

set -euo pipefail
export PATH="$HOME/.nvm/versions/node/v20.20.1/bin:$PATH"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="/tmp/plytest-$$"
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
    "$ROOT/lib/ply-parser.ts",
    "$ROOT/lib/splat-parser.ts",
    "$ROOT/tests/ply-parser.test.ts",
    "$ROOT/tests/splat-parser.test.ts"
  ]
}
EOF

cd "$ROOT"
node_modules/.bin/tsc -p "$OUT/tsc.json" 2>&1 | grep -v 'node:assert\|Cannot find name .process' || true

# ESM needs explicit .js extension
sed -i "s|'../lib/ply-parser'|'../lib/ply-parser.js'|g" "$OUT/out/tests/ply-parser.test.js"
sed -i "s|'../lib/splat-parser'|'../lib/splat-parser.js'|g" "$OUT/out/tests/splat-parser.test.js"
echo '{"type":"module"}' > "$OUT/out/package.json"

cd "$OUT/out"
node tests/ply-parser.test.js
node tests/splat-parser.test.js
