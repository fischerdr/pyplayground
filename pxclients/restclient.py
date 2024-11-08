import requests
import time

class RestAPIClient:
    def __init__(self, base_url, auth_url, client_id, client_secret):
        self.base_url = base_url
        self.auth_url = auth_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.token = None
        self.token_expiration = None

    def _get_auth_token(self):
        """Obtain a new authentication token using client credentials."""
        auth_data = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'grant_type': 'client_credentials'
        }

        response = requests.post(self.auth_url, data=auth_data)

        if response.status_code == 200:
            auth_response = response.json()
            self.token = auth_response['access_token']
            # Assume the API gives an expiration time in seconds
            self.token_expiration = time.time() + auth_response['expires_in']
            print("Token obtained successfully.")
        else:
            print(f"Error fetching token: {response.status_code}, {response.text}")
            self.token = None
            self.token_expiration = None

    def _refresh_token(self):
        """Refresh the token if it's expired."""
        print("Refreshing the token...")
        self._get_auth_token()

    def _get_headers(self):
        """Get the headers with the authorization token."""
        if self.token is None or time.time() >= self.token_expiration:
            self._refresh_token()

        return {
            'Authorization': f'Bearer {self.token}',
            'Content-Type': 'application/json'
        }

    def _send_request(self, method, endpoint, params=None, data=None):
        """Generic request sender (GET, POST, PUT, DELETE)."""
        url = f"{self.base_url}/{endpoint}"

        try:
            response = requests.request(
                method,
                url,
                headers=self._get_headers(),
                params=params,
                json=data
            )

            # If the token has expired, refresh it and retry the request
            if response.status_code == 401:  # Unauthorized
                print("Token expired, refreshing...")
                self._refresh_token()
                response = requests.request(
                    method,
                    url,
                    headers=self._get_headers(),
                    params=params,
                    json=data
                )

            response.raise_for_status()  # Will raise an error for 4xx and 5xx status codes
            return response.json()

        except requests.exceptions.RequestException as e:
            print(f"Request failed: {e}")
            return None

    def get(self, endpoint, params=None):
        """Send a GET request."""
        return self._send_request('GET', endpoint, params=params)

    def post(self, endpoint, data=None):
        """Send a POST request."""
        return self._send_request('POST', endpoint, data=data)

    def put(self, endpoint, data=None):
        """Send a PUT request."""
        return self._send_request('PUT', endpoint, data=data)

    def delete(self, endpoint):
        """Send a DELETE request."""
        return self._send_request('DELETE', endpoint)


# Example Usage

if __name__ == "__main__":
    base_url = 'https://api.example.com/v1'  # Replace with your API's base URL
    auth_url = 'https://api.example.com/oauth/token'  # The URL to obtain the token
    client_id = 'your_client_id'
    client_secret = 'your_client_secret'

    client = RestAPIClient(base_url, auth_url, client_id, client_secret)

    # Example of GET request
    response = client.get("data/endpoint")
    if response:
        print("GET Response:", response)

    # Example of POST request
    new_data = {"key": "value"}
    response = client.post("data/endpoint", data=new_data)
    if response:
        print("POST Response:", response)
