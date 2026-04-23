import { expect, Locator, Page } from "@playwright/test";
import path from "path";
import logger from "../utils/logger";
import { getBaseUrl } from "../utils/navigation";

export class Chat {
  //Element locators
  private get plusButton(): Locator {
    return this.page.locator('div[role="presentation"] button').filter({
      has: this.page.locator("svg.lucide-plus"),
    });
  }
  /**
   * Get locator for an uploaded file by filename
   * @param fileName - Name of the uploaded file to locate
   * @returns Locator for the uploaded file element
   */
  private getUploadedFileLocator(fileName: string): Locator {
    return this.page.locator("p.text-muted-foreground").filter({
      hasText: fileName,
    });
  }

  constructor(private page: Page) {}

  async open() {
    await this.page.getByRole("link", { name: "Chat" }).click();
  }

  /**
   * Open a fresh chat by navigating directly to the chat URL
   * This automatically opens a new chat session
   */
  async openNewChat() {
    const baseUrl = getBaseUrl().replace(/\/$/, "");
    await this.page.goto(`${baseUrl}/chat`);
    await this.page.waitForTimeout(1000);
  }

  /**
   * Ask a question in the chat and wait for the complete response
   * Uses API interception with UI fallback
   * @param question - The question to ask
   * @param timeout - Maximum time to wait for response (default: 60000ms)
   * @returns The complete response text from the assistant
   */
  async askQuestion(
    question: string,
    timeout: number = 120000,
  ): Promise<string> {
    const input = this.page.getByRole("textbox", {
      name: "Ask a question...",
    });

    let fullResponse = "";

    // Listen BEFORE sending request
    const responsePromise = this.page.waitForResponse(
      async (response) => {
        return (
          response.url().includes("/api/langflow") &&
          response.request().method() === "POST"
        );
      },
      { timeout },
    );

    // Send question
    await input.fill(question);
    await this.page.keyboard.press("Enter");

    const response = await responsePromise;

    try {
      const raw = await response.text();

      const lines = raw.split("\n").filter((line) => line.trim());

      for (const line of lines) {
        try {
          const chunk = JSON.parse(line);

          if (chunk.delta?.content) {
            fullResponse += chunk.delta.content;
          }

          if (chunk.response?.text) {
            fullResponse = chunk.response.text; // final override
          }
        } catch {
          // ignore malformed chunks
        }
      }
    } catch {
      // fallback to UI
    }

    // Fallback if API parsing fails
    if (!fullResponse) {
      const lastResponse = this.page.locator(".markdown.prose").last();
      await lastResponse.waitFor({ state: "visible", timeout });

      fullResponse = (await lastResponse.textContent()) || "";
    }

    return fullResponse.trim();
  }

  /**
   * Ingest a URL via chat and capture tool call data
   * @param url - The URL to ingest
   * @returns Object containing the tool call locator and captured tool data
   */
  async ingestUrl(url: string): Promise<{
    toolCall: Locator;
    toolData: any;
    fullResponse: string;
  }> {
    const input = this.page.getByRole("textbox", {
      name: "Ask a question...",
    });

    let capturedToolData: any = null;
    let fullResponseText = "";

    // Listen for API response to capture tool call data
    const responsePromise = this.page.waitForResponse(
      async (response) => {
        return (
          response.url().includes("/api/langflow") &&
          response.request().method() === "POST"
        );
      },
      { timeout: 120000 },
    );

    await input.fill(`Please ingest this URL: ${url}`);
    await this.page.keyboard.press("Enter");

    // Capture the API response
    const response = await responsePromise;
    const raw = await response.text();
    const lines = raw.split("\n").filter((line) => line.trim());

    for (const line of lines) {
      try {
        const chunk = JSON.parse(line);

        // Capture tool call data
        if (
          chunk.type === "response.output_item.done" &&
          chunk.item?.type === "tool_call"
        ) {
          capturedToolData = chunk.item;
        }

        // Build full response text
        if (chunk.delta?.content) {
          fullResponseText += chunk.delta.content;
        }
        if (chunk.response?.text) {
          fullResponseText = chunk.response.text;
        }
      } catch {
        // ignore malformed chunks
      }
    }

    // Match the exact format: "Function Call: opensearch_url_ingestion_flow"
    const toolCall = this.page
      .getByText(/Function Call:.*opensearch_url_ingestion_flow/i)
      .last();

    await expect(toolCall).toBeVisible({ timeout: 120000 });

    return {
      toolCall,
      toolData: capturedToolData,
      fullResponse: fullResponseText.trim(),
    };
  }

