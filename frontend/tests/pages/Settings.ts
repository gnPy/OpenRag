import { expect, Page } from "@playwright/test";
import config from "../config/test.config";
import logger from "../utils/logger";

export class Settings {
  constructor(private page: Page) {}

  //Getters for elements
  private configureButton(providerName: string) {
    return this.page
      .locator("div.rounded-xl, div.border-border.group")
      .filter({ hasText: providerName })
      .getByRole("button", { name: "Configure" });
  }

  private setupHeading(providerName: string) {
    return this.page.getByRole("heading", { name: providerName });
  }

  private get watsonxProjectID() {
    return this.page.locator("#project-id");
  }

  private get apiKey() {
    return this.page.locator("#api-key");
  }

  private get watsonxEndPoint() {
    return this.page.getByRole("combobox");
  }

  private watsonxOption(value: string) {
    return this.page.locator('[role="option"]', { hasText: value });
  }

  private get saveModelProvider() {
    return this.page.getByRole("button", { name: "Save" });
  }

  private getToastByText(message: string) {
    return this.page
      .locator("[data-sonner-toast]")
      .locator("[data-title]", { hasText: message });
  }

  private editSetupButton(providerName: string) {
    return this.page
      .locator("div.rounded-xl, div.border-border.group")
      .filter({ hasText: providerName })
      .getByRole("button", { name: "Edit Setup" });
  }
  private get removeModelProvider() {
    return this.page.getByRole("button", { name: "Remove" });
  }

  private get removeConfigButton() {
    return this.page
      .locator("div", { hasText: "Remove configuration?" })
      .getByRole("button", { name: "Remove" });
  }

  private get watsonxConnectionError() {
    return this.page.getByText("Connection failed. Check your configuration.");
  }

  async open() {
    // Check if already on settings page and content is visible
    if (this.page.url().includes("/settings")) {
      const modelProviders = this.page.getByText("Model Providers");
      const isVisible = await modelProviders.isVisible().catch(() => false);
      if (isVisible) {
        return; // Already on settings and content is loaded
      }
    }

    // Navigate to settings
    const settingsLink = this.page.getByRole("link", { name: "Settings" });
    await settingsLink.click();

    // Wait for settings page to load
    await expect(this.page.getByText("Model Providers")).toBeVisible({
      timeout: 15000,
    });
  }

  async saveIngestSettings() {
    const saveButton = this.page.getByRole("button", {
      name: /save ingest settings/i,
    });

    await expect(saveButton).toBeVisible();
    await saveButton.click();

    await expect(
      this.page.getByText(/settings updated successfully/i).first(),
    ).toBeVisible({ timeout: 120000 });
  }

  async setPictureDescriptions(enabled: boolean) {
    await this.open();

    const toggle = this.page.getByRole("switch", {
      name: /picture descriptions/i,
    });

    await toggle.scrollIntoViewIfNeeded();

    const state = await toggle.getAttribute("data-state");
    const isChecked = state === "checked";

    if (isChecked !== enabled) {
      await toggle.click();
      await this.saveIngestSettings();
    }
  }

  async setTableStructure(enabled: boolean) {
    await this.open();

    const toggle = this.page.getByRole("switch", {
      name: /table structure/i,
    });

    await toggle.scrollIntoViewIfNeeded();

    const state = await toggle.getAttribute("data-state");
    const isChecked = state === "checked";

    if (isChecked !== enabled) {
      await toggle.click();
      await this.saveIngestSettings();
    }
  }

  async setOCR(enabled: boolean) {
    await this.open();

    const toggle = this.page.getByRole("switch", {
      name: /^ocr$/i,
    });

    await toggle.scrollIntoViewIfNeeded();

    const state = await toggle.getAttribute("data-state");
    const isChecked = state === "checked";

    if (isChecked !== enabled) {
      await toggle.click();
      await this.saveIngestSettings();
    }
  }

  async selectModel(section: string, model: string) {
    await this.open();

    const dropdown = this.page
      .getByText(new RegExp(section, "i"))
      .locator("..")
      .getByRole("combobox");

    await dropdown.scrollIntoViewIfNeeded();

    const currentText = (await dropdown.textContent())?.toLowerCase() || "";
    if (currentText.includes(model.toLowerCase())) return;

    await dropdown.click();

    let search = this.page.locator(
      'input[placeholder="Search model..."]:focus',
    );

    if ((await search.count()) === 0) {
      // fallback safety
      search = this.page
        .locator('input[placeholder="Search model..."]')
        .first();
    }

    await expect(search).toBeVisible({ timeout: 5000 });

    await search.fill(model);

    const option = this.page.getByRole("option", {
      name: new RegExp(`^${model}$`),
    });

    await expect(option).toBeVisible({ timeout: 10000 });

    //  stabilize before click
    await option.waitFor({ state: "visible" });

    await option.click({ timeout: 5000 });

    // immediately wait for dropdown to disappear (key!)
    await option.waitFor({ state: "detached" }).catch(() => {});

    //  wait for UI update (prevents retry issues)
    await this.page
      .getByText(/settings updated successfully/i)
      .first()
      .waitFor({ timeout: 20000 })
      .catch(() => {});
  }

