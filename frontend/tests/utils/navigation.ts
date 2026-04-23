import { expect, Locator, Page } from "@playwright/test";
import logger from "./logger";
import { completeOnboarding } from "./onboarding";

/**
 * Login page locators - optimized for the actual login form structure
 */
const LOGIN_LOCATORS = {
  usernameField: (page: Page) => page.locator("#username"),
  passwordField: (page: Page) => page.locator("#password"),
  submitButton: (page: Page) =>
    page.getByRole("button", { name: /continue|log in|login|sign in/i }),
};

/**
 * Get the base URL from environment or config
 */
export function getBaseUrl(): string {
  return process.env.BASE_URL || "http://localhost:3000";
}

/**
 * Build a full URL by properly joining base URL and path
 */
function buildUrl(path: string): string {
  const baseUrl = getBaseUrl().replace(/\/$/, "");
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${baseUrl}${normalizedPath}`;
}

/**
 * Get login credentials from environment
 */
function getLoginCredentials(): { email: string; password: string } {
  const email = process.env.TEST_USER_EMAIL;
  const password = process.env.TEST_USER_PASSWORD;

  if (!email || !password) {
    throw new Error(
      "TEST_USER_EMAIL and TEST_USER_PASSWORD environment variables must be set",
    );
  }
  return {
    email,
    password,
  };
}

/**
 * Handle login if login page is detected
 */
async function handleLogin(page: Page): Promise<void> {
  try {
    // Check if login page is present (with short timeout)
    const submitButton = LOGIN_LOCATORS.submitButton(page);
    await submitButton.waitFor({ state: "visible", timeout: 3000 });
    logger.info("Login page detected - attempting login...");
    const credentials = getLoginCredentials();
    // Fill in username field
    const usernameField = LOGIN_LOCATORS.usernameField(page);
    await usernameField.fill(credentials.email);
    // Fill in password field
    const passwordField = LOGIN_LOCATORS.passwordField(page);
    await passwordField.fill(credentials.password);
    // Click submit button
    await submitButton.click();
    // Wait for navigation after login
    await page.waitForLoadState("networkidle");
    logger.info("Login successful");
  } catch (error) {
    // Login page not detected or already logged in
    logger.info("No login page detected - proceeding...");
  }
}

/**
 * Core navigation handler with login support
 */
export async function navigateToApp(
  page: Page,
  path: string = "/",
): Promise<void> {
  const fullUrl = buildUrl(path);
  await page.goto(fullUrl);
  await handleLogin(page);
  await completeOnboarding(page);
  // After onboarding, the app redirects to /chat, redirect to another path if needed
  if (!page.url().includes(path)) {
    logger.info(`Navigating to intended path: ${path}`);
    await page.goto(fullUrl);
    await page.waitForLoadState("networkidle");
  }
}

/**
 * Navigate to Chat page and verify textbox
 */
export async function navigateToChat(page: Page): Promise<void> {
  await navigateToApp(page, "/chat");
  await expect(
    page.getByRole("textbox", { name: "Ask a question..." }),
  ).toBeVisible({ timeout: 60000 });
}

/**
 * Navigate to Knowledge page and verify heading
 */
export async function navigateToKnowledge(page: Page): Promise<void> {
  await navigateToApp(page, "/knowledge");
  await expect(page.getByText("Project Knowledge")).toBeVisible({
    timeout: 60000,
  });
}

/**
 * Navigate to Settings page and verify heading
 */
export async function navigateToSettings(page: Page): Promise<void> {
  await navigateToApp(page, "/settings");
  await expect(page.getByText("Model Providers")).toBeVisible({
    timeout: 60000,
  });
}

/**
 * Navigate to Home (optional: treat as chat)
 */
export async function navigateToHome(page: Page): Promise<void> {
  await navigateToChat(page);
}
