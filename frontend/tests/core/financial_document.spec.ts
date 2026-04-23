import { OPENAI_CONFIG } from "../config/provider";
import { expect, test } from "../utils/fixtures";
import logger from "../utils/logger";
import { navigateToHome } from "../utils/navigation";

/**
 * Financial Document Ingestion Test Suite - Simplified Stability Test
 * Tests table structure extraction from financial documents (Walmart 10-Q)
 *
 * Configuration: Table Structure ON only
 * Tests: 2 questions x 3 runs each = 6 total test executions
 *
 * Test 1: Basic table data retrieval (Total Net Sales for April 30, 2023: 151,004 million)
 * Test 2: Out-of-scope query (Tesla revenue - should not hallucinate)
 */

// Helper function to normalize numbers for comparison
function normalizeNumber(text: string): string {
  return text.replace(/[$,\s]/g, "").toLowerCase();
}

// Helper function to check if response contains a number
function containsNumber(text: string, expectedNumber: string): boolean {
  const normalized = normalizeNumber(text);
  const variations = [
    expectedNumber,
    expectedNumber.replace(",", ""),
    `${expectedNumber}million`,
    `${expectedNumber}m`,
    `$${expectedNumber}`,
  ];

  return variations.some((variant) =>
    normalized.includes(normalizeNumber(variant)),
  );
}

test.describe("Financial Document - OpenAI @33219232", () => {
  test("Table Structure ON - Stability Test", async ({
    page,
    settings,
    knowledge,
    chat,
    cleanupDocuments,
  }) => {
    test.setTimeout(300000); // 5 minutes

    const testDocument = "WALMART_2024Q1_10Q.pdf";

    // Navigate to the application
    await navigateToHome(page);

    logger.info(`\n🧪 Testing Financial Document with OpenAI`);

    // Configure models
    await settings.open();
    await settings.selectModel("Language model", OPENAI_CONFIG.language);
    await settings.selectModel("Embedding model", OPENAI_CONFIG.embedding);
    logger.info(`  ✓ Language model set to: ${OPENAI_CONFIG.language}`);
    logger.info(`  ✓ Embedding model set to: ${OPENAI_CONFIG.embedding}`);

    // Document management
    await knowledge.open();
    await knowledge.deleteDocument(testDocument);
    await cleanupDocuments([testDocument]);

    // Enable table structure
    await settings.open();
    await settings.setTableStructure(true);

    // Ingest document
    await knowledge.open();
    const fileName = await knowledge.ingestFile(`test-data/${testDocument}`);
    await knowledge.verifyDocumentActive(fileName);

    // Track results
    let test1Passed = 0;
    let test2Passed = 0;

    // Open chat for testing
    await chat.open();

    // Run Test 1: Basic Table Data Retrieval - 3 times
    for (let i = 1; i <= 3; i++) {
      await chat.openNewChat();
      const question = "What is the total net sales for April 30, 2023?";
      const response = await chat.askQuestion(question, 90000);

      const hasNetSales =
        containsNumber(response, "151,004") ||
        containsNumber(response, "151004") ||
        response.includes("151.0") ||
        response.includes("$151");

      if (hasNetSales) {
        test1Passed++;
      }
    }

    // Run Test 2: Out-of-Scope Query - 3 times
    for (let i = 1; i <= 3; i++) {
      await chat.openNewChat();
      const question = "What is Tesla's revenue in this document?";
      const response = await chat.askQuestion(question, 90000);

      const responseLower = response.toLowerCase();

      // Check for hallucination
      const hasHallucination =
        /\$?\d+[\d,]*\s*(million|billion|m|b)/i.test(response) &&
        !responseLower.includes("walmart");

      // Check for proper "not available" response
      const indicatesNoInfo =
        responseLower.includes("not") ||
        responseLower.includes("no ") ||
        responseLower.includes("don't") ||
        responseLower.includes("doesn't") ||
        responseLower.includes("cannot") ||
        responseLower.includes("unable") ||
        responseLower.includes("access") ||
        responseLower.includes("document");

      if (!hasHallucination && indicatesNoInfo) {
        test2Passed++;
      }
    }

    // Report results
    logger.info(`\nStability Results - OpenAI:`);
    logger.info(`  Test 1 (Table Data): ${test1Passed}/3`);
    logger.info(`  Test 2 (Out-of-Scope): ${test2Passed}/3`);

    // Fail if any run failed
    expect(test1Passed).toBe(3);
    expect(test2Passed).toBe(3);
  });
});
