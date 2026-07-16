#!/usr/bin/env node
/**
 * Copy Cesium static assets (Workers/Assets/Widgets/ThirdParty) into public/cesium
 * so the browser can load them at runtime via CESIUM_BASE_URL.
 */
const fs = require('fs');
const path = require('path');

const cesiumPkg = require.resolve('cesium/package.json');
const cesiumBuild = path.join(path.dirname(cesiumPkg), 'Build', 'Cesium');
const targetDir = path.join(__dirname, '..', 'public', 'cesium');

if (!fs.existsSync(cesiumBuild)) {
  console.error(`[copy-cesium] Cesium Build dir not found at ${cesiumBuild}`);
  process.exit(0);
}

function copyRecursive(src, dst) {
  const stat = fs.statSync(src);
  if (stat.isDirectory()) {
    fs.mkdirSync(dst, { recursive: true });
    for (const entry of fs.readdirSync(src)) {
      copyRecursive(path.join(src, entry), path.join(dst, entry));
    }
  } else {
    fs.copyFileSync(src, dst);
  }
}

const dirs = ['Workers', 'Assets', 'Widgets', 'ThirdParty'];
for (const d of dirs) {
  const src = path.join(cesiumBuild, d);
  const dst = path.join(targetDir, d);
  if (!fs.existsSync(src)) {
    console.warn(`[copy-cesium] skip missing ${d}`);
    continue;
  }
  fs.rmSync(dst, { recursive: true, force: true });
  copyRecursive(src, dst);
  console.log(`[copy-cesium] copied ${d}`);
}
console.log(`[copy-cesium] done → ${targetDir}`);
