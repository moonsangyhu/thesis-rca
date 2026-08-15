#!/usr/bin/env node

import { writeSync } from "node:fs";
import { pathToFileURL } from "node:url";

const SCHEMA_VERSION = 1;

function writeRecord(record) {
  writeSync(process.stdout.fd, `${JSON.stringify(record)}\n`);
}

function fail(message) {
  writeRecord({
    type: "thesis.sdk.error",
    schema_version: SCHEMA_VERSION,
    message: String(message).slice(0, 2000),
  });
  process.exitCode = 1;
}

const sdkIndex = process.argv[2];
if (!sdkIndex) {
  fail("missing SDK index path");
} else {
  let request;
  try {
    let input = "";
    process.stdin.setEncoding("utf8");
    for await (const chunk of process.stdin) {
      input += chunk;
    }
    request = JSON.parse(input);
  } catch (error) {
    fail(`invalid runner request: ${error}`);
  }

  if (request) {
    let client;
    let session;
    try {
      const { CopilotClient } = await import(pathToFileURL(sdkIndex).href);
      client = new CopilotClient({
        mode: "empty",
        baseDirectory: request.base_directory,
        workingDirectory: request.working_directory,
        logLevel: "error",
        useLoggedInUser: true,
      });
      session = await client.createSession({
        model: request.model,
        reasoningEffort: request.reasoning_effort,
        workingDirectory: request.working_directory,
        availableTools: [],
        excludedTools: [],
        tools: [],
        enableSkills: false,
        enableConfigDiscovery: false,
        skipCustomInstructions: true,
        mcpServers: {},
        customAgents: [],
        remoteSession: "off",
        streaming: false,
        maxOutputTokens: request.max_output_tokens,
        sessionLimits: { maxAiCredits: request.max_ai_credits },
        enableSessionTelemetry: false,
        skipEmbeddingRetrieval: true,
        embeddingCacheStorage: "in-memory",
        enableOnDemandInstructionDiscovery: false,
        enableFileHooks: false,
        enableHostGitOperations: false,
        enableSessionStore: false,
        memory: { enabled: false },
        systemMessage: { mode: "replace", content: request.system_prompt },
        onEvent: writeRecord,
      });
      writeRecord({
        type: "thesis.sdk.binding",
        schema_version: SCHEMA_VERSION,
        session_id: session.sessionId,
        mode: "empty",
        model: request.model,
        reasoning_effort: request.reasoning_effort,
        available_tools: [],
        excluded_tools: [],
        tools: [],
        enable_skills: false,
        enable_config_discovery: false,
        skip_custom_instructions: true,
        mcp_servers: [],
        custom_agents: [],
        remote_session: "off",
        max_output_tokens: request.max_output_tokens,
        max_ai_credits: request.max_ai_credits,
        request_nonce: request.request_nonce,
        system_prompt_sha256: request.system_prompt_sha256,
        user_prompt_sha256: request.user_prompt_sha256,
      });
      const response = await session.sendAndWait(
        { prompt: request.user_prompt },
        request.timeout_ms,
      );
      const metrics = await session.rpc.usage.getMetrics();
      writeRecord({
        type: "thesis.sdk.result",
        schema_version: SCHEMA_VERSION,
        session_id: session.sessionId,
        request_nonce: request.request_nonce,
        response: response?.data?.content,
        metrics,
      });
    } catch (error) {
      fail(error instanceof Error ? error.message : error);
    } finally {
      if (session) {
        try {
          await session.disconnect();
        } catch (error) {
          fail(`session disconnect failed: ${error}`);
        }
      }
      if (client) {
        try {
          const errors = await client.stop();
          if (errors.length) {
            fail(`client stop failed: ${errors.map((error) => error.message).join(" | ")}`);
          }
        } catch (error) {
          fail(`client stop failed: ${error}`);
        }
      }
    }
  }
}
