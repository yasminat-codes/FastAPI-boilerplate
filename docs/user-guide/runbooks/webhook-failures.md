# Runbook: Webhook Failures

This runbook covers failures in the template's webhook ingestion pipeline: signature verification failures, replay and duplicate storms, malformed or poison payloads, and processing backlogs.

For provider-specific outage and auth failure guidance, see the [Integration Runbooks](../integrations/runbooks.md).

## Symptoms

- Structured logs show `webhook_signature_failure`, `webhook_replay_rejected`, or `webhook_malformed_payload` events.
- The `{namespace}_webhook_signature_failures_total` metric is spiking.
- The `{namespace}_webhook_events_received_total{status="rejected"}` counter is climbing.
- The provider's webhook dashboard shows unacknowledged deliveries piling up.
- Sentry is reporting new exceptions from `src/app/webhooks/` modules.

## Signature Verification Failures

The template's ingestion pipeline runs provider-specific signature verification before accepting a delivery. Signature failures mean the raw request body and the expected HMAC do not match.

### Common Causes

1. **Rotated signing secret** — the provider rotated its webhook signing key, but the template is still using the old secret.
2. **Wrong secret for environment** — the sandbox signing secret is configured in production, or vice versa.
3. **Body mutation** — a reverse proxy, WAF, or middleware is modifying the request body before the webhook route reads it. Signature verification depends on byte-for-byte body fidelity.
4. **Spoofed deliveries** — someone is sending forged webhook payloads to your endpoint.

### Diagnosis

1. Check structured logs for the affected provider:
   ```
   webhook_signature_failure provider=stripe detail="HMAC mismatch"
   ```

2. Verify the signing secret is correct:
   - Log into the provider's dashboard and compare the signing secret with your environment variable.
   - Confirm you are using the correct environment (sandbox vs. production).
   - Print the first and last 4 characters of the configured secret to verify it loaded correctly.

3. Check whether a reverse proxy or CDN is rewriting the body:
   - The template's `build_webhook_ingestion_request(...)` dependency captures `request.body()` before any JSON parsing.
   - If you have a load balancer that decompresses or re-encodes the body, the signature will not match.
   - Test by sending a known-good webhook from the provider's test/retry UI and checking whether the raw body matches what the provider signed.

4. Check delivery source IPs:
   - If your endpoint is public, confirm the deliveries are coming from the provider's published IP ranges.
   - If you see deliveries from unknown IPs, treat them as spoofed.

### Resolution

1. **If the signing secret rotated**: update the environment variable with the new secret and restart the application.
2. **If the body is being mutated**: configure your reverse proxy to pass the webhook route's body through unmodified. Some providers document required proxy configurations.
3. **If deliveries are spoofed**: restrict the webhook endpoint to the provider's IP ranges using your load balancer or WAF, and discard the rejected deliveries.
4. **Replay missed deliveries**: once verification is working again, use the provider's dashboard to replay failed deliveries. The template's replay protection will deduplicate any that were already processed.

## Replay and Duplicate Storms

The template checks recent `webhook_event` rows for matching delivery IDs, event IDs, and payload fingerprints before persisting a new delivery. When replays are detected, the pipeline raises a typed replay error and returns a `200 OK` to the provider (so it stops retrying) without processing the event again.

### Common Causes

