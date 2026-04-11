# Versioning and Release Guidance

This template follows semantic versioning and maintains a structured release process to ensure clarity about changes and compatibility across versions.

## Semantic Versioning

The template uses semantic versioning with the format `MAJOR.MINOR.PATCH`:

- **MAJOR** — Breaking changes to template contracts or critical infrastructure. Bumped when existing integration patterns, configuration structure, or deployment topology changes in incompatible ways. Users upgrading to a new major version will need to review and adapt their implementations.

- **MINOR** — New features, extension points, or non-breaking enhancements. Bumped when new capabilities are added without breaking existing functionality. Users can safely adopt new versions for additional features.

- **PATCH** — Bug fixes, documentation updates, and maintenance changes. Bumped for corrections and improvements that don't introduce new functionality. Safe to adopt for maintenance and stability improvements.

## Version Location

The template version is defined in `pyproject.toml` under the `[project]` section:

```toml
[project]
name = "fastapi-template"
version = "0.1.0"
```

Update this file when preparing a release.

## Release Process

Follow these steps to cut a new release:

### 1. Update Version

Edit `pyproject.toml` and bump the version number according to semantic versioning rules.

### 2. Update Changelog

Move all entries from the `[Unreleased]` section in `CHANGELOG.md` to a new section with the version number and date:

```markdown
## [X.Y.Z] - YYYY-MM-DD

### Added
- Feature 1
- Feature 2

### Fixed
- Bug fix 1
```

Keep the `[Unreleased]` section at the top for future changes.

### 3. Tag Release

Create a git tag with the version prefixed by `v`:

```bash
git tag -a v0.2.0 -m "Release version 0.2.0"
git push origin v0.2.0
```

### 4. Create GitHub Release

On GitHub, create a new release from the tag. Use the version as the title (e.g., "0.2.0") and paste the relevant section from `CHANGELOG.md` as the release body.

## Changelog Maintenance

Keep the changelog updated as development progresses:

- **During development** — Every pull request should include updates to the `[Unreleased]` section of `CHANGELOG.md`, categorized appropriately (Added, Fixed, Changed, Deprecated, etc.).

- **At release time** — The release maintainer moves all `[Unreleased]` entries to a versioned section with the release date.

This approach ensures the changelog is always current and ready for release without last-minute scrambling.

## Guidelines for Entries

Changelog entries should be concise and action-oriented:

- Use past tense ("Added JWT token refresh", not "Add JWT token refresh")
- Keep each entry to one line when possible
- Focus on user-facing changes and significant internal improvements
- Group by category: Added, Changed, Fixed, Removed, Deprecated

## GitHub Releases

GitHub Releases serve as the public-facing changelog. Create a release for each version:

1. Click "Releases" on the repository main page
2. Click "Create a new release"
3. Select the appropriate tag (e.g., `v0.2.0`)
4. Use the version as the title
5. Paste the changelog section for that version as the body
6. Publish the release

This makes version history easily discoverable and provides a convenient download point for each release version.
