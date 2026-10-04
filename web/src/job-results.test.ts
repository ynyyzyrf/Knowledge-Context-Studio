import { describe, expect, it } from "vitest";
import { jobIsRunning, jobSummary } from "./job-results";
import type { Job } from "./types";

describe("job results", () => {
  it("continues polling after extraction while indexing", () => {
    const job = {
      state: "succeeded",
      result: { pipeline_state: "indexing" },
    } as Job;
    expect(jobIsRunning(job)).toBe(true);
    expect(
      jobIsRunning({
        ...job,
        result: { ...job.result!, pipeline_state: "ready" },
      }),
    ).toBe(false);
  });
  it("distinguishes zero memories from processing", () => {
    expect(
      jobSummary({
        state: "succeeded",
        result: { reason: "no_durable_facts" },
      } as Job),
    ).toBe("沒有可存的長期記憶");
    expect(jobSummary({ state: "pending" } as Job)).toBe("等待處理");
  });
});
