import { defineConfig, devices } from "@playwright/test";

// Frontend publicado y API publicada (por defecto: despliegue docker local).
const BASE_URL = process.env.BASE_URL ?? "http://127.0.0.1:7440";
const API_BASE = process.env.API_BASE ?? "http://127.0.0.1:7441";

export default defineConfig({
  testDir: "./tests",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [
    ["list"],
    ["html", { open: "never", outputFolder: "playwright-report" }],
  ],
  use: {
    baseURL: BASE_URL,
    headless: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});

export const URLS = { BASE_URL, API_BASE };
