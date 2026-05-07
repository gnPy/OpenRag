import { expect, test } from "@playwright/test";
import { completeOnboarding } from "../utils/onboarding";

test("can configure OpenAI provider", async ({ page }) => {
  await completeOnboarding(page, {
    llmProvider: "openai",
    embeddingProvider: "openai",
    reset: true,
  });

  // Chat page

  await expect(page.getByText("How can I assist?")).toBeVisible({
    timeout: 30000,
  });

  await expect(
    page.getByTestId("conversation-button-What is OpenRAG?").first(),
  ).toBeVisible();

  await expect(page.getByTestId("selected-knowledge-filter")).toContainText(
    "test-document",
  );

  await page
    .getByTestId("chat-input")
    .fill(
      "From the uploaded test document, return only the exact value after 'ID:'",
    );

  await page.getByTestId("send-button").click();

  await expect(page.getByText("Thinking")).toBeVisible();

  await expect(page.getByText(/OPENRAG-GENERIC-ASSET-001/i)).toBeVisible({
    timeout: 60000,
  });

  await expect(page.getByTestId(/^suggestion-/)).toHaveCount(3, {
    timeout: 20000,
  });
});
