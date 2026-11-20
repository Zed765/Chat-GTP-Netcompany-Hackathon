// Fails the production build if any part of the mock API ended up in it.
// Usage: node scripts/assert-no-mock.mjs <build directory>
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

// Strings that exist only in src/mocks: its entry point, a fixture, and its token format.
const MARKERS = ["installMockApi", "The mock API has no route", "mock-session.", "chatterbox-ai.example"];

const directory = process.argv[2] ?? "dist";
const files = readdirSync(directory, { recursive: true, withFileTypes: true })
  .filter((entry) => entry.isFile())
  .map((entry) => join(entry.parentPath, entry.name));

const leaks = files.flatMap((file) => {
  const content = readFileSync(file, "utf8");
  return MARKERS.filter((marker) => content.includes(marker)).map((marker) => `${file}: contains "${marker}"`);
});

if (leaks.length > 0) {
  console.error(`The build in ${directory}/ contains mock API code:\n  ${leaks.join("\n  ")}`);
  console.error("Build without VITE_MOCK_API and without --mode mock.");
  process.exit(1);
}
console.log(`${directory}/: ${files.length} files, no mock API code.`);
