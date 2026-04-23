import path from "path";
import { expect, test } from "../utils/fixtures";
import { navigateToSettings } from "../utils/navigation";

const testDocumentPath = path.join(__dirname, "../test-data/AMCOR_2022.pdf");
const testDocumentName = "AMCOR_2022.pdf";
const verificationQuestion =
  "What types of securities are registered and on which exchange are they listed?";

/**
 * Test: Switch model providers using watsonx.ai and openai
 * Verify user is able to switch model providers
 */
test.describe("Update model providers to watsonx.ai and openai @33219219, @33219229, @33219231", () => {
  test("Verify user is able to switch to watsonx.ai provider", async ({
    page,
    settings,
    knowledge,
    chat,
  }) => {
    //test.skip(true, 'Skipping due to bug https://github.com/langflow-ai/openrag/issues/1335');
    await navigateToSettings(page);
    await settings.configureWatsonxai();
    await settings.removeModelProviderSetup("OpenAI");
    await knowledge.deleteDocument(testDocumentName);
    await knowledge.ingestFile(testDocumentPath);
    await knowledge.verifyDocumentActive(testDocumentName);
    await chat.open();
    const responseWatsonx = await chat.askQuestion(
      verificationQuestion,
      120000,
    );
    expect(
      ["Ordinary Shares", "Guaranteed Senior Notes", "AMCR", "AUKF/27"].every(
        (keyword) => responseWatsonx.includes(keyword),
      ),
    ).toBe(true);
  });

  test("Restore OpenAI provider and verify functionality", async ({
    settings,
    chat,
    page,
    knowledge,
  }) => {
    //test.skip(true, 'Skipping due to bug https://github.com/langflow-ai/openrag/issues/1335');
    await navigateToSettings(page);
    await settings.configureOpenAPI();
    await settings.removeModelProviderSetup("IBM watsonx.ai");
    await knowledge.deleteDocument(testDocumentName);
    await knowledge.ingestFile(testDocumentPath);
    await chat.open();
    await chat.openNewChat();
    const responseOpenai = await chat.askQuestion(verificationQuestion, 120000);
    expect(
      ["Ordinary Shares", "Guaranteed Senior Notes", "AMCR", "AUKF/27"].every(
        (keyword) => responseOpenai.includes(keyword),
      ),
    ).toBe(true);
  });
});

/**
 * Test: Verify invalid credentials are not accepted for watsonx.ai
 */
test.describe("Verify invalid credentials are not accepted for watsonx.ai @34581239", () => {
  test("Verify invalid credentials are not accepted for watsonx.ai", async ({
    page,
    settings,
  }) => {
    await navigateToSettings(page);
    //Remove existing watsonx.ai setup if present
    await settings.removeModelProviderSetup("IBM watsonx.ai");
    await settings.configureWatsonxaiInvalidCredentials(
      "https://us-south.ml.cloud.ibm.com",
      "4865-b94f-d0a80ad0f62a",
      "Z79J_MUqLtVY",
    );
  });
});
