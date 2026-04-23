import { expect, Locator, Page } from "@playwright/test";
import logger from "../utils/logger";

export class TasksMenu {
  readonly drawer: Locator;

  constructor(private page: Page) {
    // The drawer typically contains the Tasks header and task lists
    this.drawer = this.page
      .locator("div")
      .filter({ has: this.page.getByText("Recent Tasks") })
      .first();
  }

  /**
   * Opens the Tasks menu by clicking the bell icon in the header (right side)
   */
  async open() {
    // First, check if it's already open
    const isVisible = await this.page
      .getByText("Recent Tasks")
      .first()
      .isVisible()
      .catch(() => false);
    if (isVisible) {
      return;
    }

    // Primary approach: Find the bell icon button in the header (right side)
    // The bell icon is typically a lucide-bell SVG icon
    const bellButton = this.page
      .locator("header button:has(svg.lucide-bell)")
      .or(this.page.locator("button:has(svg.lucide-bell)"))
      .first();

    try {
      await bellButton.click({ timeout: 5000 });
    } catch {
      // Fallback 1: Try by accessible name
      try {
        const tasksButton = this.page.getByRole("button", {
          name: /Tasks|Notifications/i,
        });
        await tasksButton.click({ timeout: 3000 });
      } catch {
        // Fallback 2: Find bell icon by SVG class anywhere
        await this.page.locator("svg.lucide-bell").locator("..").click();
      }
    }

    await expect(this.page.getByText("Recent Tasks").first()).toBeVisible({
      timeout: 10000,
    });
  }

  /**
   * Closes the Tasks menu
   */
  async close() {
    // Try clicking the close button on the drawer (usually an 'X')
    const closeBtn = this.page
      .getByRole("button", { name: /close/i })
      .or(this.page.locator("button").filter({ hasText: "×" }))
      .or(this.page.locator("svg.lucide-x").locator(".."))
      .first();

    await closeBtn.click();
    await expect(this.page.getByText("Recent Tasks").first()).toBeHidden({
      timeout: 5000,
    });
  }
}

// Made with Bob
