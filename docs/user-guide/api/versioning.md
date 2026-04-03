# API Versioning

The template now treats versioning as a first-class router concern instead of a loose folder convention.

## Current Structure

Versioning is defined by:

- `ApiVersion`
- `SUPPORTED_API_VERSIONS`
- `build_version_router(...)`
- `build_api_router(...)`

The default runtime currently mounts:

```text
/api/v1
```

through `src/app/api/__init__.py` and `src/app/api/v1/__init__.py`.

## Adding A New Version

When a cloned project needs a breaking API change:

1. Add a new version package such as `src/app/api/v2/`.
2. Create a `build_v2_router(...)` function in that package.
3. Register the new builder in the API version registry.
4. Add `ApiVersion.V2` to the supported versions tuple.
5. Keep the old version stable for existing clients.

The high-level shape should stay the same:

```text
src/app/api/
├── __init__.py
├── routing.py
├── v1/
└── v2/
```

## Route Groups Inside A Version

Every version should reserve the same route groups:

- public
- ops
- admin
- internal
- webhooks

That keeps a future `v2` predictable even if the actual endpoints diverge from `v1`.

## Non-Breaking Vs Breaking Changes

Keep changes inside the current version when they are additive, such as:

- new optional request fields
- new optional response fields
- new endpoints
- new filters or sort options that do not alter existing defaults

Create a new version when a change would break existing clients, such as:

- removing or renaming fields
- changing the top-level response shape
- changing required authentication or authorization posture for an existing endpoint
- changing path structure in a way that invalidates client URLs

## Recommendation

Treat `v1` as the stable template baseline and add new versions sparingly. The template should optimize for a strong default versioning pattern, not for keeping multiple half-maintained API versions alive without a clear need.
