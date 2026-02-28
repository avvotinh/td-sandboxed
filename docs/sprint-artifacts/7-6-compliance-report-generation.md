# Story 7.6: Compliance Report Generation

Status: done

## Story

As a **trader**,
I want **to generate compliance reports for my prop firm accounts**,
So that **I can verify my challenge progress and have records for compliance verification**.

## Acceptance Criteria

1. **Given** I run `trading-engine report --account ftmo-gold-001 --format pdf`
   **When** the report generates
   **Then** I receive a PDF file containing:
   - Account summary header (account ID, report period, generation date)
   - Balance overview (opening, closing, peak, current drawdown)
   - Daily P&L line chart showing balance progression over the reporting period
   - Trading days count (days with at least 1 trade) vs calendar days
   - Rule violation summary table (count by rule type, severity breakdown)
   - Trade history table (date, symbol, side, size, entry, exit, P&L)
   - Footer with generation timestamp and system version

2. **Given** I run `trading-engine report --account ftmo-gold-001 --format json`
   **When** the report generates
   **Then** I receive structured JSON output with all report sections as nested objects (financial values as strings for precision)

3. **Given** I run `trading-engine report --account ftmo-gold-001 --compare-dashboard`
   **When** the command executes
   **Then** it shows metrics to compare with prop firm dashboard:
   ```
   FTMO Dashboard Comparison for ftmo-gold-001
   =============================================
   Metric              System Value    FTMO Dashboard (enter manually)
   Daily Loss          -1.5%           [___]
   Max Drawdown        3.2%            [___]
   Trading Days        6               [___]
   Profit Target       4.8%            [___]
   Total Trades        45              [___]
   Win Rate            62.2%           [___]
   ```

4. **Given** I run `trading-engine report --account ftmo-gold-001 --format csv`
   **When** the report generates
   **Then** CSV files are written for each section (trades, violations, snapshots) with appropriate filenames

5. **Given** I run `trading-engine report --account ftmo-gold-001 --days 30`
   **When** the report generates
   **Then** only the last 30 days of data are included (default: all available data)

6. **Given** DATABASE_URL is not set
   **When** I run any report command
   **Then** I see a clear error: "Database connection required. Set DATABASE_URL environment variable."

## Tasks / Subtasks

**Task Dependency Order:**
```
Task 1 (Add reportlab dependency) → Task 2 (Create reports module) → Task 3 (Data gathering) → Task 4 (PDF generator) → Task 5 (JSON/CSV output) → Task 6 (Dashboard comparison) → Task 7 (CLI command) → Task 8 (Tests)
```

