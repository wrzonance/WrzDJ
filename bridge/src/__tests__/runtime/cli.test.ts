import { execFile, spawn } from "node:child_process";
import { createServer } from "node:http";
import { promisify } from "node:util";
import { describe, expect, it } from "vitest";

const run = promisify(execFile);

describe("bridge CLI", () => {
  // Regression: 57cfcdc6867f advertised only stagelinq for unknown plugins.
  it("lists every supported plugin when the configured plugin is unknown", async () => {
    await expect(run(process.execPath, ["--import", "tsx", "src/index.ts"], {
      timeout: 10_000,
      env: {
        ...process.env,
        WRZDJ_API_URL: "http://localhost:8000",
        WRZDJ_BRIDGE_API_KEY: "test-key",
        WRZDJ_EVENT_CODE: "TEST123",
        WRZDJ_PLUGIN: "unknown-plugin",
      },
    })).rejects.toMatchObject({
      code: 1,
      stderr: expect.stringContaining("Available plugins: pioneer-prolink, serato, stagelinq, traktor-broadcast"),
    });
  });

  it("starts a controlled plugin and shuts down on SIGTERM with handlers removed", async () => {
    const server = createServer((_request, response) => {
      response.writeHead(200, { "content-type": "application/json" });
      response.end(JSON.stringify({ commands: [] }));
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    const address = server.address();
    if (!address || typeof address === "string") throw new Error("Test server did not bind a TCP port");

    const child = spawn(process.execPath, ["--import", "tsx", "src/__tests__/fixtures/cli-signal-process.ts"], {
      cwd: process.cwd(),
      env: {
        ...process.env,
        WRZDJ_API_URL: `http://127.0.0.1:${address.port}`,
        WRZDJ_BRIDGE_API_KEY: "test-key",
        WRZDJ_EVENT_CODE: "CLI-TEST",
      },
      stdio: ["ignore", "pipe", "pipe"],
    });

    let output = "";
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk: string) => { output += chunk; });
    child.stderr.on("data", (chunk: string) => { output += chunk; });

    try {
      await new Promise<void>((resolve, reject) => {
        const timeout = setTimeout(() => reject(new Error(`CLI did not start: ${output}`)), 10_000);
        const onOutput = () => {
          if (!output.includes("READY")) return;
          clearTimeout(timeout);
          child.stdout.off("data", onOutput);
          child.stderr.off("data", onOutput);
          resolve();
        };
        child.stdout.on("data", onOutput);
        child.stderr.on("data", onOutput);
        child.once("error", reject);
      });

      child.kill("SIGTERM");
      const exitCode = await new Promise<number | null>((resolve) => child.once("close", resolve));
      expect(exitCode).toBe(0);
      expect(output).toContain("PLUGIN_STOPPED");
      expect(output).toContain("SIGTERM_HANDLERS=0");
    } finally {
      if (child.exitCode === null) child.kill("SIGKILL");
      server.closeAllConnections();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  }, 20_000);
});