  /**
   * Update chunk size and overlap settings
   * @param chunkSize - Chunk size value (e.g., "500")
   * @param chunkOverlap - Chunk overlap value (e.g., "50")
   */
  async updateChunkSettings(chunkSize: string, chunkOverlap: string) {
    await this.open();

    // Find and update chunk size input
    const chunkSizeInput = this.page.getByLabel(/chunk size/i);
    await chunkSizeInput.scrollIntoViewIfNeeded();
    await chunkSizeInput.clear();
    await chunkSizeInput.fill(chunkSize);

    // Find and update chunk overlap input
    const chunkOverlapInput = this.page.getByLabel(/chunk overlap/i);
    await chunkOverlapInput.scrollIntoViewIfNeeded();
    await chunkOverlapInput.clear();
    await chunkOverlapInput.fill(chunkOverlap);

    // Save settings
    await this.saveIngestSettings();
  }

  /**
   * Configure IBM watsonx.ai model provider
   */
  async configureWatsonxai() {
    logger.info("Configuring watsonx.ai settings");
    const configureBtn = this.configureButton("IBM watsonx.ai");
    const editBtn = this.editSetupButton("IBM watsonx.ai");
    //If Configure button is visible -> do setup
    if (await configureBtn.isVisible()) {
      await configureBtn.click();
      await expect(this.setupHeading("IBM watsonx.ai")).toBeVisible();
      const { url, projectId, apiKey } = config.watsonx;
      await this.watsonxEndPoint.click();
      const option = this.watsonxOption(url);
      await expect(option).toBeVisible({ timeout: 10000 });
      await option.click();
      await this.watsonxProjectID.fill(projectId);
      await this.apiKey.fill(apiKey);
      await this.saveModelProvider.click();
      logger.info("Watsonx.ai configuration completed");
      await expect(
        this.getToastByText("IBM watsonx.ai successfully configured"),
      ).toBeVisible({ timeout: 20000 });
      await expect(editBtn).toBeEnabled();
    }
    //Else if already configured -> skip setup
    else if (await editBtn.isVisible()) {
      logger.info("Watsonx.ai already configured. Skipping setup.");
      await expect(editBtn).toBeEnabled();
    }
    //Neither found
    else {
      throw new Error("Neither Configure nor Edit Setup button is visible");
    }
  }

  /**
   * Remove model provider configuration
   */
  async removeModelProviderSetup(modelProvider: string) {
    const editButton = this.editSetupButton(modelProvider);
    const configureButton = this.configureButton(modelProvider);
    //If already configured (Edit Setup visible)
    if (await editButton.isVisible()) {
      logger.info(`${modelProvider} is configured. Removing setup...`);
      await editButton.click();
      await this.removeModelProvider.click();
      await this.removeConfigButton.click();
      await expect(
        this.getToastByText(`${modelProvider} configuration removed`),
      ).toBeVisible();
    }
    //If not configured
    else if (await configureButton.isVisible()) {
      logger.info(`${modelProvider} is not configured. Skipping removal.`);
    }
    //Unexpected state
    else {
      throw new Error(
        `No Configure/Edit Setup button found for ${modelProvider}`,
      );
    }
  }

  /**
   * Configure Openai model provider
   */
  async configureOpenAPI() {
    logger.info("Configuring Openai settings");
    const configureBtn = this.configureButton("OpenAI");
    const editBtn = this.editSetupButton("OpenAI");
    //If Configure button is visible -> do setup
    if (await configureBtn.isVisible()) {
      await configureBtn.click();
      await expect(this.setupHeading("OpenAI")).toBeVisible();
      const apiKey = config.openaiApiKey;
      await this.apiKey.fill(apiKey);
      await this.saveModelProvider.click();
      logger.info("OpenAI configuration completed");
      await expect(
        this.getToastByText("OpenAI successfully configured"),
      ).toBeVisible();
      await expect(editBtn).toBeEnabled();
    }
    //Else if already configured -> skip setup
    else if (await editBtn.isVisible()) {
      logger.info("OpenAI already configured. Skipping setup.");
      await expect(editBtn).toBeEnabled();
    }
    //Neither found
    else {
      throw new Error("Neither Configure nor Edit Setup button is visible");
    }
  }

  /**
   * Configure IBM watsonx.ai model provider with invalid credentials
   */
  async configureWatsonxaiInvalidCredentials(
    url: string,
    projectId: string,
    apiKey: string,
  ) {
    logger.info("Configuring watsonx.ai settings with invalid credentials");
    const configureBtn = this.configureButton("IBM watsonx.ai");
    const editBtn = this.editSetupButton("IBM watsonx.ai");
    //If Configure button is visible -> do setup
    if (await configureBtn.isVisible()) {
      await configureBtn.click();
      await expect(this.setupHeading("IBM watsonx.ai")).toBeVisible();
      await this.watsonxEndPoint.click();
      const option = this.watsonxOption(url);
      await expect(option).toBeVisible({ timeout: 10000 });
      await option.click();
      await this.watsonxProjectID.fill(projectId);
      await this.apiKey.fill(apiKey);
      await this.saveModelProvider.click();
      logger.info(
        "Verify that watsonx.ai configuration failed due to invalid credentials",
      );
      await expect(this.watsonxConnectionError).toBeVisible();
    }
  }
}
