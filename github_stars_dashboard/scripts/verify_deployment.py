#!/usr/bin/env python3
"""Deployment verification script for GitHub Stars Dashboard.

This module provides verification utilities for production deployments.
"""

import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable


class DeploymentVerifier:
    """Deployment verification for GitHub Stars Dashboard."""

    def __init__(self, compose_file: str = "docker-compose.yml"):
        """Initialize deployment verifier.

        Args:
            compose_file: Path to docker-compose.yml file.
        """
        self.compose_file = Path(compose_file)
        self.project_dir = self.compose_file.parent

    def verify_podman_installed(self) -> bool:
        """Verify Podman is installed.

        Returns:
            True if Podman is installed.
        """
        try:
            result = subprocess.run(
                ["podman", "--version"],
                capture_output=True,
                text=True,
                check=True,
            )
            print(f"✓ Podman installed: {result.stdout.strip()}")
            return True
        except subprocess.CalledProcessError:
            print("✗ Podman not installed")
            return False

    def verify_podman_compose_installed(self) -> bool:
        """Verify podman-compose is installed.

        Returns:
            True if podman-compose is installed.
        """
        try:
            result = subprocess.run(
                ["podman-compose", "--version"],
                capture_output=True,
                text=True,
                check=True,
            )
            print(f"✓ podman-compose installed: {result.stdout.strip()}")
            return True
        except subprocess.CalledProcessError:
            print("✗ podman-compose not installed")
            return False

    def verify_compose_file(self) -> bool:
        """Verify docker-compose.yml exists and is valid.

        Returns:
            True if compose file is valid.
        """
        if not self.compose_file.exists():
            print(f"✗ docker-compose.yml not found at {self.compose_file}")
            return False

        try:
            subprocess.run(
                ["podman", "compose", "-f", str(self.compose_file), "config"],
                cwd=self.project_dir,
                capture_output=True,
                check=True,
            )
            print("✓ docker-compose.yml is valid")
            return True
        except subprocess.CalledProcessError:
            print("✗ docker-compose.yml is invalid")
            return False

    def verify_env_file(self, env_file: str = ".env.prod") -> bool:
        """Verify environment file exists and has required variables.

        Args:
            env_file: Path to environment file.

        Returns:
            True if environment file is valid.
        """
        env_path = self.project_dir / env_file

        if not env_path.exists():
            print(f"✗ Environment file not found: {env_path}")
            return False

        required_vars = ["GITHUB_TOKEN", "DATABASE_URL", "APP_PORT"]
        missing: list[str] = []

        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    for var in required_vars:
                        if var in line:
                            required_vars.remove(var)

        if required_vars:
            print(f"✗ Missing required variables: {', '.join(required_vars)}")
            return False

        print(f"✓ Environment file valid: {env_path}")
        return True

    def verify_containers_running(self) -> bool:
        """Verify containers are running.

        Returns:
            True if containers are running.
        """
        try:
            result = subprocess.run(
                ["podman", "compose", "-f", str(self.compose_file), "ps"],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                print("✗ Failed to get container status")
                return False

            if "No containers to show" in result.stdout:
                print("✗ No containers running")
                return False

            print("✓ Containers are running")
            print(result.stdout)
            return True
        except Exception as e:
            print(f"✗ Error checking containers: {e}")
            return False

    def verify_health_check(self, timeout: int = 30) -> bool:
        """Verify health check endpoint is responding.

        Args:
            timeout: Maximum time to wait in seconds.

        Returns:
            True if health check is passing.
        """
        import time

        try:
            # Get port from environment
            env_file = self.project_dir / ".env.prod"
            port = 8000
            if env_file.exists():
                with open(env_file, "r") as f:
                    for line in f:
                        if line.startswith("APP_PORT="):
                            port = int(line.split("=")[1].strip())
                            break

            start_time = time.time()
            while time.time() - start_time < timeout:
                url = f"http://localhost:{port}/health"
                try:
                    with urllib.request.urlopen(url, timeout=5) as response:
                        if response.status == 200:
                            print(f"✓ Health check passed: {url}")
                            return True
                except urllib.error.URLError:
                    pass
                time.sleep(2)

            print(f"✗ Health check timed out after {timeout}s")
            return False
        except Exception as e:
            print(f"✗ Error checking health: {e}")
            return False

    def verify_database_accessible(self) -> bool:
        """Verify database is accessible.

        Returns:
            True if database is accessible.
        """
        try:
            result = subprocess.run(
                [
                    "podman",
                    "exec",
                    "github-stars-dashboard",
                    "python",
                    "-c",
                    "from github_stars.database import get_db_session; print('OK')",
                ],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode == 0 and "OK" in result.stdout:
                print("✓ Database is accessible")
                return True
            else:
                print("✗ Database is not accessible")
                return False
        except Exception as e:
            print(f"✗ Error checking database: {e}")
            return False

    def verify_scheduler_running(self) -> bool:
        """Verify scheduler container is running.

        Returns:
            True if scheduler is running.
        """
        try:
            result = subprocess.run(
                ["podman", "ps", "--format", "{{.Names}}"],
                capture_output=True,
                text=True,
            )

            if "github-stars-scheduler" in result.stdout:
                print("✓ Scheduler container is running")
                return True
            else:
                print("✗ Scheduler container is not running")
                return False
        except Exception as e:
            print(f"✗ Error checking scheduler: {e}")
            return False

    def run_verification(self, env_file: str = ".env.prod") -> bool:
        """Run full deployment verification.

        Args:
            env_file: Environment file to check.

        Returns:
            True if all verifications pass.
        """
        print("=" * 60)
        print("GitHub Stars Dashboard - Deployment Verification")
        print("=" * 60)

        checks: list[tuple[str, Callable[[], bool]]] = [
            ("Podman installed", self.verify_podman_installed),
            ("podman-compose installed", self.verify_podman_compose_installed),
            ("docker-compose.yml valid", self.verify_compose_file),
            ("Environment file valid", lambda: self.verify_env_file(env_file)),
            ("Containers running", self.verify_containers_running),
            ("Health check", self.verify_health_check),
            ("Database accessible", self.verify_database_accessible),
            ("Scheduler running", self.verify_scheduler_running),
        ]

        results: list[tuple[str, bool]] = []
        for name, check_func in checks:
            try:
                result = check_func()
                results.append((name, result))
            except Exception as e:
                print(f"✗ {name} failed with error: {e}")
                results.append((name, False))

        print("\n" + "=" * 60)
        print("Verification Summary")
        print("=" * 60)

        all_passed = True
        for name, result in results:
            status = "✓ PASS" if result else "✗ FAIL"
            print(f"{status}: {name}")
            if not result:
                all_passed = False

        print("=" * 60)
        if all_passed:
            print("✓ All verification checks passed!")
        else:
            print("✗ Some verification checks failed")
        print("=" * 60)

        return all_passed


def main() -> None:
    """Main entry point for verification script."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Verify GitHub Stars Dashboard deployment"
    )
    parser.add_argument(
        "-c", "--compose", default="docker-compose.yml", help="Compose file"
    )
    parser.add_argument("-e", "--env", default=".env.prod", help="Environment file")

    args = parser.parse_args()
    verifier = DeploymentVerifier(compose_file=args.compose)

    success = verifier.run_verification(env_file=args.env)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
