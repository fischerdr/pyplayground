import json
import logging
import os
from time import sleep

import click
import requests

# Configure logging
logging.basicConfig(
    filename="ansible_tower.log",
    level=logging.ERROR,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


@click.command()
@click.option("--tower-url", envvar="TOWER_URL", required=True, help="Ansible Tower/Controller URL")
@click.option("--token", envvar="TOWER_TOKEN", required=True, help="API Token for authentication")
@click.option("--template-name", required=True, help="Partial name of the job template")
@click.option("--inventory-name", required=True, help="Partial name of the inventory")
@click.option("--extra-vars", default="{}", help="Extra variables as JSON string")
@click.option(
    "--interactive",
    is_flag=True,
    help="Enable interactive mode for selecting templates and inventories",
)
@click.option("--output-file", default=None, help="File to save job output")
def run_job(tower_url, token, template_name, inventory_name, extra_vars, interactive, output_file):
    """
    Launch an Ansible Tower job template with specified parameters.
    """
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    def log_error(message):
        """Log an error message to the log file."""
        logging.error(message)
        print(f"Error: {message}")

    def search_resource_by_name(endpoint, partial_name):
        """Search for a resource by partial name."""
        url = f"{tower_url}/api/v2/{endpoint}/?name__icontains={partial_name}"
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            if data["count"] > 0:
                results = data["results"]
                print(f"Found {len(results)} {endpoint[:-1]}(s) matching '{partial_name}':")
                for idx, resource in enumerate(results):
                    print(f"[{idx + 1}] {resource['name']} (ID: {resource['id']})")
                return results
            else:
                print(f"No {endpoint[:-1]} found with partial name '{partial_name}'.")
                return None
        except requests.exceptions.RequestException as e:
            log_error(f"Failed to search {endpoint[:-1]}: {e}")
            return None

    def select_resource(resources, resource_type):
        """Allow the user to select a resource from the list."""
        if not resources:
            return None
        if len(resources) == 1:
            print(
                f"Automatically selecting {resource_type}: {resources[0]['name']} (ID: {resources[0]['id']})"
            )
            return resources[0]["id"]
        while True:
            try:
                selection = int(input(f"Select a {resource_type} by number (1-{len(resources)}): "))
                if 1 <= selection <= len(resources):
                    selected = resources[selection - 1]
                    print(f"Selected {resource_type}: {selected['name']} (ID: {selected['id']})")
                    return selected["id"]
                else:
                    print(
                        f"Invalid selection. Please choose a number between 1 and {len(resources)}."
                    )
            except ValueError:
                print("Invalid input. Please enter a number.")

    def launch_job_template(job_template_id, inventory_id=None, extra_vars=None):
        """Launch an Ansible Tower job template."""
        url = f"{tower_url}/api/v2/job_templates/{job_template_id}/launch/"

        payload = {}
        if inventory_id:
            payload["inventory"] = inventory_id
        if extra_vars:
            payload["extra_vars"] = json.loads(extra_vars)

        try:
            response = requests.post(url, headers=headers, json=payload)
            response.raise_for_status()
            job = response.json()
            print(f"Job launched successfully. Job ID: {job['id']}")
            return job
        except requests.exceptions.RequestException as e:
            log_error(f"Failed to launch job: {e}")
            return None

    def monitor_job_status(job_id):
        """Monitor the status of a running job and return its output."""
        url = f"{tower_url}/api/v2/jobs/{job_id}/"

        while True:
            try:
                response = requests.get(url, headers=headers)
                response.raise_for_status()
                job = response.json()
                status = job["status"]
                print(f"Job status: {status}")
                if status in ["successful", "failed", "error", "canceled"]:
                    return job
                sleep(5)  # Poll every 5 seconds
            except requests.exceptions.RequestException as e:
                log_error(f"Failed to fetch job status: {e}")
                break

    def fetch_job_events(job_id):
        """Fetch the tasks and their results for the completed job."""
        url = f"{tower_url}/api/v2/jobs/{job_id}/job_events/"
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            events = response.json()["results"]
            for event in events:
                if event["event"] == "playbook_on_task_start":
                    print(f"Task: {event['task']}")
                elif event["event"] == "runner_on_failed":
                    # Log and display failed task details
                    failed_details = (
                        "\n--- Failed Task Details ---\n"
                        f"Task: {event['task']}\n"
                        f"Host: {event['host']}\n"
                        f"Message: {event['stdout']}\n"
                        "----------------------------\n"
                    )
                    print(failed_details)
                    logging.error(failed_details.strip())
                elif event["event"] == "runner_on_ok":
                    print(f"  Host: {event['host']} - Success")
        except requests.exceptions.RequestException as e:
            log_error(f"Failed to fetch job events: {e}")

    def fetch_job_output(job_id):
        """Fetch the output of a completed job."""
        url = f"{tower_url}/api/v2/jobs/{job_id}/stdout/"
        try:
            response = requests.get(url, headers=headers, params={"format": "txt"})
            response.raise_for_status()
            return response.text
        except requests.exceptions.RequestException as e:
            log_error(f"Failed to fetch job output: {e}")
            return None

    # Search for the job template and inventory using partial names
    job_templates = search_resource_by_name("job_templates", template_name)
    inventories = search_resource_by_name("inventories", inventory_name)

    if interactive:
        # Allow user to select from multiple matches
        job_template_id = select_resource(job_templates, "job template") if job_templates else None
        inventory_id = select_resource(inventories, "inventory") if inventories else None
    else:
        # Automatically select the first match
        job_template_id = job_templates[0]["id"] if job_templates else None
        inventory_id = inventories[0]["id"] if inventories else None

    # Launch the job if both job template and inventory are found
    if job_template_id and inventory_id:
        job = launch_job_template(job_template_id, inventory_id=inventory_id, extra_vars=extra_vars)
        if job:
            final_job = monitor_job_status(job["id"])
            if final_job:
                fetch_job_events(final_job["id"])
                if output_file:
                    output = fetch_job_output(final_job["id"])
                    if output:
                        with open(output_file, "w") as f:
                            f.write(output)
                        print(f"Job output saved to {output_file}")


if __name__ == "__main__":
    run_job()
