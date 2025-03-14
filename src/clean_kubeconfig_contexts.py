import logging
import sys
from typing import Any, Dict, List, Set, Tuple

import click
import yaml
from kubernetes import config
from kubernetes.config.kube_config import KubeConfigLoader
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/clean_kubeconfig_contexts.log", mode="a"),
    ],
)
logger = logging.getLogger(__name__)
console = Console()


def get_kube_config_data() -> Dict[str, Any]:
    """Get kubeconfig data.
    
    Returns:
        Dict containing kubeconfig data
        
    Raises:
        SystemExit: If unable to load kubeconfig
    """
    try:
        # Load the kubeconfig file
        loader = KubeConfigLoader(config_file=config.KUBE_CONFIG_DEFAULT_LOCATION)
        config_dict = loader._config
        logger.debug("Successfully loaded kubeconfig")
        return config_dict
    except Exception as e:
        logger.error(f"Failed to load kubeconfig: {e}")
        sys.exit(1)


def display_contexts(verbose: bool = False) -> None:
    """List all available contexts in the kubeconfig.
    
    Args:
        verbose: If True, show additional details for each context
    """
    try:
        config_dict = get_kube_config_data()
        contexts = config_dict.get("contexts", [])
        current_context = config_dict.get("current-context", "")
        
        if not contexts:
            logger.info("No contexts found in kubeconfig.")
            return
        
        logger.info(f"Found {len(contexts)} contexts in kubeconfig:")
        
        # Create a rich table
        table = Table(title="Available Contexts")
        
        # Add columns based on verbosity
        table.add_column("Current", justify="center", style="cyan", no_wrap=True)
        table.add_column("Name", style="green")
        
        if verbose:
            table.add_column("Cluster", style="blue")
            table.add_column("User", style="magenta")
            table.add_column("Namespace", style="yellow")
        
        # Add rows
        for context in contexts:
            name = context["name"]
            current = "✓" if name == current_context else ""
            
            if verbose:
                cluster = context["context"].get("cluster", "")
                user = context["context"].get("user", "")
                namespace = context["context"].get("namespace", "default")
                table.add_row(current, name, cluster, user, namespace)
            else:
                table.add_row(current, name)
        
        # Print the table
        console.print(table)
        
        # Print current context info
        if current_context:
            console.print(f"Current context: [bold green]{current_context}[/bold green]")
        else:
            console.print("[yellow]No current context set[/yellow]")
        
    except Exception as e:
        logger.error(f"Failed to list contexts: {e}")
        sys.exit(1)


def show_current_context() -> None:
    """Display the current context and its details."""
    try:
        config_dict = get_kube_config_data()
        contexts = config_dict.get("contexts", [])
        current_context_name = config_dict.get("current-context", "")
        
        if not current_context_name:
            console.print("[yellow]No current context set in kubeconfig.[/yellow]")
            return
        
        # Find the current context
        current_context = None
        for context in contexts:
            if context["name"] == current_context_name:
                current_context = context
                break
        
        if not current_context:
            console.print(f"[yellow]Current context '[bold]{current_context_name}[/bold]' not found in contexts list.[/yellow]")
            return
        
        # Extract details
        cluster = current_context["context"].get("cluster", "")
        user = current_context["context"].get("user", "")
        namespace = current_context["context"].get("namespace", "default")
        
        # Create a panel with context details
        content = Text()
        content.append("Name:      ", style="dim")
        content.append(f"{current_context_name}\n", style="green bold")
        content.append("Cluster:   ", style="dim")
        content.append(f"{cluster}\n", style="blue")
        content.append("User:      ", style="dim")
        content.append(f"{user}\n", style="magenta")
        content.append("Namespace: ", style="dim")
        content.append(f"{namespace}", style="yellow")
        
        panel = Panel(
            content,
            title="Current Context",
            border_style="cyan",
            padding=(1, 2)
        )
        
        console.print(panel)
        
    except Exception as e:
        logger.error(f"Failed to show current context: {e}")
        sys.exit(1)


