# Resilience and Fallback Patterns

The template provides reusable patterns for handling external integration failures gracefully. When a third-party provider becomes unavailable or degrades, these patterns let you continue serving users with degraded functionality, deferred processing, or fallback data instead of returning hard errors.

## Fallback Behavior

When a provider is temporarily unavailable, fallback patterns let you use cached or stale data instead of failing the entire operation.

### When to Use Fallback

Fallback is appropriate for read operations where stale data is acceptable:

- Cached user profiles
- Historical transaction lists
- Configuration data that changes infrequently
- Display-only information (not critical for workflow)

**Do not use fallback** for operations that require fresh or authoritative data:

- Payment processing (use deferred retry instead)
- Permission checks
- Real-time status checks
- Operations that depend on recent data

### The FallbackProvider Protocol

Implement this protocol to provide fallback data when a primary provider fails:

```python
from typing import Protocol, TypeVar

T = TypeVar('T')

class FallbackProvider(Protocol[T]):
    """Provides fallback data when primary provider is unavailable."""
    
    async def get_fallback(self, key: str) -> T | None:
        """Return cached or degraded-mode data, or None if unavailable."""
        ...
```

### Using with_fallback()

The `with_fallback()` helper lets you define primary and fallback paths:

```python
from src.app.integrations import IntegrationResult, classify_http_error
from src.app.integrations.http_client import HttpClientError
from datetime import datetime

class UserCacheProvider:
    """Simple fallback provider backed by in-memory cache."""
    
    def __init__(self):
        self._cache = {}
    
    async def get_fallback(self, user_id: str) -> dict | None:
        cached = self._cache.get(user_id)
        if cached:
            return {
                **cached,
                '_from_cache': True,
                '_cached_at': cached.get('_cached_at'),
            }
        return None

# Pseudocode for with_fallback pattern
async def get_user(user_id: str, fallback_provider: FallbackProvider) -> IntegrationResult:
    """Get user from primary provider with fallback to cache."""
    try:
        response = await primary_client.get(f"/users/{user_id}")
        user_data = response.json()
        # Cache for future fallback
        fallback_provider._cache[user_id] = {
            **user_data,
            '_cached_at': datetime.now().isoformat(),
        }
        return IntegrationResult.ok(
            data=user_data,
            provider="stripe",
            operation="get_user"
        )
    except HttpClientError as exc:
        # Primary failed; try fallback
        fallback_data = await fallback_provider.get_fallback(user_id)
        if fallback_data:
            return IntegrationResult.ok(
                data=fallback_data,
                provider="stripe",
                operation="get_user",
                degraded=True,  # Mark as degraded mode
            )
        # No fallback available
        error = classify_http_error("stripe", "get_user", exc)
        return IntegrationResult.fail(error=error)
```

The `IntegrationResult` object tracks whether the data came from a successful call or degraded mode via the `degraded` flag. Check `result.degraded` in your handler to decide how to present the data to the user.

### Implementing a Cache-Based Fallback Provider

Here's a practical example using a local cache:

```python
from datetime import datetime, timedelta

class LocalCacheFallback:
    """In-memory cache for fallback data."""
    
    def __init__(self, ttl_hours: int = 24):
        self._cache = {}
        self._ttl = timedelta(hours=ttl_hours)
    
    def cache_put(self, key: str, value: dict) -> None:
        """Store value in cache with timestamp."""
        self._cache[key] = {
            'data': value,
            'cached_at': datetime.now(),
        }
    
    async def get_fallback(self, key: str) -> dict | None:
        """Return cached data if not expired."""
        entry = self._cache.get(key)
        if not entry:
            return None
        
        age = datetime.now() - entry['cached_at']
        if age > self._ttl:
            del self._cache[key]  # Evict expired
            return None
        
        return {
            **entry['data'],
            '_stale': age > self._ttl / 2,
        }

# Usage in client
class StripeClientWithFallback:
    def __init__(self):
        self.cache = LocalCacheFallback(ttl_hours=24)
    
    async def get_customer(self, customer_id: str) -> IntegrationResult:
        try:
            response = await self._http_client.get(f"/v1/customers/{customer_id}")
            data = response.json()
            self.cache.cache_put(f"customer:{customer_id}", data)
            return IntegrationResult.ok(data=data, provider="stripe")
        except HttpClientError as exc:
            fallback = await self.cache.get_fallback(f"customer:{customer_id}")
            if fallback:
                return IntegrationResult.ok(data=fallback, provider="stripe", degraded=True)
            error = classify_http_error("stripe", "get_customer", exc)
            return IntegrationResult.fail(error=error)
```

## Partial Failure Handling

