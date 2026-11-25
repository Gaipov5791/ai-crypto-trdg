import { execSync } from "node:child_process";

const port = process.argv[2] ?? "5173";
const re = new RegExp(`:${port}\\s`);

function listeningPids() {
  const out = execSync("netstat -ano", { encoding: "utf8" });
  const pids = new Set();
  for (const line of out.split(/\r?\n/)) {
    if (!re.test(line) || !line.includes("LISTENING")) continue;
    const pid = line.trim().split(/\s+/).pop();
    if (pid && /^\d+$/.test(pid) && pid !== "0") pids.add(pid);
  }
  return [...pids];
}

for (const pid of listeningPids()) {
  try {
    execSync(`taskkill /F /PID ${pid}`, { stdio: "ignore" });
    console.log(`Freed port ${port} (PID ${pid})`);
  } catch {
    // process already gone
  }
}
