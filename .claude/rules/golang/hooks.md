---
paths:
  - "**/*.go"
  - "**/go.mod"
  - "**/go.sum"
---
# Go Hooks

> This file extends [common/hooks.md](../common/hooks.md) with Go specific content.

## PostToolUse Hooks

Configured in `.claude/settings.local.json`:

- **gofmt -w**: Auto-format `.go` files on save.
- **go vet ./...**: Run vet against the package of the edited file (first 10 lines of output).

Not currently enabled (add manually if desired):
- **goimports**: import ordering (gofmt handles basic formatting).
- **staticcheck**: extended static checks on modified packages.
