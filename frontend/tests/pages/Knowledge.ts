import { expect, Locator, Page } from "@playwright/test";
import path from "path";
import logger from "../utils/logger";

export class Knowledge {
  constructor(private page: Page) {}

  /**
   * Check if there's a critical search error in the knowledge base
   * Detects two types of errors:
   * 1. OpenSearch database errors (search_phase_execution_exception)
   * 2. Model-specific embedding errors (Failed to embed with model)
   * @throws Error if search error is detected
   */
  private async checkForSearchError() {
    // Wait a moment for any error messages to appear
    await this.page.waitForTimeout(1000);

    // Look for different types of search error messages
    const searchErrorGeneric = this.page.getByText(/search error/i);
    const transportError = this.page.getByText(
      /TransportError.*search_phase_execution_exception/i,
    );
    const embeddingError = this.page.getByText(/Failed to embed with model/i);

    try {
      // Check if any error message is visible
      const errorCheck = await Promise.race([
        searchErrorGeneric.isVisible().then(async (visible) => {
          if (visible) {
            // Get the full error text to determine the type
            const errorText = await searchErrorGeneric.textContent();
            return { type: "search_error", text: errorText };
          }
          return null;
        }),
        transportError
          .isVisible()
          .then((visible) =>
            visible
              ? {
                  type: "transport_error",
                  text: "TransportError(503, search_phase_execution_exception)",
                }
              : null,
          ),
        embeddingError.isVisible().then(async (visible) => {
          if (visible) {
            const errorText = await embeddingError.textContent();
            return { type: "embedding_error", text: errorText };
          }
          return null;
        }),
        new Promise<null>((resolve) => setTimeout(() => resolve(null), 2000)),
      ]);

      if (errorCheck) {
        // Determine error type and throw appropriate error
        if (
          errorCheck.type === "embedding_error" ||
          errorCheck.text?.includes("Failed to embed")
        ) {
          // Extract model name from error message if possible
          const modelMatch = errorCheck.text?.match(/model\s+([^\s]+)/i);
          const modelName = modelMatch ? modelMatch[1] : "unknown";

          throw new Error(
            `❌ MODEL ERROR: Search failed due to embedding model issue.\n` +
              `   Model: ${modelName}\n` +
              `   Error: ${errorCheck.text}\n` +
              `   This occurs when searching with a model that has documents indexed with it but the model is unavailable or misconfigured.\n` +
              `   Solution: Either fix the model configuration or switch to a different embedding model.`,
          );
        } else {
          // OpenSearch database error
          throw new Error(
            "❌ CRITICAL: Knowledge base search error detected (OpenSearch database issue).\n" +
              "   This error prevents all knowledge base operations.\n" +
              `   Error: ${errorCheck.text}\n` +
              "   Solution: Check OpenSearch service status and configuration.",
          );
        }
      }
    } catch (error) {
      // If it's our custom error, re-throw it
      if (
        error instanceof Error &&
        (error.message.includes("CRITICAL") ||
          error.message.includes("MODEL ERROR"))
      ) {
        throw error;
      }
      // Otherwise, no error found (which is good)
    }
  }

  /**
   * Check if the page is still open and usable
   */
  private isPageClosed(): boolean {
    return this.page.isClosed();
  }

  /**
   * Safe wrapper for waitForTimeout that skips if the page is closed.
   * Prevents "Target page, context or browser has been closed" errors
   * in cleanup/catch blocks after the test has timed out.
   */
  private async safeWait(ms: number): Promise<void> {
    if (this.isPageClosed()) return;
    try {
      await this.page.waitForTimeout(ms);
    } catch {
      // Page was closed during the wait — swallow silently
    }
  }

  async open() {
    await this.page.getByRole("link", { name: "Knowledge" }).click();
    await expect(this.page.getByText("Project Knowledge")).toBeVisible();

    // Automatically check for critical errors every time we open knowledge base
    await this.checkForSearchError();
  }