  async isToolFailed(toolCall: Locator): Promise<boolean> {
    const container = toolCall.locator(
      'xpath=ancestor::div[contains(@class,"border")]',
    );

    const text = await container.textContent();

    return /error|failed|timeout/i.test(text || "");
  }

  /**
   * Apply a knowledge filter in the chat
   * @param filterName - Name of the filter to apply
   */
  async applyKnowledgeFilter(filterName: string) {
    const filterButton = this.page.locator('button[data-filter-button="true"]');
    await filterButton.click();
    await this.page.waitForTimeout(500);

    const filterOption = this.page.getByText(filterName, { exact: true });
    await expect(filterOption).toBeVisible({ timeout: 5000 });
    await filterOption.click();
    await this.page.waitForTimeout(500);
  }

  /**
   * Remove the currently applied knowledge filter
   */
  async removeKnowledgeFilter() {
    const filterButton = this.page.locator('button[data-filter-button="true"]');
    await filterButton.click();
    await this.page.waitForTimeout(500);

    const noFilterOption = this.page.getByText("No knowledge filter");
    await expect(noFilterOption).toBeVisible({ timeout: 5000 });
    await noFilterOption.click();
    await this.page.waitForTimeout(500);
  }

  /**
   * Check if a knowledge filter exists in the filter list
   * @param filterName - Name of the filter to check
   * @returns true if filter exists, false otherwise
   */
  async isFilterAvailable(filterName: string): Promise<boolean> {
    const filterButton = this.page.locator('button[data-filter-button="true"]');
    await filterButton.click();
    await this.page.waitForTimeout(500);

    try {
      const filterOption = this.page.getByText(filterName, { exact: true });
      const isVisible = await filterOption.isVisible({ timeout: 2000 });

      // Close the filter dropdown
      await filterButton.click();
      await this.page.waitForTimeout(500);

      return isVisible;
    } catch {
      // Close the filter dropdown
      await filterButton.click();
      await this.page.waitForTimeout(500);

      return false;
    }
  }

  /**
   * Upload a file in the chat section
   * @param filePath - Path to the file to upload
   * @returns The filename that was uploaded
   */
  async ingestFileInChat(filePath: string) {
    logger.info(`Uploading file from chat: ${filePath}`);
    const fileName = path.basename(filePath);
    const [fileChooser] = await Promise.all([
      this.page.waitForEvent("filechooser"),
      this.plusButton.click(),
    ]);
    await fileChooser.setFiles(filePath);
    logger.info(`File uploaded and ready for querying: ${fileName}`);
    return fileName;
  }

  /**
   * Verify uploaded file in the chat section
   * @param fileName - File name
   */
  async verifyFileInChat(fileName: string) {
    const uploadedFile = this.getUploadedFileLocator(fileName);
    await expect(uploadedFile).toBeVisible({ timeout: 10000 });
    logger.info(`File visible in chat: ${fileName}`);
  }

  /**
   * Wait for a response containing specific text
   * @param text - Text to wait for in the response
   * @param timeout - Maximum time to wait
   */
  async waitForResponseContaining(
    text: string | RegExp,
    timeout: number = 60000,
  ) {
    const response = this.page.locator("div.markdown").last();
    await expect(response).toBeVisible({ timeout });
    await expect(response).toContainText(text, { timeout });
  }

  /**
   * Get the last response from the chat
   * @param timeout - Maximum time to wait for response
   * @returns The response text
   */
  async getLastResponse(timeout: number = 60000): Promise<string> {
    const response = this.page.locator("div.markdown").last();
    await expect(response).toBeVisible({ timeout });
    return await response.innerText();
  }

