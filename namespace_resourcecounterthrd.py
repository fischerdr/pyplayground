import click
import csv
import logging
import asyncio
from kubernetes_asyncio import client, config
from collections import defaultdict
from filelock import FileLock
from concurrent.futures import ThreadPoolExecutor, as_completed

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

async def count_resources(namespace, include_crds, semaphore):
    async with semaphore:
        # API Clients
        v1 = client.CoreV1Api()
        apps_v1 = client.AppsV1Api()
        batch_v1 = client.BatchV1Api()
        custom_api = client.CustomObjectsApi()

        # Dictionary to store resource counts for the namespace
        namespace_resources = defaultdict(int)

        try:
            # Count core resources
            namespace_resources['Pods'] = len((await v1.list_namespaced_pod(namespace)).items)
            namespace_resources['Services'] = len((await v1.list_namespaced_service(namespace)).items)
            namespace_resources['ConfigMaps'] = len((await v1.list_namespaced_config_map(namespace)).items)
            namespace_resources['Secrets'] = len((await v1.list_namespaced_secret(namespace)).items)

            # Count apps resources
            namespace_resources['Deployments'] = len((await apps_v1.list_namespaced_deployment(namespace)).items)
            namespace_resources['ReplicaSets'] = len((await apps_v1.list_namespaced_replica_set(namespace)).items)
            namespace_resources['StatefulSets'] = len((await apps_v1.list_namespaced_stateful_set(namespace)).items)
            namespace_resources['DaemonSets'] = len((await apps_v1.list_namespaced_daemon_set(namespace)).items)

            # Count batch resources
            namespace_resources['Jobs'] = len((await batch_v1.list_namespaced_job(namespace)).items)
            namespace_resources['CronJobs'] = len((await batch_v1.list_namespaced_cron_job(namespace)).items)

            # Optionally count custom resources (CRDs)
            if include_crds:
                crd_api = client.ApiextensionsV1Api()
                crds = (await crd_api.list_custom_resource_definition()).items

                for crd in crds:
                    group = crd.spec.group
                    versions = crd.spec.versions
                    plural = crd.spec.names.plural

                    # Use the first version for simplicity
                    version = versions[0].name
                    try:
                        custom_objects = await custom_api.list_namespaced_custom_object(
                            group=group,
                            version=version,
                            namespace=namespace,
                            plural=plural
                        )
                        # Count the instances of this custom resource
                        namespace_resources[crd.spec.names.kind] += len(custom_objects['items'])
                    except client.exceptions.ApiException as e:
                        logging.error(f"Could not retrieve custom resources for {crd.spec.names.kind} in namespace {namespace}: {e}")
        except client.exceptions.ApiException as e:
            logging.error(f"Error counting resources in namespace {namespace}: {e}")

        return {namespace: namespace_resources}

@click.command()
@click.option('--namespace', default=None, help="Specify a namespace (defaults to all namespaces).")
@click.option('--include-crds', is_flag=True, help="Include custom resources (CRDs) in the count.")
@click.option('--output-file', type=click.Path(), default="output.csv", help="Path to output CSV file.")
@click.option('--num-threads', default=5, help="Number of threads for concurrent processing.")
@click.option('--connection-pool-size', default=5, help="Number of connections in the pool.")
def main(namespace, include_crds, output_file, num_threads, connection_pool_size):
    # Load the kubeconfig
    config.load_kube_config()  # For use outside a cluster
    # config.load_incluster_config()  # Uncomment this line if running inside a cluster

    async def process_namespaces():
        v1 = client.CoreV1Api()

        # Get list of namespaces to search
        if namespace:
            namespaces = [namespace]
        else:
            namespaces = [ns.metadata.name for ns in (await v1.list_namespace()).items]

        # Semaphore to limit concurrent connections
        semaphore = asyncio.Semaphore(connection_pool_size)

        # Create tasks with the specified number of threads
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            loop = asyncio.get_event_loop()
            tasks = [
                loop.run_in_executor(executor, asyncio.ensure_future, count_resources(ns, include_crds, semaphore))
                for ns in namespaces
            ]

            # Gather results
            all_resources = []
            for task in as_completed(tasks):
                result = await task
                all_resources.append(result)

        # Write output to CSV with file locking
        lock = FileLock(f"{output_file}.lock")
        with lock:
            with open(output_file, mode="w", newline="") as csvfile:
                fieldnames = ["Namespace"] + list(all_resources[0][namespace].keys())
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                for resource_data in all_resources:
                    namespace, resources = next(iter(resource_data.items()))
                    writer.writerow({"Namespace": namespace, **resources})
                    logging.info(f"Wrote resources for namespace: {namespace}")

    asyncio.run(process_namespaces())

if __name__ == "__main__":
    main()