  /**
   * Click "Fetch latest docs" button to refresh the document list.
   * Waits for the "What is OpenRAG?" document re-ingestion to complete.
   */
  async fetchLatestDocs() {
    if (this.isPageClosed()) return;

    const fetchButton = this.page.getByRole("button", {
      name: "Fetch latest docs",
    });
    await fetchButton.click();

    // Wait for the refresh confirmation toast
    await expect(
      this.page.getByText(/OpenRAG docs were refreshed/i).first(),
    ).toBeVisible({ timeout: 10000 });

    // Brief pause — reduced from 1000 ms to avoid eating into the test budget
    await this.safeWait(500);

    // "Fetch latest docs" triggers re-ingestion of "What is OpenRAG?" document.
    // Wait for its "Task completed" message so we don't confuse it with our own uploads.
    try {
      if (this.isPageClosed()) return;

      await expect(this.page.getByText(/task completed/i).first()).toBeVisible({
        timeout: 15000,
      });

      logger.info(
        `  ⏳ Waiting for "What is OpenRAG?" re-ingestion to complete...`,
      );

      // Wait for the toast to auto-dismiss (~3-5 s); reduced from 6000 ms
      await this.safeWait(4000);
    } catch {
      // No task-completed message appeared — that's fine, just continue
      await this.safeWait(300);
    }
  }

  async ingestFile(
    filePath: string,
    overrideIfExists: boolean = true,
  ): Promise<string> {
    await this.open();
    // Handle both SaaS (lowercase) and OSS (uppercase) versions - use first() to handle multiple matches
    await this.page
      .getByRole("button", { name: /Add [Kk]nowledge/i })
      .first()
      .click();

    const fileName = path.basename(filePath);

    await this.page
      .locator('input[type="file"]')
      .first()
      .setInputFiles(filePath);
    if (overrideIfExists) {
      try {
        const overwriteDialog = this.page.getByText("Overwrite document");
        await overwriteDialog.waitFor({ state: "visible", timeout: 3000 });

        // Click the "Overwrite" button in the dialog
        const overwriteButton = this.page.getByRole("button", {
          name: "Overwrite",
        });
        await overwriteButton.click();
      } catch {
        // No overwrite dialog appeared, file is new
      }
    }
    await expect(this.page.getByText(/task completed/i).first()).toBeVisible({
      timeout: 120000,
    });

    // Close the "Add Knowledge" dropdown menu by pressing Escape or clicking outside
    await this.page.keyboard.press("Escape");
    await this.page.waitForTimeout(500);

    return fileName;
  }

  async ingestFolder(
    folderPath: string,
    expectedFileCount: number,
    timeout: number = 180000,
  ): Promise<string> {
    await this.open();

    // Handle both SaaS (lowercase) and OSS (uppercase) versions - use first() to handle multiple matches
    await this.page
      .getByRole("button", { name: /Add [Kk]nowledge/i })
      .first()
      .click();

    const folderName = path.basename(folderPath);

    const [fileChooser] = await Promise.all([
      this.page.waitForEvent("filechooser"),
      this.page.getByText("Folder").click(),
    ]);

    await fileChooser.setFiles(folderPath);

    // ❗ DO NOT click Upload blindly

    await expect(
      this.page.getByText(`${expectedFileCount} files uploaded successfully`),
    ).toBeVisible({ timeout });

    await this.page.keyboard.press("Escape");

    return folderName;
  }
  /**
   * Reset pagination to first page
   */
  private async resetToFirstPage() {
    const firstPageButton = this.page.getByRole("button", {
      name: /first page/i,
    });

    try {
      const ariaDisabled = await firstPageButton.getAttribute("aria-disabled");
      const classAttr = await firstPageButton.getAttribute("class");

      const isDisabled =
        ariaDisabled === "true" || classAttr?.includes("ag-disabled");

      if (!isDisabled) {
        await firstPageButton.click();
        await this.page.waitForTimeout(500);
      }
    } catch {
      // Button might not exist or not be clickable, that's fine
    }
  }

