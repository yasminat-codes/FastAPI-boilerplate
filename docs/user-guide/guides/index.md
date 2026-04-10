# Extension Guides

This section contains hands-on guides for extending the template with common customization patterns. Each guide walks through a complete, self-contained example so you can understand the full lifecycle of adding a feature.

## Overview

The template provides several extension points for building production-grade capabilities:

- **Background Jobs** — Asynchronous work units that are durable, retryable, and monitorable
- **Workflows** — Multi-step orchestrations with built-in retry, compensation, and status tracking
- **Client Integrations** — Provider adapters that standardize HTTP communication, error handling, and credentials
- **Webhooks** — Ingestion and normalization of events from external systems

## Guides

### [Adding a Background Job](adding-background-job.md)

Learn how to create a durable background job by subclassing `WorkerJob`. Covers:
- Implementing the `run()` method
- Using `JobEnvelope` for structured payloads
- Registering jobs for the worker
- Customizing retry, timeout, and alert behavior
- Enqueueing from routes or other jobs

**Time:** 5-10 minutes | **Difficulty:** Beginner

### [Adding a Workflow](adding-workflow.md)

Build a multi-step orchestration with durable state, retries, and compensation. Covers:
- Defining workflow steps with the `WorkflowStep` protocol
- Creating a `WorkflowDefinition` with ordered steps
- Registering and starting workflows
- Handling step failures and branching
- Implementing compensation steps for distributed transactions

**Time:** 10-15 minutes | **Difficulty:** Intermediate

### [Adding a Client Integration](adding-integration.md)

Create a reusable adapter for third-party API providers. Covers:
- Subclassing `BaseIntegrationClient` or implementing `IntegrationClient`
- Using the shared `TemplateHttpClient` for HTTP calls
- Managing credentials with `IntegrationSettings`
- Standardizing responses with `IntegrationResult`
- Error handling and sandbox/production modes

**Time:** 10-15 minutes | **Difficulty:** Intermediate

### [Adding a Webhook Provider](../webhooks/adding-provider.md)

Ingest and normalize events from external services. This guide covers the full webhook pipeline from signature verification to event dispatch.

**Time:** 10-15 minutes | **Difficulty:** Intermediate

## Getting Started

Pick the guide that matches your use case. Each includes:

- A complete working example with real class and file names
- Copy-paste-ready code snippets
- Common patterns and best practices
- Pointers to template infrastructure for testing and monitoring

All guides assume you have the template running locally and understand basic FastAPI and async Python patterns.

## Architecture Reference

For deeper context on how these pieces fit together, see:

- [Background Tasks](../background-tasks/index.md) — Worker infrastructure and queue management
- [Integration Contracts](../integrations/contracts.md) — Credential handling and HTTP transport
- [Database Models](../database/models.md) — Persistence layer for workflows and webhook events
