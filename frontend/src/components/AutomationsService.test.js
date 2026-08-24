import api from "./AutomationsService";

function jsonResponse(data, ok = true) {
  return {
    ok,
    status: ok ? 200 : 400,
    statusText: ok ? "OK" : "Bad Request",
    headers: { get: () => "application/json" },
    json: async () => data,
    text: async () => JSON.stringify(data),
  };
}

describe("AutomationsService live tests", () => {
  beforeEach(() => {
    global.fetch = jest.fn().mockResolvedValue(jsonResponse({ ok: true, did: [] }));
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  test("uses the real live endpoint and sends an explicit confirmation", async () => {
    await api.runLiveTest(
      "owner@example.com",
      { id: "flow-1", steps: [] },
      { email: "customer@example.com" }
    );

    expect(global.fetch).toHaveBeenCalledTimes(1);
    const [url, options] = global.fetch.mock.calls[0];
    expect(url).toContain("/api/automations/test-live");
    const body = JSON.parse(options.body);
    expect(body.confirm_live).toBe(true);
    expect(body.lead_email).toBe("customer@example.com");
  });
});
