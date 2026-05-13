Review all staged and unstaged changes in the current branch.

1. Run `git diff` to see all changes
2. For Python files: delegate to `python-reviewer` subagent
3. For Go files: delegate to `go-reviewer` subagent
4. For Rust files: check error handling and unsafe blocks
5. For DB migrations: delegate to `database-reviewer` subagent
6. Run `security-reviewer` if changes touch credentials, network, or DB access

Provide a summary with severity ratings.
