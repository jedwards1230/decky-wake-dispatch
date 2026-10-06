# Releasing

Releases publish `wake-dispatch.zip` (built by `scripts/package.sh`) as the
asset of a GitHub Release. The zip contains a single `wake-dispatch/` folder
that Decky Loader can install directly.

The git tag `vX.Y.Z` is the source of truth for the version. CI never commits a
version bump; it stamps the tag's version into the packaged copy of
`package.json` only.

## Cutting a release

- **Labelled merge (normal path).** Add one of `semver:patch`, `semver:minor`
  or `semver:major` to a pull request before merging it into `main`. The
  `Release` workflow computes the next version from the latest tag, pushes the
  tag, builds the zip from it and publishes the release with generated notes.
  Pull requests without a `semver:*` label do not release.
- **Manual.** Run the `Release` workflow from `main` with an explicit version:

  ```bash
  gh workflow run release.yml --repo jedwards1230/decky-wake-dispatch --ref main -f version=0.1.0
  ```

  This tags the current `main` commit (or reuses an existing tag) and publishes
  with GitHub-generated notes. It needs no extra secrets. Every release is
  marked "latest", so only dispatch versions newer than the current latest.

If a release run fails, use **Re-run failed jobs** (not "Re-run all jobs",
which would cut another version), or dispatch the workflow with the version of
the tag that was already pushed.

## Optional secrets

| Secret | Used by | Without it |
|--------|---------|------------|
| `ANTHROPIC_API_KEY` | AI release notes; fallback credential for AI PR review | Release notes fall back to GitHub-generated notes |
| `CLAUDE_CODE_OAUTH_TOKEN` | AI PR review (preferred credential) | The `PR Review` workflow skips its review job |

## Packaging locally

```bash
scripts/package.sh                         # pnpm install + build, then zip
scripts/package.sh --no-build              # zip the existing dist/
PNPM="npx -y pnpm@9.15.9" scripts/package.sh --version 0.1.0
```

The zip is written to `out/wake-dispatch.zip`. The `package` CI job runs the
same script on every pull request and uploads the zip as a workflow artifact.