  /**
   * Find a row across all pages in the AG Grid.
   * Handles both virtualization scrolling and pagination.
   *
   * Strategy (in priority order):
   *   1. row-id attribute  — AG Grid sets this to the row's primary key; most reliable.
   *   2. Exact text match  — works when the cell text is not truncated.
   *   3. title attribute   — AG Grid often sets title="<full value>" even when the cell
   *                          text is visually truncated by CSS overflow.
   *   4. Partial text      — last resort; avoids false negatives from display trimming.
   *
   * @param key - The text to search for in the row
   * @returns The row locator if found
   * @throws Error if row not found after checking all pages
   */
  async findRowAcrossPages(key: string): Promise<Locator> {
    // Always reset to first page at the start for consistent behavior
    await this.resetToFirstPage();

    const gridContainer = this.page.locator(".ag-body-viewport");

    // Helper: try all four strategies against the currently rendered DOM.
    const tryFind = async (timeout: number): Promise<Locator | null> => {
      // 1. row-id attribute (most reliable — set by AG Grid to the data key)
      const rowById = this.page.locator(`[role="row"][row-id="${key}"]`);
      try {
        await expect(rowById.first()).toBeVisible({ timeout });
        return rowById.first();
      } catch {
        // not found by row-id
      }

      // 2. Exact text match inside the source cell
      const exactSourceCell = this.page
        .locator('[col-id="source"]')
        .getByText(new RegExp(`^${key}$`))
        .first();
      try {
        await expect(exactSourceCell).toBeVisible({ timeout });
        return exactSourceCell.locator('xpath=ancestor::*[@role="row"][1]');
      } catch {
        // not found by exact text
      }

      // 3. title attribute — handles truncated cell display text
      const cellWithTitle = this.page
        .locator(`[col-id="source"] [title="${key}"]`)
        .first();
      try {
        await expect(cellWithTitle).toBeVisible({ timeout });
        return cellWithTitle.locator('xpath=ancestor::*[@role="row"][1]');
      } catch {
        // not found by title
      }

      // 4. Partial / contains match as last resort
      const looseCell = this.page
        .locator('[col-id="source"]')
        .getByText(key, { exact: false })
        .first();
      try {
        await expect(looseCell).toBeVisible({ timeout });
        return looseCell.locator('xpath=ancestor::*[@role="row"][1]');
      } catch {
        return null;
      }
    };

    while (true) {
      // Check the current viewport first
      const found = await tryFind(3000);
      if (found) return found;

      // Scroll down incrementally inside AG Grid to reveal virtualised rows
      const prevScrollTop: number = await gridContainer.evaluate(
        (el) => el.scrollTop,
      );
      await gridContainer.evaluate((el) => {
        el.scrollTop += el.clientHeight;
      });
      await this.page.waitForTimeout(400);
      const newScrollTop: number = await gridContainer.evaluate(
        (el) => el.scrollTop,
      );

      const foundAfterScroll = await tryFind(2000);
      if (foundAfterScroll) return foundAfterScroll;

      // If scroll position didn't change we've hit the bottom of this page
      if (newScrollTop === prevScrollTop) {
        // Reset scroll before moving to the next paginated page
        await gridContainer.evaluate((el) => {
          el.scrollTop = 0;
        });

        const nextButton = this.page.getByRole("button", {
          name: /next page/i,
        });
        const ariaDisabled = await nextButton.getAttribute("aria-disabled");
        const classAttr = await nextButton.getAttribute("class");
        const isDisabled =
          ariaDisabled === "true" || classAttr?.includes("ag-disabled");

        if (isDisabled) break;

        await nextButton.click();
        await this.page.waitForTimeout(500);
      }
    }

    throw new Error(`Row with key "${key}" not found across all pages`);
  }

  /**
   * Search for a document by name using the search bar.
   * Note: Search is unreliable for document names; prefer findRowAcrossPages.
   * @param searchTerm - The term to search for (works better for content within documents)
   * @returns true if any results found, false otherwise
   */
  async searchDocument(searchTerm: string): Promise<boolean> {
    await this.open();

    // Fetch latest docs to ensure fresh data
    await this.fetchLatestDocs();

    const searchInput = this.page.locator('input[placeholder*="Search"]');
    await searchInput.fill(searchTerm);
    await this.page.keyboard.press("Enter");

    // Wait a moment for search results
    await this.page.waitForTimeout(1000);

    // Check if any rows are visible
    const rows = this.page
      .locator('[role="row"]')
      .filter({ has: this.page.locator('input[type="checkbox"]') });
    const count = await rows.count();

    return count > 0;
  }

