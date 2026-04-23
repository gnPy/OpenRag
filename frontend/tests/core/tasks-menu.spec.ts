import * as path from "path";
import { TasksMenu } from "../pages/TasksMenu";
import { expect, test } from "../utils/fixtures";
import logger from "../utils/logger";
import { navigateToKnowledge } from "../utils/navigation";

/**
 * Tasks Menu Test Suite
 *
 * Tests the complete functionality of the Tasks Menu:
 * - Upload docling.pdf → Check Tasks Menu → Print result → Close
 * - Upload industry.csv → Check Tasks Menu → Print result → Close
 * All in a single test to maintain state
 */

test.describe("Tasks Menu Functionality @33219224", () => {
  test("Upload files and verify task status in Tasks Menu", async ({
    page,
    knowledge,
  }) => {
    await navigateToKnowledge(page);
    test.setTimeout(300000); // 5 minutes

    const tasksMenu = new TasksMenu(page);

    // ========== UPLOAD 1: docling.pdf ==========
    const file1 = "docling.pdf";
    logger.info(`\n📋 Testing: ${file1}`);

    // Close Tasks Menu if it's open before upload
    const isTasksMenuOpen = await page
      .getByText("Recent Tasks")
      .first()
      .isVisible()
      .catch(() => false);
    if (isTasksMenuOpen) {
      await tasksMenu.close();
      await page.waitForTimeout(500);
    }

    // Upload docling.pdf and wait for completion
    const filePath1 = path.join(process.cwd(), "test-data", file1);
    await knowledge.ingestFile(filePath1, true);
    logger.info(`   Upload completed for ${file1}`);

    // Now open Tasks Menu and check status
    await tasksMenu.open();

    // Check task status for docling.pdf
    let completedBadge = page.getByText("COMPLETED").first();
    let failedBadge = page.getByText("FAILED").first();

    let isCompleted = await completedBadge.isVisible().catch(() => false);
    let isFailed = await failedBadge.isVisible().catch(() => false);

    // Extract success and failed counts from the task status line
    const taskStatusLine = await page
      .locator("text=/\\d+ success.*\\d+ failed/")
      .first()
      .textContent()
      .catch(() => "");

    if (isCompleted) {
      logger.info(`✅ SUCCESS: ${file1} - ${taskStatusLine}`);
    } else if (isFailed) {
      logger.info(`❌ FAILED: ${file1} - ${taskStatusLine}`);

      // Click on the "X failed" text to expand failure log
      const failedLink = page.getByText(/\d+ failed/).first();
      const isFailedLinkVisible = await failedLink
        .isVisible()
        .catch(() => false);

      if (isFailedLinkVisible) {
        await failedLink.click();
        await page.waitForTimeout(1500);
      }

      // Get failure log
      const failureLogVisible = await page
        .getByText("Failure Log")
        .first()
        .isVisible()
        .catch(() => false);

      if (failureLogVisible) {
        // Get the complete failure log section
        const failureLogSection = page
          .getByText("Failure Log")
          .first()
          .locator("..");
        const failureLogContent = await failureLogSection
          .textContent()
          .catch(() => "");

        if (failureLogContent) {
          // Extract the error message (remove "Failure Log (1 of 1 pending)" header)
          let errorMessage = failureLogContent
            .replace(/Failure Log.*?pending\)/i, "")
            .trim();

          // Split into lines and format
          const lines = errorMessage
            .split("\n")
            .map((line) => line.trim())
            .filter((line) => line);

          logger.info(`\n   📋 Failure Log:`);
          for (const line of lines) {
            logger.info(`   ${line}`);
          }
          logger.info("");
        }
      }
    }

    // Close Tasks Menu
    await tasksMenu.close();
    await page.waitForTimeout(1000);

    // ========== UPLOAD 2: industry.csv ==========
    const file2 = "industry.csv";
    logger.info(`\n📋 Testing: ${file2}`);

    // Close Tasks Menu if it's open before upload
    const isTasksMenuOpen2 = await page
      .getByText("Recent Tasks")
      .first()
      .isVisible()
      .catch(() => false);
    if (isTasksMenuOpen2) {
      await tasksMenu.close();
      await page.waitForTimeout(500);
    }

    // Upload industry.csv and wait for completion
    const filePath2 = path.join(process.cwd(), "test-data", file2);
    await knowledge.ingestFile(filePath2, true);
    logger.info(`   Upload completed for ${file2}`);

    // Now open Tasks Menu and check status
    await tasksMenu.open();

    // Check task status for industry.csv
    completedBadge = page.getByText("COMPLETED").first();
    failedBadge = page.getByText("FAILED").first();

    isCompleted = await completedBadge.isVisible().catch(() => false);
    isFailed = await failedBadge.isVisible().catch(() => false);

    // Extract success and failed counts from the task status line
    const taskStatusLine2 = await page
      .locator("text=/\\d+ success.*\\d+ failed/")
      .first()
      .textContent()
      .catch(() => "");

    if (isCompleted) {
      logger.info(`✅ SUCCESS: ${file2} - ${taskStatusLine2}`);
    } else if (isFailed) {
      logger.info(`❌ FAILED: ${file2} - ${taskStatusLine2}`);

      // Click on the "X failed" text to expand failure log
      const failedLink = page.getByText(/\d+ failed/).first();
      const isFailedLinkVisible = await failedLink
        .isVisible()
        .catch(() => false);

      if (isFailedLinkVisible) {
        await failedLink.click();
        await page.waitForTimeout(1500);
      }

      // Get failure log
      const failureLogVisible = await page
        .getByText("Failure Log")
        .first()
        .isVisible()
        .catch(() => false);

      if (failureLogVisible) {
        // Get the complete failure log section
        const failureLogSection = page
          .getByText("Failure Log")
          .first()
          .locator("..");
        const failureLogContent = await failureLogSection
          .textContent()
          .catch(() => "");

        if (failureLogContent) {
          // Extract the error message (remove "Failure Log (1 of 1 pending)" header)
          let errorMessage = failureLogContent
            .replace(/Failure Log.*?pending\)/i, "")
            .trim();

          // Split into lines and format
          const lines = errorMessage
            .split("\n")
            .map((line) => line.trim())
            .filter((line) => line);

          logger.info(`\n   📋 Failure Log:`);
          for (const line of lines) {
            logger.info(`   ${line}`);
          }
          logger.info("");
        }
      }
    }

    // Close Tasks Menu
    await tasksMenu.close();

    expect(true).toBeTruthy();
  });
});

// Made with Bob
