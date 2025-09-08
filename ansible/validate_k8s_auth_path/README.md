# Ansible Playbook: Validate Vault Kubernetes Auth Path

This Ansible playbook provides an equivalent to the Python script `validate_k8s_auth_path.py`. It validates that a Vault Kubernetes authentication path is correctly configured to communicate with its designated Kubernetes cluster by performing a `TokenReview` API call.

## How it Works

The playbook performs the following steps:
1.  **Connects to Vault**: Reads the configuration for a specified Kubernetes auth path from a Vault Enterprise namespace.
2.  **Extracts K8s Config**: Retrieves the target Kubernetes API server URL and its CA certificate from the Vault configuration.
3.  **Fetches SA Tokens**: Uses your local `kubeconfig` to connect to your currently active Kubernetes cluster to get JWTs for a "target" service account (the one to be validated) and a "reviewer" service account (the one performing the validation).
4.  **Performs TokenReview**: Makes a `TokenReview` API call directly to the Kubernetes cluster specified in Vault, authenticating with the reviewer's JWT and trusting the provided CA certificate.
5.  **Displays Results**: Reports whether the `TokenReview` was successful and the token was authenticated.

## Prerequisites

1.  **Ansible and Collections**: You need Ansible installed, along with the required collections.
    ```bash
    # Install Ansible (if not already installed)
    python -m pip install ansible

    # Install required collections from this directory
    ansible-galaxy collection install -r requirements.yml
    ```

2.  **Vault Authentication**: The playbook authenticates to Vault using a token. Ensure the following environment variables are set:
    ```bash
    export VAULT_ADDR="https://your-vault-address:8200"
    export VAULT_TOKEN="s.yourvaulttoken"
    ```

3.  **Kubernetes `kubeconfig`**: You must have a working `kubeconfig` file (`~/.kube/config` or specified via `KUBECONFIG`) that allows you to read Service Accounts and Secrets from the namespaces you will be testing.

## How to Run the Playbook

You can run the playbook and provide the required parameters as extra variables (`-e`) on the command line. This is the recommended method for automation.

```bash
ansible-playbook playbook.yml \
  -e "vault_namespace=infra/prod" \
  -e "auth_path=k8s-prod-use1-a-1" \
  -e "target_namespace=my-app-prod" \
  -e "target_service_account=my-app-sa"
```

### All Variables

-   `vault_namespace` ( **Required** ): The Vault Enterprise namespace where the auth path resides.
-   `auth_path` ( **Required** ): The specific Kubernetes auth path to validate (e.g., `k8s-prod-cluster-1`).
-   `target_namespace` ( **Required** ): The Kubernetes namespace of the service account to test.
-   `target_service_account` ( **Required** ): The name of the service account whose token will be validated.
-   `reviewer_namespace` ( *Optional* ): The namespace of the SA performing the `TokenReview`. Defaults to `target_namespace`.
-   `reviewer_service_account` ( *Optional* ): The name of the SA performing the `TokenReview`. Defaults to `target_service_account`.
-   `no_verify_ssl` ( *Optional* ): Set to `true` to disable SSL certificate verification when making the `TokenReview` API call to the target cluster. Defaults to `false`.
-   `debug_output` ( *Optional* ): Set to `true` to see verbose output from the playbook tasks. Defaults to `false`.
