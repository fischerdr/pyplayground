import threading
import time

import requests


class KeycloakClient:
    def __init__(self, keycloak_url, realm, client_id, client_secret, username, password, duration=3600):
        self.keycloak_url = keycloak_url
        self.realm = realm
        self.client_id = client_id
        self.client_secret = client_secret
        self.username = username
        self.password = password
        self.duration = duration  # Token expiration duration in seconds
        self.access_token = None
        self.refresh_token = None
        self.token_expiration = None

        # Start the background thread for token refresh handling
        self.refresh_thread = threading.Thread(target=self._auto_refresh_token)
        self.refresh_thread.daemon = True  # Daemonize the thread so it runs in the background
        self.refresh_thread.start()

    def _get_token(self):
        """Obtain a new access token using the password grant type."""
        token_url = f"{self.keycloak_url}/realms/{self.realm}/protocol/openid-connect/token"
        
        payload = {
            'grant_type': 'password',  # Grant type is password
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'username': self.username,
            'password': self.password,
            'duration': self.duration  # Optionally, set the duration for the access token
        }

        try:
            response = requests.post(token_url, data=payload)

            if response.status_code == 200:
                token_data = response.json()
                self.access_token = token_data['access_token']
                self.refresh_token = token_data.get('refresh_token', None)  # refresh_token is optional for password grant
                self.token_expiration = time.time() + token_data['expires_in']
                print("Token obtained successfully.")
            else:
                print(f"Failed to get token: {response.status_code} - {response.text}")

        except requests.exceptions.RequestException as e:
            print(f"Error fetching token: {e}")

    def _refresh_token(self):
        """Refresh the access token using the refresh token."""
        if self.refresh_token:
            print("Refreshing token...")

            refresh_url = f"{self.keycloak_url}/realms/{self.realm}/protocol/openid-connect/token"
            payload = {
                'grant_type': 'refresh_token',
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'refresh_token': self.refresh_token
            }

            try:
                response = requests.post(refresh_url, data=payload)

                if response.status_code == 200:
                    token_data = response.json()
                    self.access_token = token_data['access_token']
                    self.refresh_token = token_data.get('refresh_token', self.refresh_token)  # Keep the existing refresh token
                    self.token_expiration = time.time() + token_data['expires_in']
                    print("Token refreshed successfully.")
                else:
                    print(f"Failed to refresh token: {response.status_code} - {response.text}")

            except requests.exceptions.RequestException as e:
                print(f"Error refreshing token: {e}")
        else:
            print("No refresh token available, fetching a new token.")
            self._get_token()

    def _auto_refresh_token(self):
        """Automatically refresh the token at least 30 seconds before it expires."""
        while True:
            if self.access_token is None or time.time() >= self.token_expiration - 30:
                self._refresh_token()
            time.sleep(10)  # Check every 10 seconds for token expiration

    def _get_headers(self):
        """Get request headers with the Bearer token."""
        if self.access_token is None or time.time() >= self.token_expiration - 30:
            self._refresh_token()

        return {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json'
        }

    def get(self, endpoint):
        """Send a GET request to Keycloak API."""
        url = f"{self.keycloak_url}/realms/{self.realm}/protocol/openid-connect/{endpoint}"
        headers = self._get_headers()
        try:
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                return response.json()
            else:
                print(f"GET request failed: {response.status_code} - {response.text}")
                return None
        except requests.exceptions.RequestException as e:
            print(f"Request failed: {e}")
            return None

    def post(self, endpoint, data=None):
        """Send a POST request to Keycloak API."""
        url = f"{self.keycloak_url}/realms/{self.realm}/protocol/openid-connect/{endpoint}"
        headers = self._get_headers()
        try:
            response = requests.post(url, json=data, headers=headers)
            if response.status_code == 200:
                return response.json()
            else:
                print(f"POST request failed: {response.status_code} - {response.text}")
                return None
        except requests.exceptions.RequestException as e:
            print(f"Request failed: {e}")
            return None

# Example usage
if __name__ == "__main__":
    keycloak_url = "https://keycloak.example.com"  # Replace with your Keycloak URL
    realm = "myrealm"  # Replace with your Keycloak realm
    client_id = "my-client"  # Replace with your Keycloak client ID
    client_secret = "my-client-secret"  # Replace with your Keycloak client secret
    username = "my-username"  # Replace with the username
    password = "my-password"  # Replace with the password
    duration = 3600  # Token duration in seconds (e.g., 1 hour)

    # Initialize the Keycloak client
    keycloak_client = KeycloakClient(keycloak_url, realm, client_id, client_secret, username, password, duration)

    # Example: Get information about the authenticated user (using the access token)
    user_info = keycloak_client.get("userinfo")
    if user_info:
        print("User Info:", user_info)

    # Example: Create a new user (using POST method)
    new_user = {
        "username": "newuser",
        "email": "newuser@example.com",
        "enabled": True,
        "firstName": "New",
        "lastName": "User"
    }
    user_creation_response = keycloak_client.post("users", data=new_user)
    if user_creation_response:
        print("User created:", user_creation_response)