def set_kube_context(context_name: str, cluster: str, user: str, namespace: str) -> None:
    """Set a new kubeconfig context.
    
    Args:
        context_name: Name of the new context
        cluster: Name of the cluster
        user: Name of the user
        namespace: Target namespace
        
    Raises:
        SystemExit: If unable to set context
    """
    try:
        # Load the kubeconfig file
        config_file = config.KUBE_CONFIG_DEFAULT_LOCATION
        
        # Create a new context
        config_dict = get_kube_config_data()
        
        # Add the new context
        config_dict["contexts"].append({
            "name": context_name,
            "context": {
                "cluster": cluster,
                "user": user,
                "namespace": namespace
            }
        })
        
        # Set current-context
        config_dict["current-context"] = context_name
        
        # Write back to the kubeconfig file
        with open(config_file, "w") as f:
            yaml.dump(config_dict, f, default_flow_style=False)
        
        logger.info(f"Created consolidated context '{context_name}' with namespace '{namespace}'.")
    except Exception as e:
        logger.error(f"Failed to set context: {e}")
        sys.exit(1)


def delete_kube_context(context_name: str) -> bool:
    """Delete a kubeconfig context.
    
    Args:
        context_name: Name of the context to delete
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Load the kubeconfig file
        config_file = config.KUBE_CONFIG_DEFAULT_LOCATION
        config_dict = get_kube_config_data()
        
        # Remove the context
        contexts = config_dict["contexts"]
        config_dict["contexts"] = [c for c in contexts if c["name"] != context_name]
        
        # Write back to the kubeconfig file
        with open(config_file, "w") as f:
            yaml.dump(config_dict, f, default_flow_style=False)
        
        logger.info(f"Deleted context: {context_name}")
        return True
    except Exception as e:
        logger.warning(f"Failed to delete context {context_name}: {e}")
        return False


def delete_unused_cluster(cluster_name: str) -> bool:
    """Delete an unused cluster from kubeconfig.
    
    Args:
        cluster_name: Name of the cluster to delete
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Load the kubeconfig file
        config_file = config.KUBE_CONFIG_DEFAULT_LOCATION
        config_dict = get_kube_config_data()
        
        # Remove the cluster
        clusters = config_dict["clusters"]
        config_dict["clusters"] = [c for c in clusters if c["name"] != cluster_name]
        
        # Write back to the kubeconfig file
        with open(config_file, "w") as f:
            yaml.dump(config_dict, f, default_flow_style=False)
        
        logger.info(f"Removed unused cluster: {cluster_name}")
        return True
    except Exception as e:
        logger.warning(f"Failed to remove cluster {cluster_name}: {e}")
        return False


