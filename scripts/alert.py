#!/usr/bin/env python3
"""Alerting module for GitHub Stars Dashboard.

This module provides alert configuration and notification handlers.
"""

import json
import smtplib
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Callable, Optional


@dataclass
class Alert:
    """Represents an alert."""

    timestamp: float = field(default_factory=time.time)
    datetime_str: str = field(default_factory=lambda: datetime.now().isoformat())
    alert_type: str = "warning"
    severity: str = "medium"
    title: str = ""
    message: str = ""
    metric_name: str = ""
    metric_value: float = 0.0
    threshold: float = 0.0
    acknowledged: bool = False
    acknowledged_at: Optional[float] = None


class AlertRule:
    """Defines an alert rule with conditions and thresholds."""

    def __init__(
        self,
        name: str,
        metric_name: str,
        condition: str,
        threshold: float,
        severity: str = "medium",
        message_template: str = "",
    ):
        """Initialize alert rule.

        Args:
            name: Rule name.
            metric_name: Name of the metric to monitor.
            condition: Comparison operator (gt, lt, eq, gte, lte).
            threshold: Threshold value.
            severity: Alert severity (low, medium, high, critical).
            message_template: Custom message template.
        """
        self.name = name
        self.metric_name = metric_name
        self.condition = condition
        self.threshold = threshold
        self.severity = severity
        self.message_template = message_template or (f"Alert: {metric_name} is {condition} {threshold}")

    def evaluate(self, value: float) -> bool:
        """Evaluate if the rule condition is met.

        Args:
            value: Current metric value.

        Returns:
            True if condition is met.
        """
        if self.condition == "gt" and value > self.threshold:
            return True
        elif self.condition == "lt" and value < self.threshold:
            return True
        elif self.condition == "eq" and value == self.threshold:
            return True
        elif self.condition == "gte" and value >= self.threshold:
            return True
        elif self.condition == "lte" and value <= self.threshold:
            return True
        return False

    def generate_message(self, value: float) -> str:
        """Generate alert message.

        Args:
            value: Current metric value.

        Returns:
            Formatted alert message.
        """
        try:
            return self.message_template.format(
                metric_name=self.metric_name,
                value=value,
                threshold=self.threshold,
                metric=self.metric_name,
            )
        except KeyError:
            # If template doesn't have placeholders, return as-is with value appended
            return f"{self.message_template} (value: {value}, threshold: {self.threshold})"


