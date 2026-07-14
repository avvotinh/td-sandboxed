Run the full test suite across all services and report results.

$ARGUMENTS can be:
- (empty) — run all tests
- `trading-engine` — only Python tests
- `mt5-bridge` — only Rust tests

If argument is provided:
```bash
cd /home/hopdev/Dev/Sandboxed && make test-$ARGUMENTS
```

If no argument:
```bash
cd /home/hopdev/Dev/Sandboxed && make test
```

Analyze any failures and suggest fixes.