For bulk operations where some items may succeed and others fail, partial failure patterns let you salvage partial results instead of failing the entire batch.

### When to Use Partial Failure

Use when operating on collections of independent items:

- Syncing 100 user records from an external system (80 succeed, 20 fail)
- Batch creating resources (some valid, some with validation errors)
- Bulk updates where items are independent
- Importing CSV data with occasional bad rows

**Do not use partial failure** for strictly ordered or dependent operations where one failure invalidates the rest.

### The PartialFailurePolicy

Define your tolerance for failures in a batch:

```python
from dataclasses import dataclass

@dataclass
class PartialFailurePolicy:
    """Control how partial failures are handled in batch operations."""
    
    # Maximum ratio of items that can fail (0.0-1.0)
    # Example: 0.1 = allow up to 10% failure rate
    max_failure_ratio: float = 0.1
    
    # If True, stop processing on first auth error
    # Auth errors indicate misconfiguration, not transient failures
    fail_fast_on_auth: bool = True
    
    # If True, retry failed items before returning result
    retry_failed: bool = True
    
    # Maximum attempts per item
    max_attempts: int = 3
```

### Using execute_with_partial_failure()

Process a batch of items with configurable failure tolerance:

```python
from typing import Callable

class PartialFailureResult:
    """Result of a batch operation with partial failures."""
    
    succeeded: list[dict]  # Items that succeeded
    failed: list[tuple[dict, Exception]]  # Items that failed with reasons
    skipped: list[dict]  # Items skipped (e.g., auth errors with fail_fast=True)
    
    @property
    def partial_success(self) -> bool:
        """True if at least some items succeeded."""
        return len(self.succeeded) > 0
    
    @property
    def failure_ratio(self) -> float:
        """Ratio of failed to total items."""
        total = len(self.succeeded) + len(self.failed) + len(self.skipped)
        return (len(self.failed) + len(self.skipped)) / total if total > 0 else 0.0

# Example: Batch create customers in Stripe
async def batch_create_customers(
    customers: list[dict],
    policy: PartialFailurePolicy,
) -> PartialFailureResult:
    """Create multiple customers, tolerating some failures."""
    
    succeeded = []
    failed = []
    
    for customer in customers:
        try:
            response = await stripe_client.post(
                "/v1/customers",
                json=customer,
            )
            succeeded.append(response.json())
        except IntegrationAuthError:
            if policy.fail_fast_on_auth:
                raise  # Abort entire batch on auth failure
            failed.append((customer, exc))
        except IntegrationError as exc:
            if policy.retry_failed:
                # Could defer to job queue here
                pass
            failed.append((customer, exc))
    
    result = PartialFailureResult(
        succeeded=succeeded,
        failed=failed,
        skipped=[],
    )
    
    if result.failure_ratio > policy.max_failure_ratio:
        raise PartialFailureExceeded(
            f"Failure rate {result.failure_ratio:.0%} exceeds policy max "
            f"{policy.max_failure_ratio:.0%}",
            result=result,
        )
    
    return result
```

### Handling PartialFailureResult

Inspect the result to decide next steps:

```python
policy = PartialFailurePolicy(max_failure_ratio=0.15, fail_fast_on_auth=True)

try:
    result = await batch_create_customers(customer_list, policy)
    
    # Log success metrics
    logger.info(
        "Batch customer creation",
        succeeded=len(result.succeeded),
        failed=len(result.failed),
        failure_ratio=f"{result.failure_ratio:.0%}",
    )
    
    # Retry failed items with exponential backoff
    if result.failed:
        failed_customers = [item for item, _ in result.failed]
        await schedule_batch_retry(
            failed_customers,
            delay_seconds=60,
            max_attempts=3,
        )
    
    # Store successful creates in database
    for customer_data in result.succeeded:
        await db.customers.create(**customer_data)
        
except PartialFailureExceeded as exc:
    # Failure rate exceeded policy
    logger.error(
        "Batch exceeded failure tolerance",
        failure_ratio=f"{exc.result.failure_ratio:.0%}",
        policy_max=f"{policy.max_failure_ratio:.0%}",
    )
    # Decide whether to abort, retry, or escalate
```

## Compensating Actions

When a multi-step integration workflow partially fails, compensating actions provide cleanup and rollback. For example, if you create a Stripe customer but fail to store it in the database, compensation can delete the orphaned Stripe customer.

### When to Use Compensation

Use when you have:

- Multi-step workflows (create in A, configure in B, persist in C)
- Partial failures that leave external state inconsistent
- Need for automated rollback without manual cleanup

**Do not use compensation** as a substitute for proper error handling in a single step.

