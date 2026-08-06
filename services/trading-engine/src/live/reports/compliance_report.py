"""Compliance report generator - PDF, JSON, CSV, and dashboard comparison."""

from __future__ import annotations

import csv
import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from tabulate import tabulate

from .models import ReportData


class ComplianceReportGenerator:
    """Generates compliance reports in multiple formats."""

    # -----------------------------------------------------------------------
    # PDF generation (Task 4)
    # -----------------------------------------------------------------------

    def generate_pdf(self, report_data: ReportData, output_path: Path) -> None:
        """Generate a PDF compliance report.

        Args:
            report_data: Gathered report data with computed summary.
            output_path: Path to write the PDF file.
        """
        from reportlab.graphics.charts.linecharts import HorizontalLineChart
        from reportlab.graphics.shapes import Drawing
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import (
            PageBreak,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )

        doc = SimpleDocTemplate(
            str(output_path),
            pagesize=letter,
            topMargin=0.5 * inch,
            bottomMargin=0.5 * inch,
        )
        story: list[Any] = []
        styles = getSampleStyleSheet()
        s = report_data.summary

        # --- Header section (4.2) ---
        story.append(
            Paragraph(f"Compliance Report: {report_data.account_id}", styles["Title"])
        )
        story.append(
            Paragraph(
                f"Period: {report_data.period_start.isoformat()} to "
                f"{report_data.period_end.isoformat()}",
                styles["Normal"],
            )
        )
        story.append(
            Paragraph(
                f"Generated: {report_data.generated_at.strftime('%Y-%m-%d %H:%M:%S UTC')}",
                styles["Normal"],
            )
        )
        story.append(Spacer(1, 12))

        # --- Account summary section (4.3) ---
        story.append(Paragraph("Account Summary", styles["Heading2"]))
        summary_data = [
            ["Metric", "Value"],
            ["Opening Balance", f"${s.opening_balance:,.2f}"],
            ["Closing Balance", f"${s.closing_balance:,.2f}"],
            ["Peak Balance", f"${s.peak_balance:,.2f}"],
            ["Net P&L", f"${s.net_pnl:+,.2f}"],
            ["Max Drawdown", f"{s.max_drawdown_percent:.2f}%"],
            ["Current Drawdown", f"{s.current_drawdown_percent:.2f}%"],
            [
                "Trading Days",
                f"{s.trading_days} / {s.calendar_days} calendar days",
            ],
            ["Total Trades", str(s.total_trades)],
            ["Win Rate", f"{s.win_rate:.1f}%"],
        ]
        summary_table = Table(summary_data, colWidths=[200, 250])
        table_styles = [
            ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 10),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2C3E50")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.black),
            (
                "ROWBACKGROUNDS",
                (0, 1),
                (-1, -1),
                [colors.white, colors.HexColor("#F8F9FA")],
            ),
        ]
        # Conditional color-coding: green for positive, red for negative (row 4 = Net P&L)
        if s.net_pnl > 0:
            table_styles.append(("TEXTCOLOR", (1, 4), (1, 4), colors.HexColor("#27AE60")))
        elif s.net_pnl < 0:
            table_styles.append(("TEXTCOLOR", (1, 4), (1, 4), colors.HexColor("#E74C3C")))
        # Drawdown values are always concerning (rows 5, 6)
        if s.max_drawdown_percent > 0:
            table_styles.append(("TEXTCOLOR", (1, 5), (1, 5), colors.HexColor("#E74C3C")))
        if s.current_drawdown_percent > 0:
            table_styles.append(("TEXTCOLOR", (1, 6), (1, 6), colors.HexColor("#E74C3C")))
        summary_table.setStyle(TableStyle(table_styles))
        story.append(summary_table)
        story.append(Spacer(1, 24))

        # --- Daily P&L line chart (4.4) ---
        if report_data.snapshots:
            story.append(Paragraph("Balance Progression", styles["Heading2"]))
            daily_balances = []
            snapshot_dates = []
            for snap in report_data.snapshots:
                bal = snap.closing_balance
                if bal is not None:
                    daily_balances.append(float(bal))
                    snapshot_dates.append(snap.snapshot_date.strftime("%m/%d"))

            if daily_balances:
                # float() needed here: ReportLab chart API requires numeric values,
                # not Decimal. Precision loss is acceptable for chart visualization only.
                drawing = Drawing(450, 200)
                lc = HorizontalLineChart()
                lc.x = 50
                lc.y = 20
                lc.width = 350
                lc.height = 150
                lc.data = [tuple(daily_balances)]
                lc.categoryAxis.categoryNames = snapshot_dates
                lc.categoryAxis.labels.boxAnchor = "n"
                lc.categoryAxis.labels.angle = 45
                lc.categoryAxis.labels.fontSize = 7
                min_bal = min(daily_balances)
                max_bal = max(daily_balances)
                margin = (max_bal - min_bal) * 0.05 if max_bal != min_bal else 100
                lc.valueAxis.valueMin = min_bal - margin
                lc.valueAxis.valueMax = max_bal + margin
                lc.lines[0].strokeWidth = 2
                lc.lines[0].strokeColor = colors.HexColor("#2980B9")
                lc.joinedLines = 1
                drawing.add(lc)
                story.append(drawing)
                story.append(Spacer(1, 24))

        # --- Rule violation summary (4.5) ---
        story.append(Paragraph("Rule Violations", styles["Heading2"]))
        if report_data.violations:
            # Aggregate violations by rule type
            rule_agg: dict[str, dict[str, Any]] = {}
            for v in report_data.violations:
                rt = v.rule_type
                if rt not in rule_agg:
                    rule_agg[rt] = {
                        "count": 0,
                        "blocked": 0,
                        "peak_value": None,
                        "threshold": None,
                    }
                rule_agg[rt]["count"] += 1
                if v.order_blocked:
                    rule_agg[rt]["blocked"] += 1
                if v.current_value is not None:
                    if (
                        rule_agg[rt]["peak_value"] is None
                        or v.current_value > rule_agg[rt]["peak_value"]
                    ):
                        rule_agg[rt]["peak_value"] = v.current_value
                if v.threshold_value is not None:
                    rule_agg[rt]["threshold"] = v.threshold_value

            viol_data = [["Rule Type", "Count", "Blocked", "Peak Value", "Threshold"]]
            for rt, agg in rule_agg.items():
                peak = f"{agg['peak_value']:.4f}" if agg["peak_value"] is not None else "-"
                thresh = f"{agg['threshold']:.4f}" if agg["threshold"] is not None else "-"
                viol_data.append([rt, str(agg["count"]), str(agg["blocked"]), peak, thresh])

            viol_table = Table(viol_data, colWidths=[120, 60, 60, 100, 100])
            viol_table.setStyle(
                TableStyle(
                    [
                        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E74C3C")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.grey),
                        ("BOX", (0, 0), (-1, -1), 0.5, colors.black),
                        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
                    ]
                )
            )
            story.append(viol_table)
        else:
            story.append(Paragraph("No violations recorded.", styles["Normal"]))
        story.append(Spacer(1, 24))

        # --- Trade history (4.6) ---
        story.append(Paragraph("Trade History", styles["Heading2"]))
        if report_data.trades:
            trade_data = [["Date", "Symbol", "Side", "Size", "Entry", "Exit", "P&L", "Strategy"]]
            total_pnl = Decimal("0")
            for t in report_data.trades:
                pnl = t.pnl_dollars
                pnl_str = f"${pnl:+,.2f}" if pnl is not None else "-"
                if pnl is not None:
                    total_pnl += pnl
                trade_data.append([
                    t.entry_time.strftime("%Y-%m-%d") if t.entry_time else "",
                    t.symbol,
                    t.side,
                    f"{t.quantity:.2f}" if t.quantity is not None else "-",
                    f"${t.entry_price:,.2f}" if t.entry_price is not None else "-",
                    f"${t.exit_price:,.2f}" if t.exit_price is not None else "OPEN",
                    pnl_str,
                    t.strategy_name,
                ])
            # Footer totals
            trade_data.append(["", "", "", "", "", "TOTAL", f"${total_pnl:+,.2f}", ""])

            col_widths = [60, 60, 35, 40, 65, 65, 65, 70]
            # Handle long trade lists with PageBreak
            if len(trade_data) > 40:
                story.append(PageBreak())

            trade_table = Table(trade_data, colWidths=col_widths)
            trade_table.setStyle(
                TableStyle(
                    [
                        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8),
                        ("FONTSIZE", (0, 1), (-1, -1), 7),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2C3E50")),
                        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.grey),
                        ("BOX", (0, 0), (-1, -1), 0.5, colors.black),
                        ("ALIGN", (3, 0), (-2, -1), "RIGHT"),
                        # Bold totals row
                        ("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 8),
                        ("LINEABOVE", (0, -1), (-1, -1), 1, colors.black),
                    ]
                )
            )
            story.append(trade_table)
        else:
            story.append(Paragraph("No trades recorded.", styles["Normal"]))

        story.append(Spacer(1, 24))

        # --- Footer (4.7) ---
        story.append(
            Paragraph(
                f"Generated: {report_data.generated_at.strftime('%Y-%m-%d %H:%M:%S UTC')} "
                f"| Trading Engine v0.1.0",
                styles["Normal"],
            )
        )

        doc.build(story)

    # -----------------------------------------------------------------------
    # JSON generation (Task 5.1)
    # -----------------------------------------------------------------------

    def generate_json(self, report_data: ReportData, output_path: Path | None = None) -> str:
        """Generate a JSON compliance report.

        Financial values are serialized as strings via to_dict() for DECIMAL precision.

        Args:
            report_data: Gathered report data.
            output_path: Optional path to write JSON file.

        Returns:
            JSON string of the report.
        """
        s = report_data.summary

        data = {
            "report": {
                "account_id": report_data.account_id,
                "period_start": report_data.period_start.isoformat(),
                "period_end": report_data.period_end.isoformat(),
                "generated_at": report_data.generated_at.isoformat(),
            },
            "summary": {
                "total_trades": s.total_trades,
                "winning_trades": s.winning_trades,
                "losing_trades": s.losing_trades,
                "win_rate": str(s.win_rate),
                "net_pnl": str(s.net_pnl),
                "best_day_pnl": str(s.best_day_pnl),
                "worst_day_pnl": str(s.worst_day_pnl),
                "worst_day_pnl_percent": str(s.worst_day_pnl_percent),
                "trading_days": s.trading_days,
                "calendar_days": s.calendar_days,
                "opening_balance": str(s.opening_balance),
                "closing_balance": str(s.closing_balance),
                "peak_balance": str(s.peak_balance),
                "max_drawdown_percent": str(s.max_drawdown_percent),
                "current_drawdown_percent": str(s.current_drawdown_percent),
                "total_violations": s.total_violations,
                "blocked_count": s.blocked_count,
                "violations_by_rule": s.violations_by_rule,
            },
            "trades": [t.to_dict() for t in report_data.trades],
            "violations": [v.to_dict() for v in report_data.violations],
            "snapshots": [snap.to_dict() for snap in report_data.snapshots],
        }

        json_str = json.dumps(data, indent=2, default=str)

        if output_path is not None:
            output_path.write_text(json_str)

        return json_str

    # -----------------------------------------------------------------------
    # CSV generation (Task 5.2)
    # -----------------------------------------------------------------------

    def generate_csv(self, report_data: ReportData, output_dir: Path) -> list[str]:
        """Generate CSV files for each report section.

        Args:
            report_data: Gathered report data.
            output_dir: Directory to write CSV files.

        Returns:
            List of filenames written.
        """
        today = date.today().isoformat()
        aid = report_data.account_id
        filenames: list[str] = []

        # Trades CSV
        trades_file = output_dir / f"report-{aid}-trades-{today}.csv"
        with open(trades_file, "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "date", "symbol", "side", "size", "entry_price",
                    "exit_price", "pnl_dollars", "strategy",
                ],
            )
            writer.writeheader()
            for t in report_data.trades:
                writer.writerow({
                    "date": t.entry_time.strftime("%Y-%m-%d %H:%M") if t.entry_time else "",
                    "symbol": t.symbol,
                    "side": t.side,
                    "size": str(t.quantity),
                    "entry_price": str(t.entry_price),
                    "exit_price": str(t.exit_price) if t.exit_price is not None else "OPEN",
                    "pnl_dollars": str(t.pnl_dollars) if t.pnl_dollars is not None else "",
                    "strategy": t.strategy_name,
                })
        filenames.append(trades_file.name)

        # Violations CSV
        violations_file = output_dir / f"report-{aid}-violations-{today}.csv"
        with open(violations_file, "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "timestamp", "rule_type", "severity", "current_value",
                    "threshold_value", "action_taken", "message",
                ],
            )
            writer.writeheader()
            for v in report_data.violations:
                writer.writerow({
                    "timestamp": v.timestamp.strftime("%Y-%m-%d %H:%M") if v.timestamp else "",
                    "rule_type": v.rule_type,
                    "severity": v.severity,
                    "current_value": str(v.current_value) if v.current_value is not None else "",
                    "threshold_value": str(v.threshold_value) if v.threshold_value is not None else "",
                    "action_taken": v.action_taken,
                    "message": v.message or "",
                })
        filenames.append(violations_file.name)

        # Snapshots CSV
        snapshots_file = output_dir / f"report-{aid}-snapshots-{today}.csv"
        with open(snapshots_file, "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "date", "opening_balance", "closing_balance", "daily_pnl",
                    "daily_pnl_percent", "drawdown_percent", "trades_count",
                ],
            )
            writer.writeheader()
            for s in report_data.snapshots:
                writer.writerow({
                    "date": s.snapshot_date.isoformat() if s.snapshot_date else "",
                    "opening_balance": str(s.opening_balance) if s.opening_balance is not None else "",
                    "closing_balance": str(s.closing_balance) if s.closing_balance is not None else "",
                    "daily_pnl": str(s.daily_pnl) if s.daily_pnl is not None else "",
                    "daily_pnl_percent": str(s.daily_pnl_percent) if s.daily_pnl_percent is not None else "",
                    "drawdown_percent": str(s.drawdown_percent) if s.drawdown_percent is not None else "",
                    "trades_count": str(s.trades_count),
                })
        filenames.append(snapshots_file.name)

        # Summary CSV
        summary_file = output_dir / f"report-{aid}-summary-{today}.csv"
        sm = report_data.summary
        with open(summary_file, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["metric", "value"])
            writer.writeheader()
            writer.writerow({"metric": "total_trades", "value": str(sm.total_trades)})
            writer.writerow({"metric": "winning_trades", "value": str(sm.winning_trades)})
            writer.writerow({"metric": "losing_trades", "value": str(sm.losing_trades)})
            writer.writerow({"metric": "win_rate", "value": str(sm.win_rate)})
            writer.writerow({"metric": "net_pnl", "value": str(sm.net_pnl)})
            writer.writerow({"metric": "opening_balance", "value": str(sm.opening_balance)})
            writer.writerow({"metric": "closing_balance", "value": str(sm.closing_balance)})
            writer.writerow({"metric": "peak_balance", "value": str(sm.peak_balance)})
            writer.writerow({"metric": "max_drawdown_percent", "value": str(sm.max_drawdown_percent)})
            writer.writerow({"metric": "trading_days", "value": str(sm.trading_days)})
            writer.writerow({"metric": "total_violations", "value": str(sm.total_violations)})
            writer.writerow({"metric": "blocked_count", "value": str(sm.blocked_count)})
        filenames.append(summary_file.name)

        return filenames

    # -----------------------------------------------------------------------
    # Dashboard comparison (Task 6)
    # -----------------------------------------------------------------------

    def generate_comparison(self, report_data: ReportData) -> str:
        """Generate a dashboard comparison table.

        Shows system-computed metrics alongside placeholders for manual FTMO dashboard entry.

        Args:
            report_data: Gathered report data.

        Returns:
            Formatted comparison table string.
        """
        s = report_data.summary

        # Compute profit target as total P&L percentage
        if s.opening_balance and s.opening_balance > 0:
            profit_target_pct = (s.net_pnl / s.opening_balance) * 100
        else:
            profit_target_pct = Decimal("0")

        rows = [
            ["Daily Loss", f"{s.worst_day_pnl_percent:+.1f}%", "[___]"],
            ["Max Drawdown", f"{s.max_drawdown_percent:.1f}%", "[___]"],
            ["Trading Days", str(s.trading_days), "[___]"],
            ["Profit Target", f"{profit_target_pct:.1f}%", "[___]"],
            ["Total Trades", str(s.total_trades), "[___]"],
            ["Win Rate", f"{s.win_rate:.1f}%", "[___]"],
        ]

        headers = ["Metric", "System Value", "FTMO Dashboard (enter manually)"]
        table = tabulate(rows, headers=headers, tablefmt="simple")

        title = (
            f"FTMO Dashboard Comparison for {report_data.account_id}\n"
            + "=" * 50
        )
        return f"{title}\n{table}"