class AlertManager:
    """Manages alerts and notifications."""

    def __init__(self, config_file: str = "alert_config.json"):
        """Initialize alert manager.

        Args:
            config_file: Path to alert configuration file.
        """
        self.config_file = Path(config_file)
        self.alerts: list[Alert] = []
        self.rules: dict[str, AlertRule] = {}
        self.notification_handlers: dict[str, Callable] = {}
        self.alert_log_file = Path("/tmp/github_stars_alerts.json")

        self._register_default_handlers()
        self._load_rules()

    def _register_default_handlers(self) -> None:
        """Register default notification handlers."""
        self.notification_handlers["file"] = self._send_to_file
        self.notification_handlers["console"] = self._send_to_console
        self.notification_handlers["webhook"] = self._send_to_webhook

    def _send_to_file(self, alert: Alert) -> bool:
        """Send alert to log file.

        Args:
            alert: Alert to send.

        Returns:
            True if send successful.
        """
        try:
            self.alerts.append(alert)

            if len(self.alerts) > 100:
                self.alerts = self.alerts[-100:]

            alerts_data = [
                {
                    "timestamp": a.timestamp,
                    "datetime": a.datetime_str,
                    "type": a.alert_type,
                    "severity": a.severity,
                    "title": a.title,
                    "message": a.message,
                    "acknowledged": a.acknowledged,
                }
                for a in self.alerts
            ]

            with open(self.alert_log_file, "w") as f:
                json.dump(alerts_data, f, indent=2)

            return True

        except (IOError, OSError) as e:
            print(f"Failed to write alert to file: {e}")
            return False

    def _send_to_console(self, alert: Alert) -> bool:
        """Send alert to console.

        Args:
            alert: Alert to send.

        Returns:
            True if send successful.
        """
        severity_icon = {"low": "L", "medium": "M", "high": "H", "critical": "!"}.get(alert.severity, "?")

        print(f"[{alert.datetime_str}] [{severity_icon}] {alert.title}: {alert.message}")
        return True

    def _send_to_webhook(self, alert: Alert) -> bool:
        """Send alert to webhook URL.

        Args:
            alert: Alert to send.

        Returns:
            True if send successful.
        """
        import os

        webhook_url = os.environ.get("ALERT_WEBHOOK_URL")
        if not webhook_url:
            return False

        try:
            payload = {
                "timestamp": alert.datetime_str,
                "type": alert.alert_type,
                "severity": alert.severity,
                "title": alert.title,
                "message": alert.message,
                "metric": alert.metric_name,
                "value": alert.metric_value,
            }

            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                webhook_url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=10) as response:
                return response.status == 200

        except urllib.error.URLError as e:
            print(f"Failed to send webhook alert: {e}")
            return False
        except Exception as e:
            print(f"Failed to send webhook alert: {e}")
            return False

    def _send_to_email(self, alert: Alert) -> bool:
        """Send alert via email.

        Args:
            alert: Alert to send.

        Returns:
            True if send successful.
        """
        import os

        smtp_server = os.environ.get("SMTP_SERVER")
        smtp_port = int(os.environ.get("SMTP_PORT", "587"))
        smtp_user = os.environ.get("SMTP_USER") or ""
        smtp_password = os.environ.get("SMTP_PASSWORD") or ""
        email_to = os.environ.get("ALERT_EMAIL_TO")

        if not all([smtp_server, smtp_user, email_to]):
            return False

        try:
            msg = MIMEText(alert.message)
            msg["Subject"] = f"[{alert.severity.upper()}] {alert.title}"
            msg["From"] = smtp_user
            msg["To"] = email_to

            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.starttls()
                if smtp_password:
                    server.login(smtp_user, smtp_password)
                server.send_message(msg)

            return True

        except (smtplib.SMTPException, OSError) as e:
            print(f"Failed to send email alert: {e}")
            return False

    def add_rule(self, rule: AlertRule) -> None:
        """Add an alert rule.

        Args:
            rule: Alert rule to add.
        """
        self.rules[rule.name] = rule

    def check_rules(self, metrics: dict[str, float]) -> list[Alert]:
        """Check all rules against current metrics.

        Args:
            metrics: Dictionary of metric names to values.

        Returns:
            List of triggered alerts.
        """
        triggered_alerts: list[Alert] = []

        for rule_name, rule in self.rules.items():
            if rule.metric_name in metrics:
                value = metrics[rule.metric_name]
                if rule.evaluate(value):
                    alert = Alert(
                        alert_type="metric_threshold",
                        severity=rule.severity,
                        title=f"Alert: {rule.name}",
                        message=rule.generate_message(value),
                        metric_name=rule.metric_name,
                        metric_value=value,
                        threshold=rule.threshold,
                    )
                    triggered_alerts.append(alert)
                    self._notify(alert)

        return triggered_alerts

    def create_alert(
        self,
        alert_type: str,
        severity: str,
        title: str,
        message: str,
        metric_name: str = "",
        metric_value: float = 0.0,
        threshold: float = 0.0,
    ) -> Alert:
        """Create a new alert.

        Args:
            alert_type: Type of alert.
            severity: Alert severity.
            title: Alert title.
            message: Alert message.
            metric_name: Optional metric name.
            metric_value: Optional metric value.
            threshold: Optional threshold.

        Returns:
            Created Alert object.
        """
        alert = Alert(
            alert_type=alert_type,
            severity=severity,
            title=title,
            message=message,
            metric_name=metric_name,
            metric_value=metric_value,
            threshold=threshold,
        )

        self._notify(alert)
        return alert

    def _notify(self, alert: Alert) -> None:
        """Send alert to all configured notification handlers.

        Args:
            alert: Alert to notify.
        """
        # Always send to file and console
        self._send_to_file(alert)
        self._send_to_console(alert)

        # Send to email if configured
        if "email" in self.notification_handlers:
            self._send_to_email(alert)

        # Send to webhook if configured
        if "webhook" in self.notification_handlers:
            self._send_to_webhook(alert)

    def acknowledge_alert(self, alert_index: int) -> bool:
        """Acknowledge an alert.

        Args:
            alert_index: Index of the alert to acknowledge.

        Returns:
            True if acknowledged successfully.
        """
        if 0 <= alert_index < len(self.alerts):
            self.alerts[alert_index].acknowledged = True
            self.alerts[alert_index].acknowledged_at = time.time()
            return True
        return False

    def get_alerts(self, severity: Optional[str] = None) -> list[Alert]:
        """Get alerts, optionally filtered by severity.

        Args:
            severity: Optional severity filter.

        Returns:
            List of alerts.
        """
        if severity:
            return [a for a in self.alerts if a.severity == severity]
        return self.alerts

    def get_alert_summary(self) -> str:
        """Get alert summary.

        Returns:
            Formatted alert summary.
        """
        if not self.alerts:
            return "\nNo active alerts"

        summary = [
            "\n" + "=" * 60,
            "GitHub Stars Dashboard - Alert Summary",
            "=" * 60,
            f"\nTotal Alerts: {len(self.alerts)}",
            f"Unacknowledged: {len([a for a in self.alerts if not a.acknowledged])}",
            "",
        ]

        # Count by severity
        severity_counts: dict[str, int] = {}
        for alert in self.alerts:
            severity_counts[alert.severity] = severity_counts.get(alert.severity, 0) + 1

        for severity, count in severity_counts.items():
            summary.append(f"  {severity.capitalize()}: {count}")

        summary.append("\nRecent Alerts:")
        for alert in self.alerts[-10:]:
            status = "ACK" if alert.acknowledged else "NEW"
            summary.append(f"  [{status}] [{alert.severity}] {alert.title}: {alert.message[:50]}")

        summary.append("\n" + "=" * 60)

        return "\n".join(summary)

    def _load_rules(self) -> None:
        """Load alert rules from configuration file."""
        if not self.config_file.exists():
            self._create_default_rules()
            return

        try:
            with open(self.config_file, "r") as f:
                config = json.load(f)

            for rule_config in config.get("rules", []):
                rule = AlertRule(
                    name=rule_config["name"],
                    metric_name=rule_config["metric_name"],
                    condition=rule_config["condition"],
                    threshold=rule_config["threshold"],
                    severity=rule_config.get("severity", "medium"),
                    message_template=rule_config.get("message_template", ""),
                )
                self.add_rule(rule)

        except (IOError, OSError, json.JSONDecodeError, KeyError) as e:
            print(f"Failed to load alert rules: {e}")
            self._create_default_rules()

    def _create_default_rules(self) -> None:
        """Create default alert rules."""
        default_rules = [
            AlertRule(
                name="low_repository_count",
                metric_name="repository_count",
                condition="lt",
                threshold=1,
                severity="low",
                message_template="No repositories being tracked",
            ),
            AlertRule(
                name="high_sync_error_rate",
                metric_name="sync_errors",
                condition="gt",
                threshold=5,
                severity="high",
                message_template="High number of sync errors: {value}",
            ),
            AlertRule(
                name="database_unhealthy",
                metric_name="database_health",
                condition="eq",
                threshold=0,
                severity="critical",
                message_template="Database connection failed",
            ),
            AlertRule(
                name="api_down",
                metric_name="api_uptime",
                condition="lt",
                threshold=60,
                severity="critical",
                message_template="API has been down for less than 60 seconds",
            ),
        ]

        for rule in default_rules:
            self.add_rule(rule)


