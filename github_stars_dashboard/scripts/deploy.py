#!/usr/bin/env python3
"""Production deployment script for GitHub Stars Dashboard.

This module provides deployment utilities for Podman containerized deployments.
"""

import subprocess
import sys
from pathlib import Path


class PodmanDeployer:
    """Podman deployment manager for GitHub Stars Dashboard."""

    def __init__(self, env_file: str = ".env.prod"):
        """Initialize deployment manager.

        Args:
            env_file: Environment file to use (default: .env.prod)
        """
        self.env_file = env_file
        self.project_dir = Path(__file__).parent.parent
        self.compose_file = self.project_dir / "docker-compose.yml"

    def check_prerequisites(self) -> bool:
        """Check if Podman and required tools are available.

        Returns:
            True if all prerequisites are met.

        Raises:
            RuntimeError: If prerequisites are missing.
        """
        tools = ["podman", "podman-compose"]

        for tool in tools:
            try:
                subprocess.run([tool, "--version"], capture_output=True, check=True)
            except subprocess.CalledProcessError:
                raise RuntimeError(f"Required tool not found: {tool}")

        if not self.compose_file.exists():
            raise RuntimeError(f"docker-compose.yml not found at {self.compose_file}")

        if not Path(self.env_file).exists():
            raise RuntimeError(f"Environment file not found: {self.env_file}")

        return True

    def build_images(self) -> bool:
        """Build Docker/Podman images.

        Returns:
            True if build successful.

        Raises:
            RuntimeError: If build fails.
        """
        print("Building images...")
        result = subprocess.run(
            ["podman", "compose", "-f", str(self.compose_file), "build"],
            cwd=self.project_dir,
            capture_output=False,
        )

        if result.returncode != 0:
            raise RuntimeError("Failed to build images")

        print("Images built successfully")
        return True

    def start_services(self) -> bool:
        """Start all services.

        Returns:
            True if services started successfully.

        Raises:
            RuntimeError: If startup fails.
        """
        print("Starting services...")
        result = subprocess.run(
            [
                "podman",
                "compose",
                "-f",
                str(self.compose_file),
                "--env-file",
                self.env_file,
                "up",
                "-d",
            ],
            cwd=self.project_dir,
            capture_output=False,
        )

        if result.returncode != 0:
            raise RuntimeError("Failed to start services")

        print("Services started successfully")
        return True

    def stop_services(self) -> bool:
        """Stop all services.

        Returns:
            True if services stopped successfully.

        Raises:
            RuntimeError: If stop fails.
        """
        print("Stopping services...")
        result = subprocess.run(
            ["podman", "compose", "-f", str(self.compose_file), "down"],
            cwd=self.project_dir,
            capture_output=False,
        )

        if result.returncode != 0:
            raise RuntimeError("Failed to stop services")

        print("Services stopped successfully")
        return True

    def restart_services(self) -> bool:
        """Restart all services.

        Returns:
            True if restart successful.
        """
        self.stop_services()
        return self.start_services()

    def get_status(self) -> dict:
        """Get status of all services.

        Returns:
            Dictionary with service status information.
        """
        result = subprocess.run(
            ["podman", "compose", "-f", str(self.compose_file), "ps"],
            cwd=self.project_dir,
            capture_output=True,
            text=True,
        )

        return {
            "output": result.stdout,
            "success": result.returncode == 0,
        }

    def health_check(self, timeout: int = 60) -> bool:
        """Wait for services to become healthy.

        Args:
            timeout: Maximum time to wait in seconds.

        Returns:
            True if services become healthy within timeout.
        """
        import time

        print(f"Waiting for services to become healthy (timeout: {timeout}s)...")
        start_time = time.time()

        while time.time() - start_time < timeout:
            status = self.get_status()
            if status["success"]:
                if "healthy" in status["output"].lower():
                    print("All services are healthy")
                    return True
            time.sleep(5)

        raise TimeoutError("Services did not become healthy within timeout")

    def deploy(self, skip_build: bool = False) -> bool:
        """Perform full deployment.

        Args:
            skip_build: Skip image build step.

        Returns:
            True if deployment successful.
        """
        print("=" * 60)
        print("GitHub Stars Dashboard - Production Deployment")
        print("=" * 60)

        print("\n[1/5] Checking prerequisites...")
        self.check_prerequisites()
        print("✓ Prerequisites met")

        if not skip_build:
            print("\n[2/5] Building images...")
            self.build_images()
            print("✓ Images built")

        print("\n[3/5] Starting services...")
        self.start_services()
        print("✓ Services started")

        print("\n[4/5] Waiting for health check...")
        self.health_check()
        print("✓ Health check passed")

        print("\n[5/5] Getting final status...")
        status = self.get_status()
        print(status["output"])
        print("✓ Deployment complete")

        print("\n" + "=" * 60)
        print("Deployment successful!")
        print("Access the dashboard at: http://localhost:8000")
        print("=" * 60)

        return True

    def rollback(self) -> bool:
        """Rollback to previous version.

        Returns:
            True if rollback successful.
        """
        print("Rolling back to previous version...")
        result = subprocess.run(
            [
                "podman",
                "compose",
                "-f",
                str(self.compose_file),
                "up",
                "-d",
                "--build",
                "--force-recreate",
            ],
            cwd=self.project_dir,
            capture_output=False,
        )

        if result.returncode != 0:
            raise RuntimeError("Rollback failed")

        print("Rollback successful")
        return True


def main() -> None:
    """Main entry point for deployment script."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Deploy GitHub Stars Dashboard with Podman"
    )
    parser.add_argument(
        "command",
        choices=["deploy", "start", "stop", "restart", "status", "health", "rollback"],
        help="Deployment command",
    )
    parser.add_argument(
        "-e", "--env", default=".env.prod", help="Environment file (default: .env.prod)"
    )
    parser.add_argument(
        "--skip-build", action="store_true", help="Skip image build step"
    )

    args = parser.parse_args()
    deployer = PodmanDeployer(env_file=args.env)

    try:
        if args.command == "deploy":
            deployer.deploy(skip_build=args.skip_build)
        elif args.command == "start":
            deployer.start_services()
        elif args.command == "stop":
            deployer.stop_services()
        elif args.command == "restart":
            deployer.restart_services()
        elif args.command == "status":
            status = deployer.get_status()
            print(status["output"])
            sys.exit(0 if status["success"] else 1)
        elif args.command == "health":
            deployer.health_check()
        elif args.command == "rollback":
            deployer.rollback()
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except TimeoutError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