### The CompensatingAction Protocol

Define cleanup actions:

```python
from typing import Protocol, Any

class CompensatingAction(Protocol):
    """Automatic cleanup action registered during a workflow."""
    
    async def execute(self) -> None:
        """Perform the compensating action (e.g., delete what was created)."""
        ...
```

### Using CompensationContext

Register and execute compensations in reverse order:

```python
from contextlib import asynccontextmanager

class CompensationContext:
    """Manage a stack of compensating actions."""
    
    def __init__(self):
        self._actions: list[CompensatingAction] = []
    
    def register(self, action: CompensatingAction) -> None:
        """Register an action to be compensated in reverse order."""
        self._actions.append(action)
    
    async def compensate_all(self) -> None:
        """Execute all registered actions in reverse order."""
        for action in reversed(self._actions):
            try:
                await action.execute()
            except Exception as exc:
                logger.exception("Compensation action failed", action=action, exc=exc)

@asynccontextmanager
async def compensation_scope():
    """Context manager for compensation."""
    ctx = CompensationContext()
    try:
        yield ctx
    except Exception:
        await ctx.compensate_all()
        raise
```

### Full Example: Multi-Step Workflow with Compensation

Create a Stripe customer, add a payment method, and store in database. If any step fails, roll back the previous steps:

```python
async def create_customer_with_payment(
    customer_data: dict,
    payment_token: str,
) -> dict:
    """Create customer in Stripe, add payment method, and persist."""
    
    async with compensation_scope() as comp:
        # Step 1: Create Stripe customer
        stripe_response = await stripe_client.post("/v1/customers", json=customer_data)
        stripe_customer = stripe_response.json()
        customer_id = stripe_customer['id']
        
        # Register compensation: delete Stripe customer if later steps fail
        comp.register(DeleteStripeCustomer(client=stripe_client, customer_id=customer_id))
        
        # Step 2: Add payment method to customer
        payment_response = await stripe_client.post(
            f"/v1/customers/{customer_id}/sources",
            json={'source': payment_token},
        )
        payment_method = payment_response.json()
        
        # Register compensation: delete payment method if database write fails
        comp.register(DeletePaymentMethod(
            client=stripe_client,
            customer_id=customer_id,
            payment_id=payment_method['id'],
        ))
        
        # Step 3: Persist to database
        await db.customers.create(
            external_id=customer_id,
            data=stripe_customer,
            payment_method_id=payment_method['id'],
        )
        
        return {'customer_id': customer_id, 'payment_id': payment_method['id']}
```

Define the compensation actions:

```python
class DeleteStripeCustomer:
    def __init__(self, client, customer_id: str):
        self.client = client
        self.customer_id = customer_id
    
    async def execute(self) -> None:
        await self.client.delete(f"/v1/customers/{self.customer_id}")

class DeletePaymentMethod:
    def __init__(self, client, customer_id: str, payment_id: str):
        self.client = client
        self.customer_id = customer_id
        self.payment_id = payment_id
    
    async def execute(self) -> None:
        await self.client.delete(
            f"/v1/customers/{self.customer_id}/sources/{self.payment_id}"
        )
```

## Deferred Retries

When inline retries are exhausted, deferred retry patterns push failed calls to a background job queue for later retry. This unblocks the user-facing request while maintaining reliability.

### When to Defer

Use deferred retries when:

- Inline retries have been exhausted
- The failure is retryable (not auth or validation errors)
- You have a job queue (ARQ, Celery, etc.)
- The operation can be retried asynchronously

Do not defer:

