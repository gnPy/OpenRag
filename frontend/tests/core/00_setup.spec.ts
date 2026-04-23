import { test } from "../utils/fixtures";
import { navigateToChat } from "../utils/navigation";

test.describe("Global Setup", () => {
  test("@smoke Run onboarding if needed", async ({ page }) => {
    // Navigate to chat page - onboarding is automatically handled by navigateToChat
    await navigateToChat(page);
  });
});
