# API Exception Handling

The application factory now registers a canonical exception-to-response mapper for the API layer. That means routers and services can raise reusable exceptions while clients still receive one stable error shape.

## Error Payload Shape

Handled errors return `ApiErrorResponse`:

```json
{
  "error": {
    "code": "not_found",
    "message": "User not found"
  }
}
```

Validation failures include a `details` array:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request validation failed.",
    "details": [
      {
        "loc": ["body", "name"],
        "msg": "Field required",
        "type": "missing"
      }
    ]
  }
}
```

## What To Raise

Prefer the canonical platform exception surface:

```python
from src.app.platform.exceptions import (
    BadRequestException,
    DuplicateValueException,
    ForbiddenException,
    NotFoundException,
    UnauthorizedException,
)
```

Example:

```python
from src.app.platform.exceptions import NotFoundException


async def get_user_or_raise(username: str, db: AsyncSession) -> dict:
    user = await user_service.get_user(username=username, db=db)
    if user is None:
        raise NotFoundException("User not found")
    return user
```

## Automatic Mapping

`create_application(...)` wires the handlers from `src/app/api/errors.py` automatically, so the template now normalizes:

- platform `CustomException` subclasses such as `NotFoundException`
- regular FastAPI `HTTPException`
- `RequestValidationError`
- unhandled exceptions

## Error Codes

The template currently maps common cases to machine-readable codes such as:

- `bad_request`
- `unauthorized`
- `forbidden`
- `not_found`
- `conflict`
- `payload_too_large`
- `validation_error`
- `rate_limited`
- `request_timeout`
- `internal_server_error`

Custom exception class names are converted into snake_case codes where possible, which keeps the transport contract predictable without forcing every router to handcraft error payloads.

## Guidance

- Raise reusable exceptions from services when the failure is part of normal control flow.
- Let the application-level handlers format the response.
- Avoid returning raw `{"detail": ...}` payloads manually from route handlers unless a cloned project has a very specific compatibility reason.
- Do not leak raw stack traces or secret values in error responses.