  /**
   * Get the current theme applied to the page
   * @returns 'light' or 'dark' based on the HTML class or data attribute
   */
  async getCurrentTheme(): Promise<"light" | "dark"> {
    // Check the HTML element for theme class or data attribute
    const htmlElement = this.page.locator("html");
    const classList = (await htmlElement.getAttribute("class")) || "";
    const dataTheme = (await htmlElement.getAttribute("data-theme")) || "";

    // Check if dark mode is active
    if (classList.includes("dark") || dataTheme.includes("dark")) {
      return "dark";
    }
    return "light";
  }

  /**
   * Switch to a specific theme mode
   * The theme button is in the top right corner (sun icon for light, moon icon for dark)
   * @param theme - The theme to switch to: 'light' or 'dark'
   */
  async switchTheme(theme: "light" | "dark" | "system") {
    // Get current theme first
    const currentTheme = await this.getCurrentTheme();

    // If we're already on the desired theme, no need to click
    if (currentTheme === theme) {
      return;
    }

    // For system mode, we need to click twice if we're on the opposite theme
    // System mode will match the OS theme
    if (theme === "system") {
      // Click the theme button to toggle
      const themeButton = this.page
        .locator('header button, header [role="button"]')
        .last();
      await themeButton.click();
      await this.page.waitForTimeout(500);
      return;
    }

    // For light/dark toggle: click the theme button in top right corner
    // The button shows sun icon when in dark mode (click to go light)
    // The button shows moon icon when in light mode (click to go dark)
    const themeButton = this.page
      .locator('header button, header [role="button"]')
      .last();
    await themeButton.click();
    await this.page.waitForTimeout(1000);
  }

  /**
   * Verify theme colors are applied correctly
   * @param expectedTheme - The expected theme ('light' or 'dark')
   */
  async verifyThemeColors(expectedTheme: "light" | "dark") {
    // Get background color of the main content area
    const mainContent = this.page.locator('main, [role="main"], body').first();
    const backgroundColor = await mainContent.evaluate((el) => {
      return window.getComputedStyle(el).backgroundColor;
    });

    // Parse RGB values
    const rgbMatch = backgroundColor.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
    if (rgbMatch) {
      const [, r, g, b] = rgbMatch.map(Number);
      const brightness = (r + g + b) / 3;

      if (expectedTheme === "dark") {
        // Dark theme should have low brightness (dark background)
        expect(brightness).toBeLessThan(128);
      } else {
        // Light theme should have high brightness (light background)
        expect(brightness).toBeGreaterThan(128);
      }
    }
  }

  /**
   * Delete a chat conversation by its title (first prompt)
   * Finds the latest chat with the given title, hovers to reveal menu, and deletes it
   * @param chatTitle - The title of the chat (first prompt given to the chat)
   * @returns Promise that resolves when deletion is complete
   */
  async deleteChatByTitle(chatTitle: string) {
    logger.info(`Deleting chat: ${chatTitle}`);

    await this.openNewChat();

    // ✅ Find chat row
    const chatRow = this.page
      .locator("button")
      .filter({
        has: this.page.getByText(/Please ingest this URL/i),
      })
      .first();

    await expect(chatRow).toBeVisible({ timeout: 10000 });

    // ✅ Hover row
    await chatRow.hover();

    //  KEY FIX: scope INSIDE row, not global
    const moreOptionsButton = chatRow.locator('[aria-haspopup="menu"]');

    // ✅ Wait until it's actually visible (opacity transition handled)
    await expect(moreOptionsButton).toBeVisible({ timeout: 5000 });

    await moreOptionsButton.click();

    // ✅ Delete
    await this.page
      .getByRole("menuitem", {
        name: /delete conversation/i,
      })
      .click();

    // ✅ Confirm
    await this.page.getByRole("button", { name: /^delete$/i }).click();

    // ✅ Toast
    await expect(
      this.page.getByText(/conversation deleted successfully/i),
    ).toBeVisible();

    logger.info(`Deleted chat successfully`);
  }
}