def main() -> None:
    """Main entry point for alert management script."""
    import argparse

    parser = argparse.ArgumentParser(description="Manage alerts for GitHub Stars Dashboard")
    parser.add_argument("-c", "--config", default="alert_config.json", help="Alert config file")
    parser.add_argument("--list", action="store_true", help="List all alerts")
    parser.add_argument("--summary", action="store_true", help="Show alert summary")
    parser.add_argument(
        "--trigger",
        type=str,
        help="Trigger a test alert",
    )
    parser.add_argument(
        "--severity",
        type=str,
        choices=["low", "medium", "high", "critical"],
        default="medium",
        help="Alert severity",
    )

    args = parser.parse_args()

    manager = AlertManager(config_file=args.config)

    if args.list:
        alerts = manager.get_alerts()
        for i, alert in enumerate(alerts):
            status = "ACK" if alert.acknowledged else "NEW"
            print(f"{i}: [{status}] [{alert.severity}] {alert.title}")
    elif args.summary:
        print(manager.get_alert_summary())
    elif args.trigger:
        alert = manager.create_alert(
            alert_type="manual",
            severity=args.severity,
            title="Test Alert",
            message=f"Test alert triggered: {args.trigger}",
        )
        print(f"Alert created: {alert.title}")
    else:
        print("Use --list, --summary, or --trigger to perform actions")


if __name__ == "__main__":
    main()
