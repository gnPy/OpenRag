import path from "path";
import { OPENAI_CONFIG } from "../config/provider";
import { expect, test } from "../utils/fixtures";
import logger from "../utils/logger";
import { navigateToHome } from "../utils/navigation";

const TEST_DOCUMENT = "OpenRAG.Index.Test.Document.txt";
const TEST_DOCUMENT_PATH = path.join(__dirname, "../test-data", TEST_DOCUMENT);
// After ingestion, .txt files become .md files
const TEST_DOCUMENT_INGESTED = "OpenRAG.Index.Test.Document.md";
const UNIQUE_SEARCH_TOKEN = "OPENSEARCH-7419-ZX";

test("Opensearch Indexing - OpenAI @33219220", async ({
  page,
  settings,
  knowledge,
  cleanupDocuments,
}) => {
  test.setTimeout(180000);

  // Navigate to the application
  await navigateToHome(page);

  logger.info(`\n🧪 Testing Opensearch Indexing with OpenAI`);

  // Step 1: Cleanup test document if it exists (.txt becomes .md after ingestion)
  logger.info(`  🧹 Cleaning up existing test document...`);
  try {
    await knowledge.deleteDocument(TEST_DOCUMENT_INGESTED);
    logger.info(`  ✓ Test document cleaned up`);
  } catch (error) {
    logger.info(`  ℹ️  No existing test document to clean up`);
  }

  // Step 2: Set embedding model for OpenAI
  logger.info(`  ⚙️  Setting embedding model for OpenAI...`);
  await settings.selectModel("Embedding model", OPENAI_CONFIG.embedding);
  logger.info(`  ✓ Embedding model set to: ${OPENAI_CONFIG.embedding}`);

  // Step 3: Ingest the test document
  logger.info(`  📄 Ingesting test document...`);
  const ingestedFileName = await knowledge.ingestFile(TEST_DOCUMENT_PATH);
  logger.info(`  ✓ Document ingested: ${ingestedFileName}`);

  // Register for cleanup (use .md extension as that's what it becomes)
  await cleanupDocuments([TEST_DOCUMENT_INGESTED]);

  // Step 4: Wait for document to be indexed (Active status)
  logger.info(`  ⏳ Waiting for document to be indexed...`);
  await knowledge.verifyDocumentActive(TEST_DOCUMENT_INGESTED);
  logger.info(`  ✓ Document is indexed and active`);

  // Step 5: Search for the unique token
  // Note: Search works for content within documents, not document names
  logger.info(`  🔍 Searching for unique token: ${UNIQUE_SEARCH_TOKEN}`);
  const searchResults = await knowledge.getSearchResults(UNIQUE_SEARCH_TOKEN);

  logger.info(`  📊 Search results: ${searchResults.length} document(s) found`);
  searchResults.forEach((doc, index) => {
    logger.info(`     ${index + 1}. ${doc}`);
  });

  // Step 6: Verify results
  // The test document should be the ONLY result (note: .txt becomes .md after ingestion)
  if (searchResults.length === 0) {
    throw new Error(
      `❌ FAILED: Test document "${TEST_DOCUMENT_INGESTED}" did not appear in search results for token "${UNIQUE_SEARCH_TOKEN}"\n` +
        `   This means the document was not properly indexed or the search functionality is not working.`,
    );
  }

  if (searchResults.length > 1) {
    const otherDocs = searchResults.filter(
      (doc) => doc !== TEST_DOCUMENT_INGESTED,
    );
    throw new Error(
      `❌ FAILED: Expected only "${TEST_DOCUMENT_INGESTED}" in search results, but found ${searchResults.length} documents:\n` +
        `   - ${searchResults.join("\n   - ")}\n` +
        `   Unexpected documents: ${otherDocs.join(", ")}\n` +
        `   This indicates the unique token is not unique or there's an indexing issue.`,
    );
  }

  if (searchResults[0] !== TEST_DOCUMENT_INGESTED) {
    throw new Error(
      `❌ FAILED: Expected "${TEST_DOCUMENT_INGESTED}" but found "${searchResults[0]}"`,
    );
  }

  // Success!
  logger.info(
    `  ✅ SUCCESS: Only "${TEST_DOCUMENT_INGESTED}" found in search results`,
  );
  logger.info(`  ✓ Opensearch indexing verified for OpenAI\n`);

  // Assertions for Playwright reporting
  expect(searchResults.length).toBe(1);
  expect(searchResults[0]).toBe(TEST_DOCUMENT_INGESTED);
});
