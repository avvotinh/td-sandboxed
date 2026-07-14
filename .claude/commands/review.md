Review all staged and unstaged changes in the current branch.

1. Run `git diff` to see all changes
2. For Python files: delegate to `python-reviewer` subagent
3. For Rust files: check error handling and unsafe blocks
4. For DB migrations: delegate to `database-reviewer` subagent
5. Run `security-reviewer` if changes touch credentials, network, or DB access

> Note: `quant-reviewer` (bắt lookahead bias/overfit) sẽ được thêm cho `src/kernel/**` ở phase sau (xem docs/v2/03-harness.md H2).

Provide a summary with severity ratings.
