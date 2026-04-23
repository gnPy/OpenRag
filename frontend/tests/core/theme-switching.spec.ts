import { expect, test } from "../utils/fixtures";
import { navigateToChat } from "../utils/navigation";

test.describe("Theme Switching Functionality", () => {
  test("Test light and dark theme modes @33219207", async ({ page, chat }) => {
    // Page is already navigated to /chat by the fixture
    await navigateToChat(page);
    // Skip the onboarding tour if it appears
    const skipButton = page.getByRole("button", { name: /skip overview/i });
    try {
      await skipButton.waitFor({ timeout: 3000 });
      await skipButton.click();
      await page.waitForTimeout(500);
    } catch (error) {
      // No onboarding tour, continue
    }

    // Test Light Mode
    await chat.switchTheme("light");
    await page.waitForTimeout(500);

    let currentTheme = await chat.getCurrentTheme();
    expect(currentTheme).toBe("light");
    await chat.verifyThemeColors("light");

    // Test Dark Mode
    await chat.switchTheme("dark");
    await page.waitForTimeout(500);

    currentTheme = await chat.getCurrentTheme();
    expect(currentTheme).toBe("dark");
    await chat.verifyThemeColors("dark");
  });
});