  /**
   * Delete a document by name.
   * Uses findRowAcrossPages for reliable document location.
   * @param documentName - The name of the document to delete
   * @returns true if deletion was successful, false if document not found
   */
  async deleteDocument(
    documentNames: string | string[],
  ): Promise<boolean | { found: string[]; notFound: string[] }> {
    await this.open();

    // Fetch latest docs to ensure fresh data
    await this.fetchLatestDocs();

    // Handle single document case
    if (typeof documentNames === "string") {
      let row: Locator;
      try {
        row = await this.findRowAcrossPages(documentNames);
      } catch {
        return false; // Document not found
      }

      // Select the document (click checkbox)
      const checkbox = row.locator('input[type="checkbox"]');
      await checkbox.click();

      // Click the Delete button
      const deleteButton = this.page.getByRole("button", { name: "Delete" });
      await expect(deleteButton).toBeVisible();
      await deleteButton.click();

      // Confirm deletion in the dialog
      const confirmDialog = this.page.locator("text=Delete document");
      await expect(confirmDialog).toBeVisible({ timeout: 5000 });

      const confirmButton = this.page
        .getByRole("button", { name: "Delete" })
        .last();
      await confirmButton.click();

      // Wait for success message
      await expect(
        this.page.getByText(/successfully deleted \d+ document/i).first(),
      ).toBeVisible({ timeout: 10000 });

      // Wait for the success message to disappear
      await this.page.waitForTimeout(1000);

      return true;
    }

    // Handle multiple documents case
    const found: string[] = [];
    const notFound: string[] = [];

    // Find and select all documents that exist
    // findRowAcrossPages now resets to first page at the start automatically
    for (const documentName of documentNames) {
      try {
        const row = await this.findRowAcrossPages(documentName);
        const checkbox = row.locator('input[type="checkbox"]');
        await checkbox.click();
        found.push(documentName);
        await this.page.waitForTimeout(200); // Small delay between selections
      } catch {
        notFound.push(documentName);
      }
    }

    // If no documents were found, return early
    if (found.length === 0) {
      return { found, notFound };
    }

    // Click the Delete button
    const deleteButton = this.page.getByRole("button", { name: "Delete" });
    await expect(deleteButton).toBeVisible();
    await deleteButton.click();

    // Confirm deletion in the dialog
    const confirmDialog = this.page.locator("text=Delete document");
    await expect(confirmDialog).toBeVisible({ timeout: 5000 });

    const confirmButton = this.page
      .getByRole("button", { name: "Delete" })
      .last();
    await confirmButton.click();

    // Wait for success message
    await expect(
      this.page.getByText(/successfully deleted \d+ document/i).first(),
    ).toBeVisible({ timeout: 10000 });

    // Wait for the success message to disappear
    await this.page.waitForTimeout(1000);

    return { found, notFound };
  }

  /**
   * Open a document by clicking on it.
   * Uses findRowAcrossPages for reliable document location.
   * @param fileName - The name of the document to open
   */
  async openDocument(fileName: string) {
    await this.open();

    // Fetch latest docs to ensure fresh data
    await this.fetchLatestDocs();

    // Find the document row using reliable method
    const row = await this.findRowAcrossPages(fileName);

    // Click on the document link
    const fileLink = row.locator("span").filter({ hasText: fileName }).first();

    await expect(fileLink).toBeVisible({ timeout: 10000 });
    await fileLink.click();
  }

  async getFirstChunkText(): Promise<string> {
    await expect(this.page.getByText(/Chunk \d+/i).first()).toBeVisible();

    const chunk = this.page.locator("blockquote").first();
    return (await chunk.textContent()) || "";
  }

  async logFirstChunk(docName: string): Promise<string> {
    await this.openDocument(docName);
    const firstChunk = await this.getFirstChunkText();
    logger.info(`First chunk for "${docName}": ${firstChunk}`);
    return firstChunk;
  }

