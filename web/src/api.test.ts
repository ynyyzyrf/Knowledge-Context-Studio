import { describe, it, expect, vi, afterEach } from "vitest";
import { request, detailText, ApiError } from "./api";
afterEach(() => vi.unstubAllGlobals());
describe("API boundary", () => {
  it("keeps agent auth separate from browser cookies", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetch);
    await request("/v1/agent/me", "GET", undefined, { token: "test-only" });
    expect(fetch.mock.calls[0][1].credentials).toBe("omit");
    expect(fetch.mock.calls[0][1].headers.Authorization).toBe(
      "Bearer test-only",
    );
  });
  it("keeps conflict meaningful rather than treating it as empty data", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "版本已變更" }), {
          status: 409,
        }),
      ),
    );
    await expect(
      request("/v1/x", "PATCH", { expected_version: 1 }),
    ).rejects.toMatchObject({ status: 409, message: "版本已變更" });
  });
  it("formats validation fields", () =>
    expect(detailText([{ loc: ["body", "name"], msg: "Required" }])).toBe(
      "name：Required",
    ));
  it("reports network failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError()));
    await expect(request("/v1/x")).rejects.toBeInstanceOf(ApiError);
  });
});