- Auth failures (credentials are invalid, won't change)
- Validation errors (data won't suddenly be valid)
- Non-retryable business errors

### Decision Logic: should_defer_retry()

Determine whether to defer a failed request:

```python
def should_defer_retry(error: IntegrationError, attempts: int, max_attempts: int) -> bool:
    """Decide whether to defer a failed request to background queue."""
    
    # Only retry retryable errors
    if not is_retryable_integration_error(error):
        return False
    
    # Only defer if we've exhausted inline attempts
    if attempts < max_attempts:
        return False
    
    return True

# Usage
try:
    result = await integration_client.some_operation()
except IntegrationError as exc:
    if should_defer_retry(exc, attempts=3, max_attempts=3):
        # Queue for background retry
        await defer_to_background_queue(exc)
    else:
        # Hard failure; don't retry
        raise
```

### Building Retry Requests

Structure deferred retries for the background queue:

```python
from dataclasses import dataclass, asdict
from datetime import datetime

@dataclass
class DeferredRetryRequest:
    """Request to retry a failed integration call in background."""
    
    # Original call context
    provider: str
    operation: str
    request_data: dict | None  # Original request payload
    
    # Retry context
    attempt_number: int
    max_attempts: int = 3
    error_class: str  # Original error type for logging
    error_detail: str  # Original error message
    
    # Backoff calculation
    first_failure_at: str  # ISO timestamp
    deferred_at: str  # ISO timestamp
    
    # User/correlation context
    correlation_id: str
    
    def to_job_kwargs(self) -> dict:
        """Convert to background job arguments."""
        return asdict(self)

def build_deferred_retry_request(
    error: IntegrationError,
    provider: str,
    operation: str,
    original_request: dict | None,
    attempt_number: int,
    correlation_id: str,
) -> DeferredRetryRequest:
    """Create a deferred retry request."""
    return DeferredRetryRequest(
        provider=provider,
        operation=operation,
        request_data=original_request,
        attempt_number=attempt_number,
        error_class=error.__class__.__name__,
        error_detail=str(error),
        first_failure_at=datetime.now().isoformat(),
        deferred_at=datetime.now().isoformat(),
        correlation_id=correlation_id,
    )
```

### Implementing a DeferredRetryEnqueuer

If you use ARQ for background jobs, implement the enqueuer:

```python
from arq import create_pool
from src.app.core.worker import settings as worker_settings

class ARQDeferredRetryEnqueuer:
    """Enqueue deferred retries to ARQ."""
    
    def __init__(self, arq_settings=None):
        self.settings = arq_settings or worker_settings
    
    async def enqueue_retry(self, retry_request: DeferredRetryRequest) -> str:
        """Queue a retry request; return job ID."""
        pool = await create_pool(
            min_connections=1,
            max_connections=5,
            host=self.settings.redis_host,
            port=self.settings.redis_port,
        )
        
        # Calculate backoff delay
        delay_seconds = min(
            2 ** (retry_request.attempt_number - 1),  # Exponential: 1, 2, 4, 8...
            300,  # Cap at 5 minutes
        )
        
        job = await pool.enqueue_job(
            'integration_retry_handler',
            retry_request.to_job_kwargs(),
            _defer_until=delay_seconds,
        )
        
        logger.info(
            "Deferred retry enqueued",
            job_id=job.job_id,
            provider=retry_request.provider,
            operation=retry_request.operation,
            attempt=retry_request.attempt_number,
            defer_seconds=delay_seconds,
        )
        
        return job.job_id

# In your worker module (e.g., src/app/core/worker/jobs.py)
async def integration_retry_handler(
    provider: str,
    operation: str,
    request_data: dict | None,
    attempt_number: int,
    max_attempts: int,
    error_class: str,
    **kwargs
) -> dict:
    """Background job handler for deferred retries."""
    
    logger.info(
        "Executing deferred retry",
        provider=provider,
        operation=operation,
        attempt=attempt_number,
    )
    
    # Get the integration client for this provider
    client = get_integration_client(provider)
    
    try:
        # Re-execute the operation with fresh attempt count
        result = await client.execute_operation(operation, request_data)
        logger.info("Deferred retry succeeded", provider=provider, operation=operation)
        return {'status': 'success', 'result': result}
    except IntegrationError as exc:
        if attempt_number < max_attempts:
            # Recursively defer again
            retry_req = build_deferred_retry_request(
                exc,
                provider=provider,
                operation=operation,
                original_request=request_data,
                attempt_number=attempt_number + 1,
                correlation_id=kwargs.get('correlation_id', 'unknown'),
            )
            enqueuer = ARQDeferredRetryEnqueuer()
            job_id = await enqueuer.enqueue_retry(retry_req)
            return {'status': 'deferred', 'job_id': job_id}
        else:
            # Max attempts exhausted
            logger.error(
                "Deferred retry exhausted",
                provider=provider,
                operation=operation,
                max_attempts=max_attempts,
                final_error=str(exc),
            )
            return {'status': 'failed', 'error': str(exc)}
```

## Decision Guide

Use this table to pick the right resilience pattern for your failure scenario:

| Failure type | Pattern | When to use |
|---|---|---|
| Provider temporarily down | Fallback | Read-only operations where stale data is acceptable; display information |
| Some items in batch fail | Partial failure | Bulk syncs, batch imports, bulk API calls where items are independent |
| Multi-step workflow fails partially | Compensation | Create-then-configure flows; operations with side effects that need rollback |
| Inline retries exhausted | Deferred retry | Any retryable failure (timeout, 5xx, rate limit) when inline retries don't work |

## Further Reading

- [Integration Contracts](contracts.md) — Full contract layer for building adapters
- [Runbooks](runbooks.md) — Operational guidance for degraded providers