- [x] Task 1: Add reportlab dependency (AC: #1)
  - [x] 1.1: Add `reportlab>=4.0` to `services/trading-engine/pyproject.toml` under `[project]` dependencies
  - [x] 1.2: Install with `uv pip install reportlab>=4.0`
  - [x] 1.3: Verify import works: `uv run python -c "from reportlab.platypus import SimpleDocTemplate; print('OK')"`

- [x] Task 2: Create reports module structure (AC: #1-4)
  - [x] 2.1: Create `services/trading-engine/src/reports/__init__.py` with exports for `ComplianceReportGenerator` and `ReportData`
  - [x] 2.2: Create `services/trading-engine/src/reports/data_gatherer.py` with `ReportDataGatherer` class
  - [x] 2.3: Create `services/trading-engine/src/reports/compliance_report.py` with `ComplianceReportGenerator` class
  - [x] 2.4: Create `services/trading-engine/src/reports/models.py` with `ReportData` dataclass to hold all gathered data

- [x] Task 3: Implement report data gathering (AC: #1-5)
  - [x] 3.1: Create `ReportData` dataclass in `models.py`:
    - Fields: `account_id: str`, `period_start: date`, `period_end: date`, `generated_at: datetime`
    - Fields: `trades: list[TradeRecord]`, `violations: list[RuleViolationModel]`, `snapshots: list[AccountSnapshotModel]`
    - Fields: `summary: ReportSummary` (nested dataclass with computed metrics)
  - [x] 3.2: Create `ReportSummary` dataclass:
    - Fields: `total_trades: int`, `winning_trades: int`, `losing_trades: int`, `win_rate: Decimal`
    - Fields: `net_pnl: Decimal`, `best_day_pnl: Decimal`, `worst_day_pnl: Decimal`
    - Fields: `trading_days: int`, `calendar_days: int`
    - Fields: `opening_balance: Decimal`, `closing_balance: Decimal`, `peak_balance: Decimal`
    - Fields: `max_drawdown_percent: Decimal`, `current_drawdown_percent: Decimal`
    - Fields: `total_violations: int`, `blocked_count: int`, `violations_by_rule: dict[str, int]`
  - [x] 3.3: Implement `ReportDataGatherer.gather()` async method:
    - Accept `session: AsyncSession`, `account_id: str`, `since: date | None`, `until: date | None`
    - Reuse query patterns from `src/cli/audit.py` (`_query_trades`, `_query_violations`, `_query_snapshots`)
    - Compute `ReportSummary` from gathered data
    - Return `ReportData` instance
  - [x] 3.4: Implement `_compute_summary()` helper:
    - Calculate trade stats from `list[TradeRecord]`
    - Calculate snapshot stats from `list[AccountSnapshotModel]` (trading days, balance progression, max drawdown)
    - Calculate violation stats from `list[RuleViolationModel]` (total, by rule type, blocked count)

- [x] Task 4: Implement PDF report generator with reportlab (AC: #1)
  - [x] 4.1: Create `ComplianceReportGenerator.generate_pdf()` method:
    - Accept `report_data: ReportData`, `output_path: Path`
    - Use `SimpleDocTemplate` with `letter` page size
    - Build story (list of Flowables) in order
  - [x] 4.2: Create header section:
    - Title: "Compliance Report" with account ID
    - Report period: start date to end date
    - Generation timestamp
    - Use `Paragraph` with `Heading1` and `Normal` styles
  - [x] 4.3: Create account summary section:
    - Table with: Opening Balance, Closing Balance, Peak Balance, Net P&L, Max Drawdown %, Trading Days
    - Use `Table` with `TableStyle` for formatting
    - Color positive values green, negative values red
  - [x] 4.4: Create daily P&L line chart:
    - Use `HorizontalLineChart` from `reportlab.graphics.charts.linecharts`
    - X-axis: dates from snapshots
    - Y-axis: closing_balance or daily_pnl values
    - Add to `Drawing(450, 200)` flowable
    - Include grid lines and axis labels
  - [x] 4.5: Create rule violation summary section:
    - Table with: Rule Type, Violations Count, Blocked Count, Peak Value, Threshold
    - Aggregate from `report_data.violations`
    - Show "No violations recorded" if empty
  - [x] 4.6: Create trade history section:
    - Table with: Date, Symbol, Side, Size, Entry, Exit, P&L, Strategy
    - Format financial values with appropriate precision (:.2f for dollars, :.4f for percentages)
    - Footer row with totals
  - [x] 4.7: Add page footer:
    - Generation timestamp, system info
    - Page numbers

- [x] Task 5: Implement JSON and CSV output formats (AC: #2, #4)
  - [x] 5.1: Create `ComplianceReportGenerator.generate_json()` method:
    - Accept `report_data: ReportData`
    - Serialize all sections using existing `to_dict()` methods on ORM models
    - Financial values as strings (via `str()`, NEVER `float()`)
    - Return dict or write to file with `json.dumps(data, indent=2, default=str)`
  - [x] 5.2: Create `ComplianceReportGenerator.generate_csv()` method:
    - Accept `report_data: ReportData`, `output_dir: Path`
    - Write separate CSV files:
      - `report-{account_id}-trades-{date}.csv`
      - `report-{account_id}-violations-{date}.csv`
      - `report-{account_id}-snapshots-{date}.csv`
      - `report-{account_id}-summary-{date}.csv`
    - Use stdlib `csv.DictWriter`
    - Display confirmation: "Exported to {filename}"

- [x] Task 6: Implement dashboard comparison mode (AC: #3)
  - [x] 6.1: Create `ComplianceReportGenerator.generate_comparison()` method:
    - Accept `report_data: ReportData`
    - Compute key metrics from gathered data:
      - Daily Loss (worst single day P&L %)
      - Max Drawdown (peak drawdown %)
      - Trading Days count
      - Profit Target (total P&L %)
      - Total Trades count
      - Win Rate %
    - Return formatted comparison table using `tabulate`
  - [x] 6.2: Format output with two columns: "System Value" and "FTMO Dashboard (enter manually)"
    - System values filled from computed metrics
    - FTMO column shows `[___]` placeholders for manual entry
    - Color system values: green for positive, red for negative

- [x] Task 7: Create CLI `report` command (AC: #1-6)
  - [x] 7.1: Create `services/trading-engine/src/cli/report.py` with `report_app = typer.Typer(name="report", help="Generate compliance reports for prop firm accounts")`
  - [x] 7.2: Add `generate` command (default command) with options:
    - `--account/-a` (REQUIRED): Account ID
    - `--format/-f` (default: "pdf"): Output format ("pdf", "json", "csv")
    - `--days/-d` (optional): Number of days to include (default: all)
    - `--since` (optional): Start date (ISO format), overrides --days
    - `--until` (optional): End date (ISO format, default: today)
    - `--output/-o` (optional): Output file path (default: auto-generated in current directory)
    - `--compare-dashboard` (default: False): Show dashboard comparison instead of generating report
  - [x] 7.3: Register in `src/cli/main.py`: `app.add_typer(report_app, name="report")`
  - [x] 7.4: Add `report_app` to `src/cli/__init__.py` exports
  - [x] 7.5: Implement command flow:
    1. Get DB session factory (exits with error if DATABASE_URL not set)
    2. Parse date range from --days/--since/--until
    3. Gather report data via `ReportDataGatherer.gather()`
    4. If `--compare-dashboard`: display comparison table and exit
    5. Else: generate output in requested format
    6. Display confirmation with output file path

- [x] Task 8: Add unit and integration tests (AC: #1-6)
  - [x] 8.1: Unit test: `ReportDataGatherer.gather()` with mocked DB session returns correct `ReportData`
  - [x] 8.2: Unit test: `_compute_summary()` calculates correct trade stats (win rate, net P&L, best/worst day)
  - [x] 8.3: Unit test: `_compute_summary()` calculates correct snapshot stats (trading days, max drawdown, balance progression)
  - [x] 8.4: Unit test: `_compute_summary()` calculates correct violation stats (total, by rule type, blocked count)
  - [x] 8.5: Unit test: `generate_pdf()` creates a valid PDF file at specified path (check file exists + size > 0)
  - [x] 8.6: Unit test: `generate_json()` returns valid JSON with all sections and financial values as strings
  - [x] 8.7: Unit test: `generate_csv()` writes CSV files with correct headers and row data
  - [x] 8.8: Unit test: `generate_comparison()` returns formatted table with all metrics
  - [x] 8.9: Unit test: Missing DATABASE_URL shows error and exits with code 1
  - [x] 8.10: Unit test: Empty data (no trades, no violations, no snapshots) produces valid report with "No data" messages
  - [x] 8.11: Unit test: DECIMAL precision preserved in JSON output (strings, not floats)
  - [x] 8.12: Integration test: Full CLI `report --account test-001 --format json` via CliRunner
  - [x] 8.13: Integration test: Full CLI `report --account test-001 --format pdf` via CliRunner (verify file creation)
  - [x] 8.14: Integration test: Full CLI `report --account test-001 --compare-dashboard` via CliRunner
  - [x] 8.15: Integration test: Full CLI `report --account test-001 --format csv` via CliRunner (verify files created)

## Dev Notes

### CRITICAL: Read Before Implementation

**These items MUST be completed or the feature will not work:**

1. **NEW DEPENDENCY: reportlab**: This is the ONLY story in Epic 7 that adds a new dependency. Add `reportlab>=4.0` to `pyproject.toml`. ReportLab is a pure-Python PDF generation library with built-in charting (line charts, bar charts, tables). It does NOT require system-level dependencies like WeasyPrint (which needs Cairo/Pango). This makes it Docker-friendly and CI-friendly.

2. **CLI Framework is Typer (NOT Click)**: Same as all other CLI stories. Use `typer.Typer()`, `@app.command()`, `Annotated[type, typer.Option()]`. See `src/cli/main.py` and `src/cli/audit.py` for canonical patterns.

3. **Reuse Audit Query Patterns**: The data gathering for reports uses the SAME database queries as Story 7.5's audit commands. Either import from `src/cli/audit.py` or extract shared query functions to a common location. The query patterns are:
   - `SELECT * FROM trades WHERE account_id = :id AND entry_time >= :since ORDER BY entry_time DESC`
   - `SELECT * FROM rule_violations WHERE account_id = :id AND timestamp >= :since ORDER BY timestamp DESC`
   - `SELECT * FROM account_snapshots WHERE account_id = :id AND snapshot_date >= :since ORDER BY snapshot_date DESC`

4. **Database Session Factory Pattern**: Use existing `create_db_session_factory()` from `src/cli/main.py:28-69`. It handles DATABASE_URL reading, postgresql:// to postgresql+asyncpg:// conversion, and async_sessionmaker creation.

5. **Async/Sync Bridge**: All DB queries are async. CLI commands are sync. Use `_run_async(coro)` wrapper from `main.py:82-91` which calls `asyncio.run()`. **DO NOT** create a new event loop pattern.

6. **ORM Models Already Exist**: Do NOT re-create any models. Use:
   - `TradeRecord` at `src/orders/db_models.py` (has `to_dict()` method)
   - `RuleViolationModel` at `src/rules/violation_db_writer.py` (has `to_dict()` method)
   - `AccountSnapshotModel` at `src/snapshots/models.py` (has `to_dict()` method)

7. **DECIMAL Precision is Critical**: All financial values from TimescaleDB are `Decimal` type. When serializing to JSON, convert via `str()` - NEVER `float()`. For PDF tables, format with `:.2f` for dollars, `:.4f` for percentages.

8. **ReportLab PDF Patterns** (from Context7 research):
   ```python
   from reportlab.lib.styles import getSampleStyleSheet
   from reportlab.lib.pagesizes import letter
   from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, Spacer
   from reportlab.graphics.charts.linecharts import HorizontalLineChart
   from reportlab.graphics.shapes import Drawing
   from reportlab.lib import colors

   # Create PDF
   doc = SimpleDocTemplate('report.pdf', pagesize=letter)
   story = []  # list of Flowables

   # Add heading
   styles = getSampleStyleSheet()
   story.append(Paragraph("Report Title", styles['Heading1']))

   # Add table
   data = [['Header1', 'Header2'], ['val1', 'val2']]
   table = Table(data, colWidths=[200, 200])
   table.setStyle([
       ('FONT', (0,0), (-1,0), 'Helvetica-Bold', 10),
       ('INNERGRID', (0,0), (-1,-1), 0.25, colors.black),
       ('BOX', (0,0), (-1,-1), 0.25, colors.black),
   ])
   story.append(table)

   # Add line chart
   drawing = Drawing(450, 200)
   lc = HorizontalLineChart()
   lc.x, lc.y, lc.width, lc.height = 50, 50, 350, 125
   lc.data = [(100000, 100500, 99800, 100200)]  # balance progression
   lc.categoryAxis.categoryNames = ['Day 1', 'Day 2', 'Day 3', 'Day 4']
   drawing.add(lc)
   story.append(drawing)

   doc.build(story)
   ```

9. **CSV Export Uses stdlib `csv` Module**: Same as Story 7.5. Use `csv.DictWriter()` for structured output. Write multiple files (one per section) to current working directory.

10. **Color Output via STATUS_COLORS**: For CLI comparison table:
    - Green (`STATUS_COLORS["connected"]`): Positive values
    - Red (`STATUS_COLORS["error"]`): Negative values, violations
    - Yellow (`STATUS_COLORS["paused"]`): Warnings
    - Cyan (`STATUS_COLORS["starting"]`): Headers

11. **Auto-generated Filenames**: Follow the pattern from audit.py:
    - PDF: `compliance-report-{account_id}-{date}.pdf`
    - JSON: `compliance-report-{account_id}-{date}.json`
    - CSV: `report-{account_id}-{section}-{date}.csv` (per section)

---

### Quick Reference: What to Create/Modify

| Component | What to Do | Location |
|-----------|------------|----------|
| **pyproject.toml** | Add `reportlab>=4.0` dependency | `services/trading-engine/pyproject.toml` (MODIFY) |
| **reports/__init__.py** | Module init with exports | `src/reports/__init__.py` (NEW) |
| **reports/models.py** | ReportData and ReportSummary dataclasses | `src/reports/models.py` (NEW) |
| **reports/data_gatherer.py** | Async data gathering and summary computation | `src/reports/data_gatherer.py` (NEW) |
| **reports/compliance_report.py** | PDF, JSON, CSV generators | `src/reports/compliance_report.py` (NEW) |
| **cli/report.py** | CLI `report` command with options | `src/cli/report.py` (NEW) |
| **cli/main.py** | Register `report_app` | `src/cli/main.py` (MODIFY - 2 lines) |
| **cli/__init__.py** | Add `report_app` to exports | `src/cli/__init__.py` (MODIFY - 1 line) |
| **Unit Tests** | Report generation and data gathering tests | `tests/unit/test_compliance_report.py` (NEW) |
| **Integration Tests** | Full CLI invocation tests | `tests/integration/test_compliance_report.py` (NEW) |

---

### Architecture Compliance

**Service:** `services/trading-engine/` (Python 3.11+)
**Database:** TimescaleDB (PostgreSQL 16+)
**ORM:** SQLAlchemy 2.0+ with async support (asyncpg)
**CLI Framework:** Typer with subcommand groups
**PDF Library:** ReportLab 4.0+ (NEW dependency)

**CRITICAL CONSTRAINTS from Architecture:**

Tables being queried (same as Story 7.5):

```sql
-- trades (regular table, no retention)
CREATE TABLE trades (
    trade_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id VARCHAR(50) NOT NULL,
    strategy_name VARCHAR(100) NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    side VARCHAR(4) NOT NULL CHECK (side IN ('BUY', 'SELL')),
    quantity DECIMAL(18, 8) NOT NULL,
    entry_price DECIMAL(18, 5) NOT NULL,
    entry_time TIMESTAMPTZ NOT NULL,
    exit_price DECIMAL(18, 5),
    exit_time TIMESTAMPTZ,
    pnl_dollars DECIMAL(18, 2),
    pnl_percent DECIMAL(8, 4),
    status VARCHAR(20) DEFAULT 'open',
    ...
);
CREATE INDEX idx_trades_account_time ON trades (account_id, entry_time DESC);

-- rule_violations (hypertable, 90-day retention for raw data)
CREATE TABLE rule_violations (
    id UUID DEFAULT gen_random_uuid(),
    account_id VARCHAR(50) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    rule_type VARCHAR(50) NOT NULL,
    rule_name VARCHAR(100) NOT NULL,
    severity VARCHAR(20) NOT NULL,
    current_value DECIMAL(18, 4),
    threshold_value DECIMAL(18, 4),
    action_taken VARCHAR(50) NOT NULL,
    message TEXT,
    ...
);
CREATE INDEX idx_violations_account ON rule_violations (account_id, timestamp DESC);

-- account_snapshots (regular table, no retention)
CREATE TABLE account_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id VARCHAR(50) NOT NULL,
    snapshot_date DATE NOT NULL,
    opening_balance DECIMAL(18, 2),
    closing_balance DECIMAL(18, 2),
    daily_pnl DECIMAL(18, 2),
    daily_pnl_percent DECIMAL(8, 4),
    drawdown_percent DECIMAL(8, 4),
    trades_count INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,
    losing_trades INTEGER DEFAULT 0,
    ...
    UNIQUE(account_id, snapshot_date)
);
CREATE INDEX idx_snapshots_account_date ON account_snapshots (account_id, snapshot_date DESC);
```

**Continuous Aggregates Available** (for future enhancement - longer time ranges):
- `audit_daily_summary` (day, account_id, event_type, event_count, warning_count, error_count)
- `violation_daily_summary` (day, account_id, rule_type, violation_count, critical_count, warning_count, blocked_count, peak_value, min_threshold)

**Retention Window Awareness:**
- `trades`: No retention - reports can query all history
- `rule_violations`: 90 days raw, 365 days via `violation_daily_summary` aggregate
- `account_snapshots`: No retention - reports can query all history
- For reports spanning > 90 days, violation data may be incomplete in raw table. Consider querying continuous aggregate for longer periods (future enhancement).

**Communication Patterns:**
| Direction | Protocol | Port | Data |
|-----------|----------|------|------|
| Outbound | PostgreSQL | 5432 | SELECT queries on trades, rule_violations, account_snapshots |

---

### Context from Previous Stories

**From Story 7.5 (CLI Audit Query Commands) - DIRECT REUSE:**

| Pattern | Implementation | Location |
|---------|----------------|----------|
| `_get_db_session_factory()` | Creates async sessionmaker from DATABASE_URL | `src/cli/audit.py` |
| `_query_trades()` | Async SELECT on trades table with filters | `src/cli/audit.py` |
| `_query_violations()` | Async SELECT on rule_violations with filters | `src/cli/audit.py` |
| `_query_snapshots()` | Async SELECT on account_snapshots with filters | `src/cli/audit.py` |
| `_compute_trade_summary()` | Trade stats: total, net P&L, win rate | `src/cli/audit.py` |
| `_export_json()` | JSON serialization with `to_dict()` + `default=str` | `src/cli/audit.py` |
| `_export_csv()` | CSV writing with `csv.DictWriter` | `src/cli/audit.py` |

**From Story 7.1 (Trade Execution Audit Logging):**

| Pattern | Implementation | Location |
|---------|----------------|----------|
| TradeRecord ORM | Full column mapping with `from_trade()`, `to_dict()` | `src/orders/db_models.py:27-129` |
| Financial precision | `Decimal(str(value))` everywhere, never float | All DB writers |

**From Story 7.3 (Rule Violation Tracking):**

| Pattern | Implementation | Location |
|---------|----------------|----------|
| RuleViolationModel | Full 17-column ORM with `to_dict()` | `src/rules/violation_db_writer.py` |

**From Story 7.4 (Daily Account Snapshots):**

| Pattern | Implementation | Location |
|---------|----------------|----------|
| AccountSnapshotModel | 17-column ORM with `from_snapshot_data()`, `to_dict()` | `src/snapshots/models.py` |

**Existing CLI Patterns (FOLLOW EXACTLY):**

| Pattern | Example | Location |
|---------|---------|----------|
| Typer app creation | `app = typer.Typer(name="trading-engine", ...)` | `src/cli/main.py:71-75` |
| Subcommand registration | `app.add_typer(audit_app, name="audit")` | `src/cli/main.py:78-79` |
| Async bridge | `_run_async(coro)` -> `asyncio.run(coro)` | `src/cli/main.py:82-91` |
| Table formatting | `tabulate(rows, headers, tablefmt="simple")` | `src/cli/main.py:572-604` |
| JSON output | `json.dumps(data, indent=2, default=str)` | `src/cli/main.py:676-677` |
| Error handling | `typer.style(msg, fg=STATUS_COLORS["error"])` + `raise typer.Exit(1)` | Throughout `main.py` |
| DB session factory | `create_db_session_factory()` -> `async_sessionmaker` | `src/cli/main.py:28-69` |
| Option pattern | `Annotated[str, typer.Option("--account", "-a", help="...")]` | `src/cli/main.py:609-623` |

**Testing Patterns (FOLLOW EXACTLY):**

| Pattern | Example | Location |
|---------|---------|----------|
| CliRunner | `from typer.testing import CliRunner; runner = CliRunner()` | `tests/unit/test_cli.py` |
| CLI invocation | `result = runner.invoke(app, ["report", "--account", "test-001", "--format", "json"])` | Test files |
| AsyncMock | `from unittest.mock import AsyncMock, MagicMock, patch` | All test files |
| DB session mock | Mock `async_sessionmaker` -> `AsyncSession` -> `execute()` -> `scalars()` | Test pattern |
| Assert exit code | `assert result.exit_code == 0` | Test pattern |
| Assert output | `assert "Compliance Report" in result.output` | Test pattern |
| Temp file cleanup | Use `tmp_path` pytest fixture for PDF/CSV output verification | Test pattern |

---

### Git Intelligence (Recent Commits)

Last 5 commits are all Epic 7 implementations:
```
e30a484 Implement spec 7 story 7.5  (CLI audit query commands)
a1a1694 Implement spec 7 story 7.4  (daily account snapshots)
fe5004b Implement spec 7 story 7.3  (rule violation tracking)
67cf9cc Implement spec 7 story 7.2  (comprehensive audit log table)
13fca35 Implement spec 7 story 7.1  (trade execution audit logging)
```

**Files created/modified in Epic 7 (stories 7.1-7.5):**
- `src/audit/` - AuditService, AuditDBWriter
- `src/orders/db_models.py` - TradeRecord ORM model
- `src/orders/trade_db_writer.py` - Trade persistence with session() context manager
- `src/rules/violation_db_writer.py` - Violation persistence + RuleViolationModel
- `src/rules/violation_service.py` - Violation service facade
- `src/snapshots/` - AccountSnapshotModel, SnapshotDBWriter, DailySnapshotService
- `src/cli/audit.py` - Audit CLI commands (trades, violations, daily)
- `src/engine.py` - Service lifecycle integration
- `infra/timescaledb/migrations/006-008` - Indexes, retention, compression, aggregates

**Key Convention:** All new modules in `src/` follow the pattern of `__init__.py` with exports + implementation files. Tests mirror module structure.

---

### Latest Technical Documentation (Context7 Research)

**ReportLab 4.x PDF Generation Patterns (from Context7 /websites/reportlab):**

```python
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Table, TableStyle,
    Spacer, PageBreak
)
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.shapes import Drawing

# Create document
doc = SimpleDocTemplate(
    'compliance-report.pdf',
    pagesize=letter,
    topMargin=0.5*inch,
    bottomMargin=0.5*inch
)
story = []
styles = getSampleStyleSheet()

# Header
story.append(Paragraph("Compliance Report: ftmo-gold-001", styles['Title']))
story.append(Paragraph(f"Period: 2025-12-01 to 2025-12-31", styles['Normal']))
story.append(Spacer(1, 12))

# Summary table with styling
summary_data = [
    ['Metric', 'Value'],
    ['Opening Balance', '$100,000.00'],
    ['Closing Balance', '$104,800.00'],
    ['Net P&L', '+$4,800.00'],
    ['Max Drawdown', '3.2%'],
    ['Trading Days', '18'],
]
summary_table = Table(summary_data, colWidths=[200, 150])
summary_table.setStyle(TableStyle([
    ('FONT', (0, 0), (-1, 0), 'Helvetica-Bold', 10),
    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2C3E50')),
    ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
    ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
    ('INNERGRID', (0, 0), (-1, -1), 0.25, colors.grey),
    ('BOX', (0, 0), (-1, -1), 0.5, colors.black),
    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8F9FA')]),
]))
story.append(summary_table)
story.append(Spacer(1, 24))

# Daily P&L line chart
drawing = Drawing(450, 200)
lc = HorizontalLineChart()
lc.x = 50
lc.y = 20
lc.width = 350
lc.height = 150
lc.data = [tuple(daily_balances)]  # e.g., (100000, 100500, 99800, ...)
lc.categoryAxis.categoryNames = [d.strftime('%m/%d') for d in snapshot_dates]
lc.categoryAxis.labels.boxAnchor = 'n'
lc.categoryAxis.labels.angle = 45
lc.valueAxis.valueMin = min(daily_balances) * 0.99
lc.valueAxis.valueMax = max(daily_balances) * 1.01
lc.lines[0].strokeWidth = 2
lc.lines[0].strokeColor = colors.HexColor('#2980B9')
lc.joinedLines = 1
drawing.add(lc)
story.append(Paragraph("Balance Progression", styles['Heading2']))
story.append(drawing)

doc.build(story)
```

**Key ReportLab Points:**
- Use `SimpleDocTemplate` for standard page layouts
- `Table` + `TableStyle` for structured data
- `HorizontalLineChart` for line charts (perfect for balance progression)
- `Drawing` wraps charts as Flowables
- `Spacer` for vertical spacing between sections
- `PageBreak` to start new pages for long trade histories
- All rendering is done in `doc.build(story)` call
- No external dependencies (pure Python, C extension optional for speed)

**SQLAlchemy 2.1 Async Query Patterns (from Context7 /websites/sqlalchemy_en_21):**

```python
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import async_sessionmaker

# Aggregate queries for report summaries
async with async_session() as session:
    # Count trades by status
    stmt = select(
        func.count(TradeRecord.trade_id),
        func.sum(TradeRecord.pnl_dollars),
    ).where(
        TradeRecord.account_id == account_id,
        TradeRecord.entry_time >= since
    )
    result = await session.execute(stmt)
    total_trades, total_pnl = result.one()
```

**Typer CLI Subcommand Pattern (from Context7 /fastapi/typer):**

```python
import typer
from typing_extensions import Annotated
from pathlib import Path

report_app = typer.Typer(name="report", help="Generate compliance reports")

@report_app.command()
def generate(
    account: Annotated[str, typer.Option("--account", "-a", help="Account ID")],
    format: Annotated[str, typer.Option("--format", "-f", help="Output format")] = "pdf",
    days: Annotated[int | None, typer.Option("--days", "-d", help="Days to include")] = None,
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Output file")] = None,
    compare_dashboard: Annotated[bool, typer.Option("--compare-dashboard", help="Show comparison")] = False,
):
    """Generate compliance report for a prop firm account."""
    ...
```

---

### Implementation Guide

**Step 1: Add dependency to `services/trading-engine/pyproject.toml`**
```toml
reportlab = ">=4.0"
```

**Step 2: Create `src/reports/__init__.py`**
```python
"""Compliance report generation module."""
from .compliance_report import ComplianceReportGenerator
from .models import ReportData, ReportSummary

__all__ = ["ComplianceReportGenerator", "ReportData", "ReportSummary"]
```

**Step 3: Create `src/reports/models.py`**
```python
"""Report data models."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

@dataclass
class ReportSummary:
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: Decimal = Decimal("0")
    net_pnl: Decimal = Decimal("0")
    best_day_pnl: Decimal = Decimal("0")
    worst_day_pnl: Decimal = Decimal("0")
    trading_days: int = 0
    calendar_days: int = 0
    opening_balance: Decimal = Decimal("0")
    closing_balance: Decimal = Decimal("0")
    peak_balance: Decimal = Decimal("0")
    max_drawdown_percent: Decimal = Decimal("0")
    current_drawdown_percent: Decimal = Decimal("0")
    total_violations: int = 0
    blocked_count: int = 0
    violations_by_rule: dict[str, int] = field(default_factory=dict)

@dataclass
class ReportData:
    account_id: str
    period_start: date
    period_end: date
    generated_at: datetime
    trades: list = field(default_factory=list)
    violations: list = field(default_factory=list)
    snapshots: list = field(default_factory=list)
    summary: ReportSummary = field(default_factory=ReportSummary)
```

**Step 4: Create `src/reports/data_gatherer.py`**
- Reuse query patterns from `src/cli/audit.py`
- Compute summary stats from gathered data

**Step 5: Create `src/reports/compliance_report.py`**
- PDF generation using reportlab (SimpleDocTemplate + Flowables)
- JSON generation using to_dict() + json.dumps
- CSV generation using csv.DictWriter
- Dashboard comparison using tabulate

**Step 6: Create `src/cli/report.py`**
- Follow exact same pattern as `src/cli/audit.py`
- Single `generate` command with format/comparison options

**Step 7: Register in `src/cli/main.py`**
```python
from .report import report_app
app.add_typer(report_app, name="report")
```

---

### Project Structure Notes

- New module: `services/trading-engine/src/reports/` (4 new files)
- New CLI file: `services/trading-engine/src/cli/report.py` (1 new file)
- Modified: `services/trading-engine/pyproject.toml` (1 line), `src/cli/main.py` (2 lines), `src/cli/__init__.py` (1 line)
- Tests: `tests/unit/test_compliance_report.py` and `tests/integration/test_compliance_report.py` (2 new files)
- Total: 7 new files, 3 modified files

### References

- [Source: docs/epics.md#Epic-7-Story-7.6] - Acceptance criteria and user story
- [Source: docs/prd.md#FR45] - Account snapshots for compliance verification
- [Source: docs/prd.md#FR42-44] - Audit trail requirements
- [Source: docs/architecture.md#Database-Schema] - TimescaleDB table schemas
- [Source: docs/architecture.md#Monorepo-Structure] - Service layout and CLI location
- [Source: infra/timescaledb/init.sql#trades] - Trade table schema
- [Source: infra/timescaledb/init.sql#rule_violations] - Violations table schema
- [Source: infra/timescaledb/init.sql#account_snapshots] - Snapshots table schema
- [Source: infra/timescaledb/migrations/007] - Audit retention and continuous aggregate
- [Source: infra/timescaledb/migrations/008] - Violations retention and continuous aggregate
- [Source: services/trading-engine/src/cli/main.py] - CLI patterns, _run_async, session factory
- [Source: services/trading-engine/src/cli/audit.py] - Audit query patterns to reuse
- [Source: services/trading-engine/src/orders/db_models.py] - TradeRecord ORM
- [Source: services/trading-engine/src/rules/violation_db_writer.py] - RuleViolationModel ORM
- [Source: services/trading-engine/src/snapshots/models.py] - AccountSnapshotModel ORM
- [Source: docs/sprint-artifacts/7-5-cli-audit-query-commands.md] - Previous story patterns and dev notes
- [Context7: /websites/reportlab] - ReportLab PDF generation with tables and charts
- [Context7: /fastapi/typer] - Typer CLI subcommand and option patterns

## Dev Agent Record

### Context Reference

<!-- Path(s) to story context XML will be added here by context workflow -->

### Agent Model Used

Claude Opus 4.6

### Debug Log References

### Completion Notes List

- Ultimate context engine analysis completed - comprehensive developer guide created
- Context7 MCP research completed for ReportLab 4.x, Typer CLI, and SQLAlchemy 2.1 async patterns
- All 5 previous Epic 7 stories (7.1-7.5) analyzed for implementation patterns and reuse opportunities
- Git history analyzed: 44 files changed across stories 7.1-7.5, all following consistent conventions
- PDF generation approach: ReportLab chosen over WeasyPrint (pure Python, built-in charting, no system deps)
- Key reuse: audit.py query functions, ORM to_dict() methods, CLI patterns, session factory
- NEW dependency required: reportlab>=4.0 (only new dep added in all of Epic 7)
- Implementation completed: All 8 tasks with 43 subtasks implemented
- reportlab 4.4.10 installed via uv (with pillow and charset-normalizer transitive deps)
- PDF generation includes: header, account summary table, balance progression line chart, violation summary, trade history with totals, and footer
- JSON output preserves all DECIMAL values as strings for financial precision
- CSV exports 4 separate files (trades, violations, snapshots, summary) using stdlib csv.DictWriter
- Dashboard comparison outputs tabulate-formatted table with [___] placeholders for manual entry
- Data gatherer reuses SQLAlchemy query patterns from audit.py with date range filtering
- _compute_summary() calculates trade stats, snapshot stats, and violation stats from raw data
- 22 tests total: 18 unit tests + 4 integration tests, all passing
- Full regression suite: 2040 passed, 78 pre-existing failures (Redis/DB integration requiring running infra)
- ruff linting passes on all new files with zero warnings

### File List

**New files:**
- `services/trading-engine/src/reports/__init__.py` - Module exports
- `services/trading-engine/src/reports/models.py` - ReportData and ReportSummary dataclasses
- `services/trading-engine/src/reports/data_gatherer.py` - Async data gathering and summary computation
- `services/trading-engine/src/reports/compliance_report.py` - PDF, JSON, CSV generators and dashboard comparison
- `services/trading-engine/src/cli/report.py` - CLI report command with generate subcommand
- `services/trading-engine/tests/unit/test_compliance_report.py` - 18 unit tests
- `services/trading-engine/tests/integration/test_compliance_report.py` - 4 integration tests

**Modified files:**
- `services/trading-engine/pyproject.toml` - Added reportlab>=4.0 dependency
- `services/trading-engine/src/cli/main.py` - Imported and registered report_app
- `services/trading-engine/src/cli/__init__.py` - Added report_app to exports

## Change Log

- 2026-02-27: Implemented compliance report generation (Story 7.6) - Added reportlab dependency, created reports module with PDF/JSON/CSV/dashboard comparison output formats, CLI report command, and 22 tests (18 unit + 4 integration)
- 2026-02-27: Code review fixes applied:
  - CRITICAL: Fixed Daily Loss displaying dollar amount as percentage; now uses worst_day_pnl_percent from snapshot data
  - HIGH: Deleted junk files (=4.0 pip artifact, leftover test JSON output)
  - HIGH: Changed CLI from `report generate --account` to `report --account` to match ACs (callback pattern)
  - HIGH: Fixed variable shadowing of `s` in generate_json list comprehension
  - MEDIUM: Added conditional color-coding in PDF summary table (green/red for P&L, red for drawdown)
  - MEDIUM: Added explanatory comment for float() usage in chart data (ReportLab API requirement)
  - MEDIUM: Added comment explaining _run_async duplication (circular import avoidance)
  - Added worst_day_pnl_percent field to ReportSummary model