1. **Provider retry storm** — the provider is retrying deliveries that your endpoint already processed, because your response was too slow (above the provider's timeout threshold).
2. **Manual bulk replay** — someone triggered a bulk replay from the provider's dashboard.
3. **Duplicate event IDs** — the provider is sending the same logical event with different delivery IDs (some providers do this by design during catch-up).

### Diagnosis

1. Check structured logs:
   ```
   webhook_replay_rejected provider=stripe delivery_id=evt_123 reason="duplicate_delivery_id"
   webhook_replay_rejected provider=stripe delivery_id=evt_456 reason="fingerprint_match"
   ```

2. Check how long your webhook handler takes to respond:
   - The template's acknowledgement strategy returns `202 Accepted` before heavy processing.
   - If your handler does inline work before returning, the provider may time out and retry.
   - Look at `{namespace}_webhook_processing_duration_seconds` to see if processing time is high.

3. Check the provider's webhook delivery log for retry patterns.

### Resolution

1. **If the provider is retrying because your endpoint is slow**: confirm that your webhook route is using `ingest_webhook_event(...)` with an async enqueuer, so the response returns immediately and processing happens in a background job.
2. **If someone triggered a manual replay**: no action needed. The template's replay protection is working correctly by deduplicating.
3. **If the volume is overwhelming**: temporarily increase the replay window setting (`WEBHOOK_REPLAY_WINDOW_SECONDS`) to catch more duplicates, or add provider-specific rate limiting on your webhook endpoint.

## Malformed and Poison Payloads

The template classifies payloads that fail validation into three categories: malformed (unparseable), unknown event type (valid JSON but unrecognized `event_type`), and poison (repeatedly fails processing after multiple retries).

### Diagnosis

1. Check structured logs:
   ```
   webhook_malformed_payload provider=stripe detail="invalid JSON"
   webhook_unknown_event_type provider=stripe event_type="invoice.finalized_v2"
   webhook_poison_detected provider=stripe delivery_id=evt_789 attempts=5
   ```

2. For malformed payloads:
   - Check if the provider changed their payload format.
   - Check if the `Content-Type` header matches what the provider sends (typically `application/json`).
   - Look at the raw payload in the `webhook_event` table's `raw_payload` column.

3. For unknown event types:
   - Check if the provider added a new event type that your adapter's event registry does not include.
   - Review your `WebhookEventTypeRegistry` configuration.

4. For poison payloads:
   - The payload passes validation but consistently causes processing failures.
   - Check the dead-letter table for the failing job's error details.

### Resolution

1. **Malformed payloads**: if the provider changed their format, update your normalizer. If the payloads are genuinely invalid, report them to the provider.
2. **Unknown event types**: add the new event type to your provider adapter's event registry, or configure the registry to ignore unrecognized types (the template logs and acknowledges them by default).
3. **Poison payloads**: inspect the dead-letter record for the root cause. Fix the processing logic, then replay the dead-lettered job.

## Processing Backlog

Webhook events are being accepted and persisted, but the background jobs that process them are falling behind.

### Diagnosis

1. Check the `{namespace}_job_queue_size` metric for growth.
2. Query the `webhook_event` table for events stuck in `acknowledged` or `enqueued` state:
   ```sql
   SELECT provider, status, COUNT(*)
   FROM webhook_event
   WHERE created_at > NOW() - INTERVAL '1 hour'
   GROUP BY provider, status
   ORDER BY COUNT(*) DESC;
   ```

3. Check worker health:
   - Are workers running? Check `/api/v1/internal/health` for worker heartbeat visibility.
   - Are workers processing jobs at all, or are they stuck?
   - Check `{namespace}_jobs_in_progress` to see if jobs are running but slow.

### Resolution

1. **Scale workers**: increase the number of worker processes or pods dedicated to the webhook queue.
2. **Check for slow processing**: if individual webhook processing jobs are taking too long, profile the handler logic and optimize.
3. **Separate webhook queue**: if webhook processing is competing with other background jobs, use a dedicated queue namespace (see [Queue Naming](../background-tasks/index.md)).
4. **Throttle the provider**: if the provider supports delivery rate configuration, reduce it temporarily.

## Prevention

1. **Always use the template's acknowledgement strategy**: return `202 Accepted` immediately and process in a background job.
2. **Monitor signature failure metrics**: a small number of signature failures is normal (provider test events, stale retries). A sudden spike is not.
3. **Keep signing secrets current**: add credential rotation to your deployment checklist. See the [Secret Rotation](secret-rotation.md) runbook.
4. **Test with provider replay tools**: periodically replay a known event to confirm the full pipeline works end to end.
5. **Set up alerting**: use the webhook alerts from the [alerting guide](index.md#webhook-alerts) to catch problems early.

## Further Reading

- [Webhooks Overview](../webhooks/index.md) — template webhook architecture.
- [Adding a Provider](../webhooks/adding-provider.md) — how to add a new webhook provider adapter.
- [Queue Backlog Incidents](queue-backlog.md) — when webhook processing jobs pile up.
- [Integration Runbooks](../integrations/runbooks.md) — provider-specific operational guidance.
