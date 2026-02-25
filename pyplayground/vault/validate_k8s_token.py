#! /usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validates a Kubernetes service account token using the TokenReview API.

Usage:
    python pyplayground/k8s/validate_k8s_token.py \
        --namespace <namespace> \
        --service-account <service-account> \
        --reviewer-namespace <reviewer-namespace> \
        --reviewer-service-account <reviewer-service-account> \
        --pre-flight-checks \
        --no-verify-ssl \
        --debug

Arguments:
    namespace: The namespace of the service account.
    service-account: The name of the service account.
    reviewer-namespace: The namespace of the reviewer service account.
    reviewer-service-account: The name of the reviewer service account.
    pre-flight-checks: Perform RBAC pre-flight checks before attempting token review.
    no-verify-ssl: Disable SSL verification for the Kubernetes API.
    debug: Enable debug logging.
"""

import json
import logging
import os
import sys

import click
from kubernetes import client
from kubernetes.client.rest import ApiException
from rich.console import Console

# Add project root to path to allow imports from pyplayground
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, project_root)

from pyplayground.utils.k8s_utils import get_service_account_jwt, load_kube_config_auto
from pyplayground.utils.logging_utils import setup_logging
from pyplayground.utils.vault_utils import log_jwt_payload

logger = logging.getLogger(__name__)


def _check_service_account_exists(core_v1_api, namespace, sa_name, console):
    """Checks if the specified ServiceAccount exists."""
    console.print(f"  Verifying ServiceAccount '[cyan]{sa_name}[/cyan]' in namespace '[cyan]{namespace}[/cyan]'...")
    try:
        core_v1_api.read_namespaced_service_account(name=sa_name, namespace=namespace)
        console.print("  [green]✔ OK:[/green] ServiceAccount exists.")
        return True
    except ApiException as e:
        if e.status == 404:
            console.print(f"  [red]✖ FAIL:[/red] ServiceAccount '[bold]{sa_name}[/bold]' not found in namespace '[bold]{namespace}[/bold]'.")
        else:
            console.print(f"  [red]✖ FAIL:[/red] API error checking ServiceAccount: {e.reason}")
        return False


def _check_auth_delegator_binding(rbac_v1_api, namespace, sa_name, console):
    """Checks if the ServiceAccount is bound to the system:auth-delegator ClusterRole."""
    console.print(f"  Checking ClusterRoleBindings for '[cyan]{sa_name}[/cyan]'...")
    try:
        bindings = rbac_v1_api.list_cluster_role_binding()
        found_binding = False
        is_delegator = False
        for binding in bindings.items:
            if binding.subjects:
                for subject in binding.subjects:
                    if subject.kind == "ServiceAccount" and subject.name == sa_name and subject.namespace == namespace:
                        role_name = binding.role_ref.name
                        console.print(f"    [green]Found binding:[/green] '{binding.metadata.name}' -> grants ClusterRole -> '[bold]{role_name}[/bold]'")
                        found_binding = True
                        if role_name == "system:auth-delegator":
                            is_delegator = True

        if not found_binding:
            console.print("  [red]✖ FAIL:[/red] No ClusterRoleBinding found for this ServiceAccount.")
            return False

        if is_delegator:
            console.print("  [green]✔ OK:[/green] ServiceAccount is correctly bound to 'system:auth-delegator'.")
        else:
            console.print("  [red]✖ FAIL:[/red] ServiceAccount is NOT bound to 'system:auth-delegator'. This is required for TokenReview.")
        return is_delegator

    except ApiException as e:
        console.print(f"  [red]✖ FAIL:[/red] API error checking ClusterRoleBindings: {e.reason}")
        return False


def _run_pre_flight_checks(
    console: Console,
    core_v1_api,
    rbac_v1_api,
    namespace: str,
    sa_name: str,
    reviewer_namespace: str,
    reviewer_sa_name: str,
):
    """Runs all pre-flight RBAC checks."""
    console.print("\n[bold]--- Running Pre-flight RBAC Checks ---[/bold]")
    sa_to_check_ns = reviewer_namespace or namespace
    sa_to_check_name = reviewer_sa_name or sa_name

    console.print(f"Checking permissions for reviewer: [bold cyan]{sa_to_check_ns}/{sa_to_check_name}[/bold cyan]")

    sa_exists = _check_service_account_exists(core_v1_api, sa_to_check_ns, sa_to_check_name, console)
    if not sa_exists:
        sys.exit(1)

    binding_ok = _check_auth_delegator_binding(rbac_v1_api, sa_to_check_ns, sa_to_check_name, console)
    if not binding_ok:
        sys.exit(1)

    console.print("[bold]--- Pre-flight Checks Complete ---[/bold]")


def _setup_reviewer_client(console: Console, core_v1_api, reviewer_namespace: str, reviewer_sa_name: str):
    """Configures and returns a Kubernetes client authenticated as the reviewer."""
    console.print(f"\n[bold magenta]Reviewer Mode:[/bold magenta] Authenticating as reviewer " f"[cyan]{reviewer_sa_name}[/cyan] in namespace [cyan]{reviewer_namespace}[/cyan].")
    reviewer_jwt = get_service_account_jwt(reviewer_namespace, reviewer_sa_name, v1_client=core_v1_api)
    if not reviewer_jwt:
        console.print("[red]Error: Could not retrieve JWT for reviewer service account. " "Cannot proceed.[/red]")
        sys.exit(1)

    logger.debug("Successfully retrieved JWT for reviewer.")

    # Create a new client configuration authenticated with the reviewer's token
    reviewer_config = client.Configuration.get_default_copy()
    reviewer_config.api_key["authorization"] = reviewer_jwt
    reviewer_config.api_key_prefix["authorization"] = "Bearer"

    # This auth client will act AS the reviewer
    auth_v1_client = client.AuthenticationV1Api(client.ApiClient(reviewer_config))
    console.print("[green]Successfully configured client to act as the reviewer.[/green]")
    return auth_v1_client


def _handle_api_exception(e: ApiException, console: Console, debug: bool):
    """Handles Kubernetes API exceptions with detailed, user-friendly messages."""
    console.print("[red]Error: A Kubernetes API call failed.[/red]")
    if e.status == 404:
        console.print("  [bold]Reason:[/bold] Not Found. The namespace or service account may not exist.")
    elif e.status == 403:
        console.print("  [bold]Reason:[/bold] Forbidden. The current user/service account lacks permissions.")
        console.print("  Check RBAC rules for 'secrets' (list) and 'tokenreviews' (create).")
    else:
        console.print(f"  [bold]Status:[/bold] {e.status}")
        console.print(f"  [bold]Reason:[/bold] {e.reason}")
    logger.error(f"API Exception: {e.body}", exc_info=debug)
    sys.exit(1)


def _display_token_review_status(status, console: Console, review_response=None, debug: bool = False):
    """Displays the results of the token review."""
    if debug and review_response:
        console.print("\n[bold yellow]--- TokenReview API Response ---[/bold yellow]")
        # Convert the Kubernetes object to a dict, then to pretty-printed JSON
        from kubernetes.client.api_client import ApiClient

        api_client = ApiClient()
        response_dict = api_client.sanitize_for_serialization(review_response)

        # Using rich.syntax.Syntax for beautiful JSON rendering
        from rich.syntax import Syntax

        pretty_json = json.dumps(response_dict, indent=2)
        console.print(Syntax(pretty_json, "json", theme="solarized-dark", line_numbers=True))
        console.print("[bold yellow]--- End of API Response ---[/bold yellow]\n")

    if status.authenticated:
        console.print("[green]✔ Token is valid.[/green]")
        console.print(f"  [bold]Username:[/bold] {status.user.username}")
        console.print(f"  [bold]UID:[/bold] {status.user.uid}")
        if status.user.groups:
            groups = ", ".join(status.user.groups)
            console.print(f"  [bold]Groups:[/bold] {groups}")
        sys.exit(0)
    else:
        console.print("[red]✖ Token is invalid or expired.[/red]")
        if status.error:
            console.print(f"  [bold]Reason:[/bold] {status.error}")
        sys.exit(1)


@click.command()
@click.option(
    "--namespace",
    required=True,
    help="The namespace of the service account.",
)
@click.option(
    "--service-account",
    "service_account_name",
    required=True,
    help="The name of the service account.",
)
@click.option(
    "--reviewer-namespace",
    help="(Optional) The namespace of the service account that will perform the token review.",
)
@click.option(
    "--reviewer-service-account",
    help="(Optional) The name of the service account that will perform the token review.",
)
@click.option(
    "--pre-flight-checks",
    is_flag=True,
    default=False,
    help="Perform RBAC pre-flight checks before attempting token review.",
)
@click.option(
    "--no-verify-ssl",
    is_flag=True,
    default=False,
    help="Disable SSL verification for the Kubernetes API.",
)
@click.option(
    "--debug",
    is_flag=True,
    default=False,
    help="Enable debug logging.",
)
def validate_k8s_token(
    namespace: str,
    service_account_name: str,
    no_verify_ssl: bool,
    debug: bool,
    reviewer_namespace: str,
    reviewer_service_account: str,
    pre_flight_checks: bool,
):
    """Retrieves an existing service account token and validates it."""
    console = Console()
    script_base_name = os.path.basename(__file__).replace(".py", "")
    log_level = logging.DEBUG if debug else logging.INFO
    setup_logging(level=log_level, script_name=script_base_name)

    logger.debug("Starting token validation process.")

    try:
        if not load_kube_config_auto(verify_ssl=not no_verify_ssl):
            console.print("[red]Error: Failed to load Kubernetes configuration.[/red]")
            sys.exit(1)

        # Clients using ambient credentials (kubeconfig or pod's SA)
        initial_core_v1_client = client.CoreV1Api()
        initial_rbac_v1_client = client.RbacAuthorizationV1Api()
        auth_v1_client = client.AuthenticationV1Api()  # Default client

        if pre_flight_checks:
            _run_pre_flight_checks(
                console,
                initial_core_v1_client,
                initial_rbac_v1_client,
                namespace,
                service_account_name,
                reviewer_namespace,
                reviewer_service_account,
            )

        # If a reviewer SA is specified, create a dedicated client for it
        if reviewer_namespace and reviewer_service_account:
            auth_v1_client = _setup_reviewer_client(
                console,
                initial_core_v1_client,
                reviewer_namespace,
                reviewer_service_account,
            )

        # 1. Retrieve the JWT for the TARGET service account using the initial client
        console.print(f"\nAttempting to retrieve token for target service account " f"[cyan]{service_account_name}[/cyan] in namespace [cyan]{namespace}[/cyan]...")

        jwt = get_service_account_jwt(namespace, service_account_name, v1_client=initial_core_v1_client)
        if not jwt:
            console.print(f"[red]Error: Failed to retrieve a JWT for '{service_account_name}'.[/red]")
            console.print("  [yellow]Note:[/yellow] Kubernetes v1.24+ no longer creates secrets for " "service accounts automatically.")
            console.print("  Check if a token secret exists and is correctly annotated for this service account.")
            sys.exit(1)

        logger.debug("Successfully retrieved JWT from a service account secret.")
        if debug:
            console.print("\n[bold yellow]--- Decoded JWT Payload ---[/bold yellow]")
            log_jwt_payload(jwt)  # Use the existing helper to log decoded JWT
            console.print("[bold yellow]--- End of JWT Payload ---[/bold yellow]\n")

        # 2. Call the TokenReview API
        console.print("Calling TokenReview API to validate the retrieved token...")
        token_review_spec = client.V1TokenReviewSpec(token=jwt)
        token_review = client.V1TokenReview(spec=token_review_spec)
        # Use the appropriate client (default or reviewer) to make the call
        review_response = auth_v1_client.create_token_review(token_review)

        _display_token_review_status(review_response.status, console, review_response, debug)

    except ApiException as e:
        _handle_api_exception(e, console, debug)
    except Exception as e:
        console.print(f"[red]An unexpected error occurred: {e}[/red]")
        logger.error("An unexpected error occurred.", exc_info=debug)
        sys.exit(1)


if __name__ == "__main__":
    validate_k8s_token()