  /**
   * Verify that a document has 'Active' status.
   * Uses findRowAcrossPages for reliable document location.
   * @param docName - The name of the document to verify
   */
  async verifyDocumentActive(docName: string) {
    await this.open();
    await this.fetchLatestDocs();
    const row = await this.findRowAcrossPages(docName);
    const status = row.locator('[col-id="status"]');
    await expect(status).toContainText("Active", { timeout: 30000 });
  }

  async getDocumentStatus(docName: string): Promise<string> {
    await this.open();
    await this.fetchLatestDocs();

    const row = await this.findRowAcrossPages(docName);
    const status = row.locator('[col-id="status"]').first();

    await expect(status).toBeVisible({ timeout: 30000 });

    return ((await status.textContent()) || "").trim();
  }

  /**
   * Clear the search and return to unfiltered document list
   */
  async clearSearch() {
    // Find and click the close button (X) in the search bar
    const closeButton = this.page
      .locator('input[placeholder*="Search"]')
      .locator("..")
      .locator("button")
      .first();

    try {
      await closeButton.click({ timeout: 2000 });
      await this.page.waitForTimeout(1000);
    } catch {
      // If close button not found or not clickable, clear the input manually
      const searchInput = this.page.locator('input[placeholder*="Search"]');
      await searchInput.clear();
      await this.page.keyboard.press("Enter");
      await this.page.waitForTimeout(1000);
    }
  }

  /**
   * Search for content and get all matching document names
   * Extracts document names from the row-id attribute
   * @param searchTerm - The term to search for
   * @returns Array of document names that match the search
   */
  async getSearchResults(searchTerm: string): Promise<string[]> {
    await this.open();

    // Fetch latest docs to ensure fresh data
    await this.fetchLatestDocs();

    const searchInput = this.page.locator('input[placeholder*="Search"]');
    await searchInput.fill(searchTerm);
    await this.page.keyboard.press("Enter");

    // Wait longer for search to complete and results to render
    // Increased from 2000ms to 5000ms to handle slower indexing/search operations
    await this.page.waitForTimeout(5000);

    // Check for search errors that may have occurred during the search operation
    // This is critical as search_phase_execution_exception can happen at any time
    await this.checkForSearchError();

    // Get all data rows with checkboxes (these are the actual document rows, not headers)
    const dataRows = this.page.locator('[role="row"]').filter({
      has: this.page.locator('input[type="checkbox"]'),
    });

    const count = await dataRows.count();

    const documentNames: string[] = [];
    for (let i = 0; i < count; i++) {
      const row = dataRows.nth(i);

      // Get the row-id attribute which contains the document name
      const rowId = await row.getAttribute("row-id");

      // Filter out empty strings and add to results
      if (rowId && rowId.trim()) {
        documentNames.push(rowId.trim());
      }
    }

    // Clear the search to return to unfiltered state for next operations
    await this.clearSearch();

    return documentNames;
  }

