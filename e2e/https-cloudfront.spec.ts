import { randomBytes } from "node:crypto";

import { expect, test } from "@playwright/test";

/**
 * QA checks for HTTPS through CloudFront (#220, ADR 0012). Runs only when the base URL is https
 * (a deployed environment: `E2E_BASE_URL=https://<id>.cloudfront.net npx playwright test
 * https-cloudfront`); skipped against the local http stack. Playwright validates the certificate
 * (no ignoreHTTPSErrors), so every request here is also a "no -k" check. Uses a throwaway `.test`
 * account that is deleted at the end; nothing here prints the address, password or cookie value.
 * The browser sign-in over https is the `@smoke` journey (smoke.spec.ts) run against the same URL.
 */
const base = (process.env.E2E_BASE_URL || process.env.BASE_URL || "").replace(/\/+$/, "");
test.skip(!base.startsWith("https://"), "needs an https base URL (a CloudFront environment)");

test("http redirects to https; /api is never served from cache; index.html is not cached", async ({ request }) => {
  const http = await request.get(base.replace(/^https:/, "http:") + "/", { maxRedirects: 0 });
  expect([301, 302]).toContain(http.status());
  expect(http.headers()["location"]).toMatch(/^https:\/\//);

  for (let i = 0; i < 3; i++) {
    const r = await request.get("/api/v1/healthz");
    expect(r.status()).toBe(200);
    expect(r.headers()["x-cache"] ?? "").not.toMatch(/hit/i);
    console.log(`healthz #${i + 1}: x-cache=${r.headers()["x-cache"]} version=${(await r.json()).version}`);
  }
  for (let i = 0; i < 2; i++) {
    const r = await request.get("/");
    expect(r.status()).toBe(200);
    expect(r.headers()["x-cache"] ?? "").not.toMatch(/hit/i);
    console.log(`index #${i + 1}: x-cache=${r.headers()["x-cache"]} cache-control=${r.headers()["cache-control"]}`);
  }
});

test("sign-up and sign-in over https: Secure; HttpOnly; SameSite=Lax cookie, authenticated request works", async ({
  playwright,
}) => {
  const api = await playwright.request.newContext({ baseURL: base });
  const run = `${Date.now()}-${randomBytes(3).toString("hex")}`;
  const email = `qa220+${run}@example.test`;
  const password = `qa-${randomBytes(12).toString("hex")}`;
  let created = false;
  try {
    const signup = await api.post("/api/v1/auth/signup", {
      data: {
        email,
        password,
        display_name: `QA HTTPS ${run.slice(-6)}`,
        role: "athlete",
        birth_date: "1990-01-01",
        units: "metric",
        timezone: "Pacific/Auckland",
        accept_disclaimer: true,
      },
    });
    expect(signup.status()).toBe(201);
    created = true;
    const attrs = (signup.headers()["set-cookie"] ?? "").split(";").slice(1).map((a) => a.trim()).join("; ");
    console.log(`signup Set-Cookie attributes: ${attrs}`);
    expect(attrs).toMatch(/\bSecure\b/i);
    expect(attrs).toMatch(/\bHttpOnly\b/i);
    expect(attrs).toMatch(/SameSite=Lax/i);
    expect((await api.get("/api/v1/me")).status()).toBe(200);

    expect((await api.post("/api/v1/auth/logout")).status()).toBeLessThan(300);
    expect((await api.get("/api/v1/me")).status()).toBe(401);

    const login = await api.post("/api/v1/auth/login", { data: { email, password } });
    expect(login.status()).toBe(200);
    expect(login.headers()["set-cookie"] ?? "").toMatch(/;\s*Secure/i);
    const me = await api.get("/api/v1/me");
    console.log(`GET /api/v1/me after sign-in: ${me.status()} x-cache=${me.headers()["x-cache"]}`);
    expect(me.status()).toBe(200);
  } finally {
    if (created) {
      const del = await api.post("/api/v1/me/delete", { data: { password } });
      console.log(`account deleted: ${del.status()}`);
      expect(del.status()).toBe(204);
    }
    await api.dispose();
  }
});
