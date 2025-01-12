import hvac
import os
import click


@click.command()
@click.option('--url', default=None, help='Vault server URL')
@click.option('--token', default=None, help='Vault token or path to token file')
@click.option('--username', default=None, help='Username for Vault login')
@click.option('--path', default=None, help='Starting path for traversal')
@click.option('--namespace', default=None, help='Vault namespace')
def main(url, token, username, path, namespace):
    # Setup Vault client
    client = setup_vault_client(url, token, username, namespace)
    if not client:
        return

    if path:
        vaults = [os.path.join(path.rstrip('/'), '')]
    else:
        try:
            vaults = [mount for mount, details in client.sys.list_mounted_secrets_engines()['data'].items()
                      if details['type'] == 'kv']
        except Exception as e:
            click.echo(f"Error listing secret engines: {str(e)}", err=True)
            return

    for vault in vaults:
        traverse(client, vault)


def setup_vault_client(url, token, username, namespace):
    if url is None:
        url = os.environ.get('VAULT_ADDR')
    if token is None:
        token = os.environ.get('VAULT_TOKEN')
    if namespace is None:
        namespace = os.environ.get('VAULT_NAMESPACE')
    
    if not url:
        click.echo("Vault URL must be provided either as an argument or in the VAULT_ADDR environment variable.", err=True)
        return None

    try:
        client = hvac.Client(url=url, namespace=namespace)

        if token:
            if os.path.isfile(token):
                with open(token, 'r') as f:
                    token = f.read().strip()
            client.token = token
        elif username:
            # Prompt for password securely
            password = click.prompt("Enter your Vault password", hide_input=True)
            # Attempt to login and get a token
            login_response = client.auth.userpass.login(username, password)
            client.token = login_response['auth']['client_token']
        else:
            click.echo("Either a token or username must be provided.", err=True)
            return None

        if not client.is_authenticated():
            click.echo("Failed to authenticate with Vault", err=True)
            return None
        
        return client
    except Exception as e:
        click.echo(f"Error connecting to Vault: {str(e)}", err=True)
        return None


def traverse(client, path):
    try:
        secrets = client.secrets.kv.v2.list_secrets(path=path)['data']['keys']
    except hvac.exceptions.InvalidPath:
        return
    except Exception as e:
        click.echo(f"Error listing secrets at {path}: {str(e)}", err=True)
        return

    for secret in secrets:
        full_path = os.path.join(path, secret)
        if secret.endswith('/'):
            traverse(client, full_path)
        else:
            click.echo(full_path)

if __name__ == "__main__":
    main()