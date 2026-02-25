#! /usr/bin/env python3
# -*- coding: utf-8 -*-
"""PX-Backup version checker.

This module provides functionality to authenticate with PX-Backup instances
and retrieve version information from the API. It supports both username/password
authentication and OAuth2 client credentials flow.
"""

import argparse
import getpass
import json
import logging
from typing import Any, Dict, Optional

import requests  # type: ignore


def _prompt_for_password(args: argparse.Namespace) -> argparse.Namespace:
    """Prompt for password if not specified on the command line.

    Args:
        args: Parsed command-line arguments namespace.

    Returns:
        argparse.Namespace: Updated arguments namespace with password set.
    """
    if not args.password:
        args.password = getpass.getpass(prompt='"Please enter password for host %s and user %s: ' % (args.host, args.user))
    return args


def grab_token(user: str, passwd: str, url: str) -> str:
    """Grab an authentication token for PX-backup.

    Authenticates with PX-backup using username/password and retrieves
    an access token from the Keycloak authentication endpoint.

    Args:
        user: Username for PX-backup authentication.
        passwd: Password for PX-backup authentication.
        url: Base URL of the PX-backup instance.

    Returns:
        str: Access token string for authenticated requests.

    Raises:
        KeyError: If the response does not contain an access_token.
        requests.exceptions.RequestException: If the authentication request fails.
    """
    pxbk_authep = "/auth/realms/master/protocol/openid-connect/token"
    pxbk_authrequest = f"grant_type=password&client_id=pxcentral&username={user}&password={passwd}&token-duration=365d"
    pxbk_url = url + pxbk_authep
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    response = requests.post(pxbk_url, verify=False, data=pxbk_authrequest, headers=headers)
    resp = response.json()
    return resp["access_token"]  # type: ignore[no-any-return]


def get_jwt_token(consumer_key: str, consumer_secret: str, url: str) -> str:
    """Get a JWT token for PX-backup using client credentials.

    Authenticates with PX-backup using OAuth2 client credentials flow
    and retrieves a JWT access token.

    Args:
        consumer_key: OAuth2 client ID.
        consumer_secret: OAuth2 client secret.
        url: Token endpoint URL.

    Returns:
        str: Access token string, or "error" if authentication fails.

    Raises:
        requests.exceptions.RequestException: If the token request fails.
        json.JSONDecodeError: If the response is not valid JSON.
        KeyError: If the response does not contain an access_token.
    """
    data = "grant_type=client_credentials&client_id=" + consumer_key + "&client_secret=" + consumer_secret
    header = {"Content-type": "application/x-www-form-urlencoded"}
    try:
        response = requests.post(url, data=data, headers=header)
        access_token = json.loads(response.text)
        final_response = access_token["access_token"]
    except (requests.exceptions.RequestException, json.JSONDecodeError, KeyError) as err:
        print(err)
        final_response = "error"
    return final_response  # type: ignore[no-any-return]


def checkpxbkstatus(token: str, url: str) -> Optional[Dict[str, Any]]:
    """Check the status and version of PX-backup.

    Retrieves version information from the PX-backup API using
    an authenticated bearer token.

    Args:
        token: Bearer token for authentication.
        url: Base URL of the PX-backup instance.

    Returns:
        Optional[Dict[str, Any]]: Version information as a dictionary if successful,
            None if the request fails or returns a non-200 status code.

    Raises:
        requests.exceptions.RequestException: If the HTTP request fails.
    """
    pxbk_version = "/v1/version"
    ckurl = url + pxbk_version
    pxbkheaders = {"accept": "application/json", "Authorization": f"bearer {token}"}
    try:
        response = requests.get(ckurl, headers=pxbkheaders, verify=False)
        response.raise_for_status()
        if response.status_code == 200:
            print("200 returned")
            print(response.text)
            return response.json()  # type: ignore[no-any-return]
        else:
            return None
    except Exception as e:
        print(f"Request Error: {e}")
        return None


if __name__ == "__main__":
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(description="Check PX - Backup status")
    parser.add_argument(
        "-u",
        "--user",
        required=True,
        action="store",
        help="User name to use when connecting to host",
    )
    parser.add_argument(
        "-p",
        "--password",
        required=False,
        action="store",
        help="Password to use when connecting to host",
    )
    parser.add_argument(
        "-s",
        "--host",
        required=True,
        action="store",
        help="px-backup host FQDN address to connect to",
    )
    parser.add_argument("--debug-cm", action="store_true", help="Enable debug")

    args = _prompt_for_password(parser.parse_args())
    debug_cm = args.debug_cm
    pxbk_url = "https://px-backup-ui-px-backup.apps." + args.host

    if debug_cm:
        print("Debug true")
        # These two lines enable debugging at httplib level (requests->urllib3->http.client)
        # You will see the REQUEST, including HEADERS and DATA, and RESPONSE with HEADERS but without DATA.
        # The only thing missing will be the response.body which is not logged.
        import http.client as http_client

        http_client.HTTPConnection.debuglevel = 1
        # You must initialize logging, otherwise you'll not see debug output.
        logging.basicConfig()
        logging.getLogger().setLevel(logging.DEBUG)
        requests_log = logging.getLogger("requests.packages.urllib3")
        requests_log.setLevel(logging.DEBUG)
        requests_log.propagate = True

    pxbk_accesstoken = grab_token(args.user, args.password, pxbk_url)
    status = checkpxbkstatus(pxbk_accesstoken, pxbk_url)
    print(status)
