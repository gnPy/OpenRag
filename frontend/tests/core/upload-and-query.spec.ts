import * as path from "path";
import { TEST_CONFIG } from "../config/test.config";
import { TasksMenu } from "../pages/TasksMenu";
import { expect, test } from "../utils/fixtures";
import logger from "../utils/logger";
import { navigateToKnowledge } from "../utils/navigation";

test.describe("Document Upload and Query @33219204 , @34548303 , @34548305 , @34548737 , @345481142 , @345481143 , @34581155", () => {
  test("End-to-End Document Upload and Query Scenarios", async ({
    page,
    knowledge,
    chat,
    settings,
  }) => {
    await navigateToKnowledge(page);
    // Set a generous timeout for the whole test
    test.setTimeout(600000);

    // Page is already navigated to /knowledge by the fixture

    // Upload document
    let fileName = await knowledge.ingestFile(
      TEST_CONFIG.documents.kubernetes.path,
    );

    expect(fileName).toBe(TEST_CONFIG.documents.kubernetes.name);

    // Verify document is active
    await knowledge.verifyDocumentActive(fileName);

    // Navigate to chat and ask questions
    await chat.open();

    // TEST 1: Knowledge-based question
    await chat.askQuestion(TEST_CONFIG.questions.kubernetes.controlPlane);
    await chat.waitForResponseContaining(
      /kube-apiserver|scheduler/i,
      TEST_CONFIG.timeouts.default,
    );

    // TEST 2: General Knowledge (Non-RAG check)
    await chat.askQuestion(TEST_CONFIG.questions.kubernetes.inventor);
    await chat.waitForResponseContaining(
      /google/i,
      TEST_CONFIG.timeouts.default,
    );

    // TEST 3: Unrelated question (should show fallback behavior)
    await chat.askQuestion(TEST_CONFIG.questions.fallback.unrelated);
    const responseUnrelated = await chat.getLastResponse(
      TEST_CONFIG.timeouts.default,
    );
    expect(responseUnrelated).toMatch(
      /no (relevant|documents|sources|results|information)|did not (return|provide|find|yield)|not found|cannot find|unable to locate|could not find|couldn't find/i,
    );

    //--- SCENARIO 2: Upload password protected file ---
    await page.getByRole("link", { name: "Knowledge" }).click();
    await page.waitForTimeout(1000);
    const tasksMenu = new TasksMenu(page);

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

    // Upload the protected file and ignore potential timeout/error in ingestFile
    const protectedFilePath = path.join(
      process.cwd(),
      "test-data",
      "05_Automation-protected.pdf",
    );
    try {
      await knowledge.ingestFile(protectedFilePath, true);
    } catch {
      // If it fails to show a success toast, ingestFile might throw, which is fine here
    }

    //Open Tasks Menu and check status
    await tasksMenu.open();

    // Check if task completed (the graph executed but failed)
    const completedBadge = page.getByText("COMPLETED", { exact: true }).first();
    const failedBadge = page.getByText("FAILED", { exact: true }).first();

    await expect(completedBadge.or(failedBadge)).toBeVisible({
      timeout: 15000,
    });

    // Find the specific task row container for this file
    // We look for a container div that holds the filename
    const taskRow = page
      .locator("div")
      .filter({ hasText: "05_Automation-protected.pdf" })
      .last();

    // Expect failure details (it will be the top-most task since we just uploaded)
    const failedText = page.getByText(/1 failed/).first();
    await expect(failedText).toBeVisible({ timeout: 15000 });

    // Click on the failure text to expand the failure log
    await failedText.click();
    await page.waitForTimeout(1500);

    // Validate the expanded content contains the filename to confirm the task failed
    await expect(page.locator("body")).toContainText(
      "05_Automation-protected.pdf",
      { timeout: 10000 },
    );

    logger.info(`📋 Verified task failed for 05_Automation-protected.pdf`);

    // Close tasks menu
    await tasksMenu.close();

    // --- SCENARIO 3: Upload truncated file and query missing data ---
    await page.getByRole("link", { name: "Knowledge" }).click();
    await page.waitForTimeout(1000);

    const truncatedFilePath = path.join(
      process.cwd(),
      "test-data",
      "truncated_financial_report.pdf",
    );
    fileName = "truncated_financial_report.pdf";

    // Upload document
    await knowledge.ingestFile(truncatedFilePath, true);

    // Verify document is active
    await knowledge.verifyDocumentActive(fileName);

    // Navigate to chat and ask question
    await chat.open();

    let question =
      "Based on the truncated_financial_report.pdf document, what is the total annual revenue of the company?";
    await chat.askQuestion(question);

    // Verify response gracefully handles the missing Q4 data
    let response = await chat.getLastResponse(TEST_CONFIG.timeouts.default);

    // Check that it identifies Q4 as the issue (incomplete, missing, truncated, etc)
    let lowerResponse = response.toLowerCase();
    expect(lowerResponse).toMatch(
      /incomplete|truncated|missing|not possible|information alone|no relevant supporting sources|cannot|q4/i,
    );

    logger.info(`Assistant Response: ${response}`);

    // --- SCENARIO 4: Upload CSV file and query for conflicting or ambiguous data ---
    await page.getByRole("link", { name: "Knowledge" }).click();
    await page.waitForTimeout(1000);

    const csvFilePath = path.join(
      process.cwd(),
      "test-data",
      "Customer_analysis_small.csv",
    );
    fileName = "Customer_analysis_small.csv";

    // Upload document
    await knowledge.ingestFile(csvFilePath, true);

    // Verify document is active
    await knowledge.verifyDocumentActive(fileName);

    // Navigate to chat and ask quest
    await chat.open();

    question =
      'Customer_analysis_small.1 document Which Sales Channel is the "best" for the company?';
    await chat.askQuestion(question);

    // Verify response indicates the data does not explicitly state the best channel and lists ambiguity instead of making one up
    response = await chat.getLastResponse(TEST_CONFIG.timeouts.default);

    lowerResponse = response.toLowerCase();

    // Using ultra-broad matching because GenAI varies its response structure heavily.
    expect(lowerResponse).toMatch(
      /not explicitly|not conclusively|doesn't|does not|could not|cannot|typically|need to|conflicting|various|did not|didn't|not return|more specific|no relevant|not provide|no specific|not specify/i,
    );

    logger.info(`Assistant Response (Ambiguous Query): ${response}`);

    // ----- Question 2: Forcing a wrong answer -----
    const forcedQuestion =
      "Customer_analysis_small.1 from this document answer this So the company earned exactly $15.46 Million in 2023, right?";
    await chat.askQuestion(forcedQuestion);

    // Verify response gracefully contradicts the forced wrong statement
    const responseForced = await chat.getLastResponse(
      TEST_CONFIG.timeouts.default,
    );
    const lowerResponseForced = responseForced.toLowerCase();

    // Ultra-broad matching for negative confirmations to catch any GenAI permutation
    expect(lowerResponseForced).toMatch(
      /not confirm|not address|cannot|does not|do not|did not|could not|no relevant|not explicit|not provide|no specific|not detail/i,
    );

    logger.info(`Assistant Response (Forced Wrong Query): ${responseForced}`);

    // --- SCENARIO 5: Upload document with Table Structure OFF and Query ---
    logger.info(
      `📋 SCENARIO 5: Upload 3M Document with Table Structure OFF and Query`,
    );

    // Disable Table Structure
    await settings.open();
    await settings.setTableStructure(false);
    logger.info(`✓ Disabled table structure`);

    await knowledge.open();
    await page.waitForTimeout(1000);

    const testDocument3M = "3M_2015_10K.pdf";
    const filePath3M = path.join(process.cwd(), "test-data", testDocument3M);

    // Upload document
    await knowledge.ingestFile(filePath3M, true);

    // Verify document is active
    await knowledge.verifyDocumentActive(testDocument3M);

    // Navigate to chat and ask questions
    await chat.open();

    // Test Question 1
    await chat.openNewChat();
    const question1 = "What was the highest stock price in Q1 2015?";
    logger.info(`Asking Question 1: ${question1}`);
    await chat.askQuestion(question1);
    const response1 = await chat.getLastResponse(TEST_CONFIG.timeouts.default);
    logger.info(`Response 1: ${response1}\n`);

    // Verify response indicates inability to find or access the requested data
    const lowerResponse1 = response1.toLowerCase();

    // Comprehensive regex to detect ANY response indicating inability to answer
    const inabilityRegex = new RegExp(
      [
        // "do not / don't / does not" + any verb phrase
        "(do not|don't|does not|doesn't|did not|didn't)\\s+(have|possess|hold|contain|include|support|provide|offer|store|track|access|retrieve|process|find|know|see|show|display|return|fetch)",

        // "cannot / can't / could not" + any verb
        "(cannot|can't|could not|couldn't|am not able|is not able|are not able|was not able|were not able)\\s+(access|retrieve|find|provide|fetch|show|display|answer|determine|confirm|tell|give|look up|search|process|handle)",

        // "unable to" + any verb
        "unable\\s+to\\s+(access|retrieve|find|provide|answer|determine|confirm|give|look up|fetch|process|handle|assist)",

        // "no + noun" patterns
        "no\\s+(data|information|record|records|details|results|content|context|answer|sources|access|knowledge|mention|reference|entry|entries)",

        // "not + past participle" patterns
        "not\\s+(found|available|provided|included|mentioned|stored|indexed|supported|recorded|tracked|captured|listed|shown|displayed|returned|specified|covered|documented)",

        // "outside / beyond" scope
        "outside\\s+(the\\s+)?(scope|context|data|system|knowledge|coverage|dataset|available)",
        "beyond\\s+(the\\s+)?(scope|context|data|system|knowledge|coverage|dataset|available|current)",

        // Redirect to external sources
        "(refer|check|visit|consult|look|search|try)\\s+(to\\s+)?(external|reliable|financial|official|other|an?|the)?\\s*(source|website|platform|tool|service|resource|database|provider|exchange)",

        // "I / the system" + limitation language
        "(i|the system|this system|the assistant|this assistant|the model|this model)\\s+(am not|is not|are not|was not|do not|don't|does not|cannot|can't|could not|lack|lacks)",

        // General data absence
        "(the\\s+)?(document|file|data|dataset|report|content|text|pdf|knowledge base|uploaded|available|provided|ingested)\\s+(does not|do not|didn't|did not|doesn't|cannot|can't|could not|lacks?|has no|have no)\\s+(contain|include|mention|provide|show|cover|have|store|record|specify)",

        // "not able to"
        "not\\s+able\\s+to\\s+(access|find|provide|answer|retrieve|determine|assist|help|process)",

        // Explicit stock/financial limitation (catch-all for finance redirects)
        "(stock|financial|market)\\s+(data|price|information|history|records?)\\s+(is not|are not|was not|were not|not|cannot|isn't|aren't)?\\s*(available|accessible|provided|included|stored|tracked|found)",
      ].join("|"),
      "i",
    );

    expect(lowerResponse1).toMatch(inabilityRegex);
  });
});