  /**
   * Create a knowledge filter.
   * @param filterName - Name of the filter to create
   * @param sourceFileName - Name of the source file to include in the filter
   */
  async createKnowledgeFilter(filterName: string, sourceFileName: string) {
    await this.open();

    // Wait for the Knowledge Filters section to be visible
    await expect(this.page.getByText("Knowledge Filters")).toBeVisible({
      timeout: 5000,
    });

    // Click the + button next to "Knowledge Filters" using the title attribute
    const createFilterButton = this.page.locator(
      'button[title="Create New Filter"]',
    );
    await expect(createFilterButton).toBeVisible({ timeout: 5000 });
    await createFilterButton.click();

    // Wait for the filter form to appear by checking for the filter name input
    const filterNameInput = this.page
      .locator("input#filter-name")
      .or(this.page.locator('input[placeholder*="Filter name"]'))
      .first();
    await expect(filterNameInput).toBeVisible({ timeout: 5000 });

    // Fill in the filter name
    await filterNameInput.fill(filterName);
    await this.page.waitForTimeout(300);

    // Click on the "All sources" button/dropdown in the filter form (right panel)
    const sourcesButton = this.page
      .locator("button")
      .filter({ hasText: "All sources" })
      .first();
    await expect(sourcesButton).toBeVisible({ timeout: 5000 });
    await sourcesButton.click();

    // Wait for the dropdown menu to appear
    await this.page.waitForTimeout(500);

    // First, deselect "All sources" by clicking on it
    const allSourcesOption = this.page
      .locator('[role="option"]')
      .filter({ hasText: "All sources" })
      .first();
    await expect(allSourcesOption).toBeVisible({ timeout: 3000 });
    await allSourcesOption.click();
    await this.page.waitForTimeout(300);

    // Use the search input in the dropdown to find the specific document
    const searchInput = this.page
      .locator('input[placeholder*="Search options"]')
      .or(this.page.locator('input[placeholder*="search"]'))
      .first();
    await expect(searchInput).toBeVisible({ timeout: 3000 });
    await searchInput.fill(sourceFileName);
    await this.page.waitForTimeout(500);

    // Click on the filtered document option
    const sourceOption = this.page
      .locator('[role="option"]')
      .filter({ hasText: sourceFileName })
      .first();
    await expect(sourceOption).toBeVisible({ timeout: 5000 });
    await sourceOption.click();
    await this.page.waitForTimeout(500);

    // Close the dropdown by pressing Escape
    await this.page.keyboard.press("Escape");
    await this.page.waitForTimeout(300);

    // Click the "Create Filter" button
    const createButton = this.page.getByRole("button", {
      name: /Create Filter/i,
    });
    await expect(createButton).toBeVisible({ timeout: 5000 });
    await createButton.click();

    // Wait for the filter to be created (form should close)
    await this.page.waitForTimeout(1000);
  }

  /**
   * Delete a knowledge filter by name.
   * @param filterName - Name of the filter to delete
   */
  async deleteKnowledgeFilter(filterName: string) {
    await this.open();

    // Find the filter in the sidebar and click on it to open the form
    const filterItem = this.page.locator(`text="${filterName}"`).first();

    try {
      await expect(filterItem).toBeVisible({ timeout: 5000 });

      // Click on the filter to open the edit form
      await filterItem.click();

      // Wait for the "Delete Filter" button to appear (confirms form is open)
      const deleteButton = this.page.getByRole("button", {
        name: "Delete Filter",
      });
      await expect(deleteButton).toBeVisible({ timeout: 5000 });
      await deleteButton.click();

      // Wait for the form to close (filter deleted)
      await this.page.waitForTimeout(1000);
    } catch {
      // Filter not found or already deleted
    }
  }

  /**
   * Get all visible chunks in the chunk viewer.
   * @returns Array of chunk texts in order (top to bottom)
   */
  private async getAllChunks(): Promise<string[]> {
    // Wait for chunks to be visible
    await expect(this.page.getByText(/Chunk \d+/i).first()).toBeVisible({
      timeout: 5000,
    });

    // Get all visible chunk elements (blockquotes contain chunk text)
    const chunkElements = this.page.locator("blockquote");
    const count = await chunkElements.count();

    const chunkTexts: string[] = [];
    for (let i = 0; i < count; i++) {
      const chunkText = await chunkElements.nth(i).textContent();
      if (chunkText && chunkText.trim()) {
        chunkTexts.push(chunkText.trim());
      }
    }

    return chunkTexts;
  }

  /**
   * Search for chunks containing a specific token and return top 2 results.
   * @param searchToken - The token to search for in chunks
   * @returns Array containing the top 2 chunk texts after search
   */
  async searchChunks(searchToken: string): Promise<string[]> {
    // Locate the search input in the chunk viewer
    const searchInput = this.page.locator('input[placeholder*="Search"]');
    await expect(searchInput).toBeVisible({ timeout: 5000 });

    // Clear any existing search and enter the token
    await searchInput.clear();
    await searchInput.fill(searchToken);
    await this.page.keyboard.press("Enter");

    // Wait for search to complete and chunks to re-rank
    await this.page.waitForTimeout(2000);

    // Get all chunks after search
    const allChunks = await this.getAllChunks();

    // Return only the top 2 chunks
    return allChunks.slice(0, 2);
  }
}
