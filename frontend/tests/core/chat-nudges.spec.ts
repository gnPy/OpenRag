import { expect, test } from "../utils/fixtures";
import logger from "../utils/logger";
import { navigateToChat } from "../utils/navigation";
import { completeOnboarding } from "../utils/onboarding";

test.describe("Chat Suggestion Questions - Multiple Iterations @33219233 , @34581264", () => {
  test.beforeEach(async ({ page }) => {
    // Navigate to the application
    await navigateToChat(page);
  });

  test("@smoke Click suggested questions in multiple iterations and verify responses", async ({
    page,
    chat,
  }) => {
    const iterations = 2;

    for (let iteration = 1; iteration <= iterations; iteration++) {
      // Wait for page to be ready
      await page.waitForTimeout(2000);

      // Find suggestion buttons in the main chat area
      const mainChatArea = page.locator('main, [role="main"]').first();
      const suggestionButtons = mainChatArea.getByRole("button").filter({
        hasText: /.{15,}/, // Buttons with at least 15 characters
      });

      const suggestionCount = await suggestionButtons.count();

      if (suggestionCount === 0) {
        break;
      }

      // Get the first suggestion button
      const firstSuggestion = suggestionButtons.first();
      const suggestionText = await firstSuggestion.textContent();

      // Click the suggestion
      await firstSuggestion.click();

      // Wait for the response to start appearing (markdown element)
      const responseLocator = page.locator("div.markdown").last();
      await expect(responseLocator).toBeVisible({ timeout: 30000 });

      // Wait for "Thinking..." to disappear and actual response to appear
      await page.waitForTimeout(2000);

      // Wait for response to stop changing (streaming complete)
      let previousText = "";
      let stableCount = 0;
      const maxWaitTime = 120000; // 2 minutes max
      const startTime = Date.now();

      while (stableCount < 3 && Date.now() - startTime < maxWaitTime) {
        await page.waitForTimeout(1000);
        const currentText = (await responseLocator.textContent()) || "";

        // Skip if still showing "Thinking..."
        if (currentText.trim() === "Thinking...") {
          continue;
        }

        if (currentText === previousText && currentText.length > 50) {
          stableCount++;
        } else {
          stableCount = 0;
          previousText = currentText;
        }
      }

      // Check for function calls
      const functionCalls = page.getByText(/Function Call:/i);
      const functionCallCount = await functionCalls.count();
      if (functionCallCount > 0) {
        // Wait for function calls to complete
        const completedBadge = page.getByText("completed");
        if ((await completedBadge.count()) > 0) {
          await expect(completedBadge.first()).toBeVisible({ timeout: 30000 });
        }
      }

      // Get the response
      const response = await chat.getLastResponse(120000);

      // Verify response is substantial
      expect(response.length).toBeGreaterThan(50);

      // Verify response is not an error message (check for common error patterns)
      const responseLower = response.toLowerCase();
      const errorPatterns = [
        /^(sorry|apologies|unfortunately),?\s+(i|we)\s+(can't|cannot|couldn't|am unable|don't have)/i,
        /^(i|we)\s+(don't have|do not have|cannot find|couldn't find)\s+(any|the|enough)\s+(information|data|context)/i,
        /^(there (was|is) an error|an error occurred|something went wrong)/i,
        /^(the (request|query|operation) (failed|has failed))/i,
        /^(unable to (process|retrieve|find|access))/i,
      ];

      const hasError = errorPatterns.some((pattern) =>
        pattern.test(responseLower),
      );
      expect(hasError).toBe(false);

      logger.info(
        `Iteration ${iteration}/${iterations}: "${suggestionText}" - Response received (${response.length} chars)`,
      );

      // Wait before next iteration to let new suggestions appear
      await page.waitForTimeout(2000);
    }

    logger.info(" All suggestion iterations completed successfully");
  });

  test("Verify no chat nudges appear after deleting all files", async ({
    page,
    knowledge,
    chat,
  }) => {
    logger.info(
      "Starting negative test: Delete all files and check chat nudges",
    );

    // 1. Open knowledge section
    await knowledge.open();
    await page.waitForTimeout(2000);

    // 2. Check if the knowledge base is already empty
    // The UI shows a big "No knowledge" message when empty
    const noKnowledgeMsg = page.getByText("No knowledge", { exact: true });
    // Wait briefly to see if it appears
    const isEmpty = await noKnowledgeMsg
      .isVisible({ timeout: 2000 })
      .catch(() => false);

    if (!isEmpty) {
      // If there are files, select the source checkbox to select all files
      const selectAllCheckbox = page
        .locator('.ag-header-row input[type="checkbox"]')
        .first();

      // Wait for it to be actually attached/visible to avoid race conditions
      if (await selectAllCheckbox.isVisible({ timeout: 2000 })) {
        await selectAllCheckbox.click();
        await page.waitForTimeout(1000);

        // 3. Click the delete button
        const deleteBtn = page.getByRole("button", { name: "Delete" });
        if (await deleteBtn.isEnabled()) {
          await deleteBtn.click();
          await page.waitForTimeout(1000);

          // Confirm deletion
          const confirmBtn = page
            .getByRole("button", { name: "Delete" })
            .last();
          await confirmBtn.click();

          // Wait for the success toast and for the 'No knowledge' empty state to appear
          await page.waitForTimeout(2000);
          await expect(
            page.getByText("No knowledge", { exact: true }),
          ).toBeVisible({ timeout: 10000 });
        }
      }
    }

    // 4. Open new chat
    await chat.openNewChat();
    await page.waitForTimeout(3000);

    // 5. Verify no chat suggestions (nudges) appear
    // Wait a brief moment to ensure suggestions have time to load if they were going to
    await page.waitForTimeout(4000);

    // Find suggestion buttons in the main chat area
    const mainChatArea = page.locator('main, [role="main"]').first();
    const suggestionButtons = mainChatArea.getByRole("button").filter({
      hasText: /.{15,}/, // Buttons with at least 15 characters are suggestions
    });

    const suggestionCount = await suggestionButtons.count();
    expect(suggestionCount).toBe(0);

    logger.info(
      " Negative test passed: No chat suggestions are displayed after deleting library",
    );
  });
});