def delete_unused_user(user_name: str) -> bool:
    """Delete an unused user from kubeconfig.
    
    Args:
        user_name: Name of the user to delete
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Load the kubeconfig file
        config_file = config.KUBE_CONFIG_DEFAULT_LOCATION
        config_dict = get_kube_config_data()
        
        # Remove the user
        users = config_dict["users"]
        config_dict["users"] = [u for u in users if u["name"] != user_name]
        
        # Write back to the kubeconfig file
        with open(config_file, "w") as f:
            yaml.dump(config_dict, f, default_flow_style=False)
        
        logger.info(f"Removed unused user: {user_name}")
        return True
    except Exception as e:
        logger.warning(f"Failed to remove user {user_name}: {e}")
        return False


@click.command()
@click.option("--namespace", help="Target namespace for the consolidated context.")
@click.option("--context-name", help="Name of the new consolidated context.")
@click.option("--dry-run", is_flag=True, help="Show what would be changed without applying.")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging.")
@click.option("--list-contexts", is_flag=True, help="List all available contexts in the kubeconfig.")
@click.option("--show-current-context", is_flag=True, help="Show the current context and its details.")
def clean_kubeconfig(
    namespace: str, 
    context_name: str, 
    dry_run: bool, 
    verbose: bool,
    list_contexts: bool,
    show_current_context: bool
) -> None:
    """Consolidate and clean kubeconfig.
    
    This function identifies redundant contexts in the kubeconfig file and
    consolidates them into a single context with the specified namespace.
    It also removes unused clusters and users.
    
    Args:
        namespace: Target namespace for the consolidated context
        context_name: Name of the new consolidated context
        dry_run: If True, show what would be changed without applying
        verbose: If True, enable verbose logging
        list_contexts: If True, list all available contexts
        show_current_context: If True, show the current context and its details
    """
    if verbose:
        logger.setLevel(logging.DEBUG)
        logger.debug("Verbose logging enabled")
    
    # Handle list contexts option
    if list_contexts:
        display_contexts(verbose)
        return
    
    # Handle show current context option
    if show_current_context:
        show_current_context()
        return
    
    # Check required parameters for cleanup operation
    if namespace is None or context_name is None:
        logger.error("Both --namespace and --context-name are required for cleanup operation.")
        logger.info("Use --list-contexts to list available contexts or --show-current-context to show the current context.")
        sys.exit(1)
    
    logger.info("Starting kubeconfig cleanup process")
    if dry_run:
        logger.info("Running in dry-run mode - no changes will be applied")
    
    try:
        logger.info("Fetching existing kubeconfig contexts...")
        config_dict = get_kube_config_data()
        
        contexts = config_dict.get("contexts", [])
        current_context = config_dict.get("current-context", "")
        
        logger.debug(f"Found {len(contexts)} contexts")
        logger.debug(f"Current context: {current_context}")

        cluster_user_map: Dict[Tuple[str, str], str] = {}
        contexts_to_remove: List[str] = []

        # Identify redundant contexts
        for context in contexts:
            name = context["name"]
            cluster = context["context"]["cluster"]
            user = context["context"]["user"]

            key = (cluster, user)
            if key in cluster_user_map:
                contexts_to_remove.append(name)
                logger.debug(f"Found redundant context: {name} (cluster: {cluster}, user: {user})")
            else:
                cluster_user_map[key] = name
                logger.debug(f"Keeping context: {name} (cluster: {cluster}, user: {user})")

        if not cluster_user_map:
            logger.info("No contexts found in kubeconfig.")
            return

        if not contexts_to_remove:
            logger.info("No redundant contexts found.")
            return

        # Pick the first valid cluster/user pair to consolidate
        cluster, user = list(cluster_user_map.keys())[0]
        logger.info(f"Consolidating to cluster '{cluster}' and user '{user}'.")

        # Create a new consolidated context
        if not dry_run:
            set_kube_context(context_name, cluster, user, namespace)
        else:
            logger.info(f"Would create consolidated context '{context_name}' with namespace '{namespace}'.")

        # Remove redundant contexts
        for context in contexts_to_remove:
            if not dry_run:
                delete_kube_context(context)
            else:
                logger.info(f"Would delete context: {context}")

        # Clean up unused clusters and users
        logger.info("Identifying unused clusters and users...")
        
        # Reload config after potential deletions
        config_dict = get_kube_config_data()
        clusters = config_dict.get("clusters", [])
        cluster_names: Set[str] = {c["name"] for c in clusters}
        logger.debug(f"Found {len(clusters)} clusters")

        users = config_dict.get("users", [])
        user_names: Set[str] = {u["name"] for u in users}
        logger.debug(f"Found {len(users)} users")

        # Recalculate contexts after potential deletions
        contexts = config_dict.get("contexts", [])
        used_clusters: Set[str] = {
            c["context"]["cluster"] for c in contexts if c["name"] not in contexts_to_remove
        }
        used_users: Set[str] = {
            c["context"]["user"] for c in contexts if c["name"] not in contexts_to_remove
        }

        unused_clusters = cluster_names - used_clusters
        unused_users = user_names - used_users

        logger.debug(f"Found {len(unused_clusters)} unused clusters")
        logger.debug(f"Found {len(unused_users)} unused users")

        for cluster in unused_clusters:
            if not dry_run:
                delete_unused_cluster(cluster)
            else:
                logger.info(f"Would remove unused cluster: {cluster}")

        for user in unused_users:
            if not dry_run:
                delete_unused_user(user)
            else:
                logger.info(f"Would remove unused user: {user}")

        logger.info("Kubeconfig cleanup complete.")
    except Exception as e:
        logger.error(f"Unexpected error during kubeconfig cleanup: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    clean_kubeconfig()
