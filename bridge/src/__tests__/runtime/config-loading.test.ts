import { describe, expect, it } from "vitest";
import { loadConfig } from "../../runtime/config.js";

const environment = { WRZDJ_BRIDGE_API_KEY: "key", WRZDJ_EVENT_CODE: "ONE" };

describe("loadConfig", () => {
  // Regression: 57cfcdc6867f captured one environment snapshot at import time.
  it("loads independent configurations from the supplied environment", () => {
    const first = loadConfig(environment);
    const second = loadConfig({ ...environment, WRZDJ_EVENT_CODE: "TWO" });
    expect(first.eventCode).toBe("ONE");
    expect(second.eventCode).toBe("TWO");
    expect(first.apiUrl).toBe("http://localhost:8000");
    expect(environment).toEqual({ WRZDJ_BRIDGE_API_KEY: "key", WRZDJ_EVENT_CODE: "ONE" });
  });

  it.each(["5seconds", "Infinity", "-1", "NaN"])("rejects invalid timing %s", (value) => {
    expect(() => loadConfig({ ...environment, MIN_PLAY_SECONDS: value })).toThrow("MIN_PLAY_SECONDS");
  });

  it.each(["WRZDJ_BRIDGE_API_KEY", "WRZDJ_EVENT_CODE"])("requires %s", (key) => {
    expect(() => loadConfig({ ...environment, [key]: "" })).toThrow(key);
  });
});
