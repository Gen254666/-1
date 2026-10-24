import { execSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const configDir = path.dirname(fileURLToPath(import.meta.url));

export default function globalSetup(): void {
  const backendDir = path.resolve(configDir, "../../backend");
  execSync("uv run python ../scripts/e2e_seed.py", {
    cwd: backendDir,
    stdio: "inherit",
  });
}
