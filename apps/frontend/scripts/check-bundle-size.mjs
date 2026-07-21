import { readdir, stat } from "node:fs/promises";

const maxKiB = Number(process.env.BUNDLE_MAX_KIB ?? 500);
const maxBytes = maxKiB * 1024;
const assetsDir = new URL("../dist/assets/", import.meta.url);

function formatKiB(bytes) {
  return `${(bytes / 1024).toFixed(1)} KiB`;
}

let entries;
try {
  entries = await readdir(assetsDir);
} catch (error) {
  console.error(
    `Bundle size check failed: ${assetsDir.pathname} is missing. Run npm run build first.`,
  );
  process.exitCode = 1;
  throw error;
}

const jsAssets = entries.filter((entry) => entry.endsWith(".js"));
const oversized = [];
let largest = null;

for (const asset of jsAssets) {
  const file = new URL(asset, assetsDir);
  const size = (await stat(file)).size;
  if (!largest || size > largest.size) {
    largest = { asset, size };
  }
  if (size > maxBytes) {
    oversized.push({ asset, size });
  }
}

if (jsAssets.length === 0) {
  console.error("Bundle size check failed: no JavaScript assets were emitted.");
  process.exit(1);
}

if (oversized.length > 0) {
  console.error(`Bundle size check failed: max JS chunk size is ${maxKiB} KiB.`);
  for (const { asset, size } of oversized) {
    console.error(`- ${asset}: ${formatKiB(size)}`);
  }
  process.exit(1);
}

console.log(
  `Bundle size check passed: ${jsAssets.length} JS chunks, largest ${largest.asset} at ${formatKiB(
    largest.size,
  )}.`,
);
