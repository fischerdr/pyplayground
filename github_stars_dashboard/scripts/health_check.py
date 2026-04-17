#!/usr/bin/env python3
"""Health check monitoring for GitHub Stars Dashboard.

This module provides health check utilities for monitoring Podman containers.
"""

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.request import urlopen


class HealthChecker:
    """Health check monitoring for GitHub Stars Dashboard containers."""

    def __init__(self, compose_file: str = "docker-compose.yml"):
        """Initialize health checker.

        Args:
            compose_file: Path to docker-compose.yml file.
        """
        self.compose_file = Path(compose_file)
        self.project_dir = self.compose_file.parent

    def get_container_status(self) -> dict:
        """Get status of all containers.

        Returns:
            Dictionary with container status information.
        """
        result = subprocess.run(
            [
                "podman",
                "compose",
                "-f",
                str(self.compose_file),
                "ps",
                "--format",
                "json",
            ],
            cwd=self.project_dir,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            return {"success": False, "error": result.stderr}

        containers: list[dict[str, Any]] = []
        for line in result.stdout.strip().split("\n"):
            if line:
                try:
                    containers.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        return {"success": True, "containers": containers}

    def check_container_health(self, container_name: str) -> bool:
        """Check if a specific container is healthy.

        Args:
            container_name: Name of the container to check.

        Returns:
            True if container is healthy.
        """
        status = self.get_container_status()

        if not status["success"]:
            return False

        for container in status["containers"]:
            if container.get("NAME") == container_name:
                health = container.get("Health", "")
                status_str = container.get("STATUS", "")

                if "healthy" in health.lower() or "healthy" in status_str.lower():
                    return True
                elif "unhealthy" in health.lower() or "unhealthy" in status_str.lower():
                    return False

        return False

    def check_api_health(self, host: str = "localhost", port: int = 8000) -> bool:
        """Check API health endpoint.

        Args:
            host: API host address.
            port: API port number.

        Returns:
            True if API is healthy.
        """
        url = f"http://{host}:{port}/health"

        try:
            response = urlopen(url, timeout=10)
            status_val: int = response.status
            response.close()
            return status_val == 200
        except Exception:
            return False

    def run_health_checks(
        self, timeout: int = 120, interval: int = 5
    ) -> dict[str, Any]:
        """Run comprehensive health checks.

        Args:
            timeout: Maximum time to wait in seconds.
            interval: Check interval in seconds.

        Returns:
            Dictionary with health check results.
        """
        results: dict[str, Any] = {
            "started_at": time.time(),
            "containers": {},
            "api": False,
            "overall": False,
        }

        print("Running health checks...")
        start_time = time.time()

        while time.time() - start_time < timeout:
            # Check container health
            status = self.get_container_status()
            if status["success"]:
                for container in status["containers"]:
                    name = container.get("NAME", "unknown")
                    health = container.get("Health", "unknown")
                    status_str = container.get("STATUS", "unknown")

                    results["containers"][name] = {
                        "health": health,
                        "status": status_str,
                        "healthy": "healthy" in health.lower()
                        or "healthy" in status_str.lower(),
                    }

                    print(f"  {name}: {health} - {status_str}")

                # Check API health
                api_healthy = self.check_api_health()
                results["api"] = api_healthy
                print(f"  API: {'healthy' if api_healthy else 'unhealthy'}")

                # Check if all healthy
                all_healthy = (
                    all(c["healthy"] for c in results["containers"].values())
                    and api_healthy
                )

                if all_healthy and results["containers"]:
                    results["overall"] = True
                    results["completed_at"] = time.time()
                    return results

            time.sleep(interval)

        results["completed_at"] = time.time()
        results["timeout"] = True
        return results

    def generate_report(self) -> str:
        """Generate health check report.

        Returns:
            Formatted health check report string.
        """
        results = self.run_health_checks()

        report = ["\n" + "=" * 60, "Health Check Report", "=" * 60]

        if results.get("timeout"):
            report.append("\n⚠ WARNING: Health check timed out")

        report.append(f"\nCompleted at: {time.strftime('%Y-%m-%d %H:%M:%S')}")

        report.append("\nContainer Status:")
        for name, status in results["containers"].items():
            health_icon = "✓" if status["healthy"] else "✗"
            report.append(f"  {health_icon} {name}: {status['health']}")

        api_icon = "✓" if results["api"] else "✗"
        report.append(
            f"\n{api_icon} API Health: {'healthy' if results['api'] else 'unhealthy'}"
        )

        overall_icon = "✓" if results["overall"] else "✗"
        report.append(
            f"\n{overall_icon} Overall Status: {'healthy' if results['overall'] else 'unhealthy'}"
        )

        report.append("\n" + "=" * 60)

        return "\n".join(report)


def main() -> None:
    """Main entry point for health check script."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Health check monitoring for GitHub Stars Dashboard"
    )
    parser.add_argument(
        "-c", "--compose", default="docker-compose.yml", help="Compose file"
    )
    parser.add_argument(
        "-t", "--timeout", type=int, default=120, help="Timeout in seconds"
    )
    parser.add_argument(
        "-i", "--interval", type=int, default=5, help="Check interval in seconds"
    )
    parser.add_argument(
        "--report", action="store_true", help="Generate detailed report"
    )

    args = parser.parse_args()
    checker = HealthChecker(compose_file=args.compose)

    if args.report:
        print(checker.generate_report())
        sys.exit(
            0
            if checker.run_health_checks(args.timeout, args.interval)["overall"]
            else 1
        )
    else:
        results = checker.run_health_checks(args.timeout, args.interval)
        if results["overall"]:
            print("All health checks passed")
            sys.exit(0)
        else:
            print("Health checks failed")
            sys.exit(1)


if __name__ == "__main__":
    main()
