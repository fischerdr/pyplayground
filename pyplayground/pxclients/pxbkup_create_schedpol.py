#! /usr/bin/env python3
# -*- coding: utf-8 -*-
"""Creates a schedule policy for PX-backup."""
import csv
import getpass
import json
import logging
import os
import sys
from argparse import ArgumentParser

import requests
from jinja2 import Environment, FileSystemLoader

from pyplayground.utils.logging_utils import get_logger, setup_logging

# Setup logging
setup_logging(script_name=os.path.basename(__file__).replace(".py", ""))
logger = get_logger(__name__)

logger.warning("Stay calm!")


class REST_API:
    """REST API class."""

    def __init__(self, host, user, password, duration=None, verify=None):
        """Initialize the REST API class."""
        self.host = host
        self.user = user
        self.password = password
        self.duration = duration or "365d"
        self.authep = "/auth/realms/master/protocol/openid-connect/token"
        self.payload = f"grant_type=password&client_id=pxcentral&username={self.user}&password={self.password}&token-duration={self.duration}"
        self.pxbk_url = self.host + self.authep
        self.headers = {"Content-Type": "application/x-www-form-urlencoded"}
        self.ssl_verify = verify or False
        self.token = self.get_token()

    def get_token(self):
        """Get a token for the REST API."""
        logger.info(self.pxbk_url)
        try:
            response = requests.post(
                self.pxbk_url, verify=self.ssl_verify, data=self.payload, headers=self.headers
            )
            if response.ok:
                access_token = json.loads(response.text)
                token = access_token["access_token"]
            else:
                response.raise_for_status()
        except requests.exceptions.HTTPError as err:
            logger.error(f"Error - {err} - response: {response.content}")
            # logger.error(err)
            sys, exit(response.status_code)
        return token

    def refresh_token(self):
        """Refresh the token for the REST API."""
        return self.get_token()


class dotdict(dict):
    """dot.notation to dictionary attributes."""

    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__


def _prompt_for_password(args):
    """If no password is specified on the command line, prompt for it."""
    if not args.password:
        args.password = getpass.getpass(
            prompt="Enter password for host %s and user %s: " % (args.host, args.user)
        )
    return args


def searchUUID(url, token, name):
    """Search for a user by name."""
    usr_search = f"{url}/auth/admin/realms/master/users?search={name}"
    payload = {}
    pxbkheaders = {"accept": "application/json", "Authorization": f"bearer {token}"}
    response = requests.request("GET", usr_search, headers=pxbkheaders, data=payload, verify=False)
    usr_rec = search(name, response.json())
    logger.info(usr_rec)
    return usr_rec


def createSchedPol(url, token, name, orgID, ownerID, schedType, schedOptions):
    """Create a schedule policy."""
    pass


def search(name, users):
    """Search for a user by name."""
    # return [element for element in users if element['username'] == name]
    return next(filter(lambda obj: obj.get("username") == name, users), None)


def load_schedpolicy(file_path):
    """Load a schedule policy from a file."""
    try:
        with open(file_path, mode="r") as f:
            csvFile = csv.reader(f)
            for lines in csvFile:
                logger.info(lines)
        logger.info(f"Loaded {len(csvFile)} nodes from file {file_path}")
        return csvFile
    except FileNotFoundError:
        logger.info(f"Error: The file {file_path} was not found.")
        return []


if __name__ == "__main__":
    environment = Environment(loader=FileSystemLoader("templates/"))
    template = environment.get_template("createschedulepolicy.json.j2")

    parser = ArgumentParser(description="Create PX-Backup schedule policy")
    parser.add_argument(
        "-u", "--user", required=True, action="store", help="User to connecting to PX-Backup"
    )
    parser.add_argument(
        "-p", "--password", required=False, action="store", help="User's Password to connect with"
    )
    parser.add_argument(
        "-s", "--host", required=True, action="store", help="PX-Backup FQDN address to connect"
    )
    parser.add_argument("--debug", action="store_true", default=None, help="Enable debug")
    parser.add_argument(
        "--ownername", default=None, dest="ownerName", help="User name to own the resource"
    )
    parser.add_argument("--schedName", default=None, help="Name of resource in PX-backup ")
    parser.add_argument(
        "--retain",
        default=None,
        help="select the number of backups to retain concurrently. This option determines how long backups and snapshots should be kept before they are deleted.",
    )
    parser.add_argument(
        "--betweenFull",
        default=None,
        help="specify the number of incremental backups between two full backups. This applies only to Portworx volumes",
    )
    parser.add_argument("--minutes", default=None, help="fixed intervals defined in minutes")
    parser.add_argument(
        "--timeampm",
        default=None,
        help="runs every day at a specified time. Provide the hours and minutes from midnight to define the time",
    )
    parser.add_argument(
        "--day",
        default=None,
        help="specified day # of the month. If the day given is longer than the current month, it will roll over to the next month.",
    )
    parser.add_argument("--weekday", default=None, help="specified day")
    reqGroup = parser.add_mutually_exclusive_group(required=True)
    reqGroup.add_argument(
        "--file",
        help="Path to a file containing schedule policy list *NOTE* format(first line must be): schedName,ownername,type,minutes,timeampm,weekday,day",
    )
    reqGroup.add_argument(
        "--type",
        choices=["interval", "daliy", "weekly", "monthly"],
        dest="schedType",
        default=None,
        help="Type of schedule policy to create",
    )
    parser.add_argument(
        "-l",
        "--log",
        help="Set logging level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        nargs="?",
        dest="loggingLevel",
        const="INFO",
        default="INFO",
        type=str.upper,
    )

    args = _prompt_for_password(parser.parse_args())

    if args.schedType:
        req_args = bool(args.schedName) + bool(args.ownerName)
        if req_args != 2:
            parser.print_help()
            sys.exit(1)

    if args.password == "":
        parser.print_help()
        sys.exit(1)

    pxbkui_url = "https://pxbk-ui.apps." + args.host
    pxbkapi_url = "https://pxbk-api.apps." + args.host

    if args.debug:
        print("Debug true")
        # These two lines enable debugging at httplib level (requests->urllib3->http.client)
        # You will see the REQUEST, including HEADERS and DATA, and RESPONSE with HEADERS but without DATA.
        # The only thing missing will be the response.body which is not logged.
        import http.client as http_client
        http_client.HTTPConnection.debuglevel = 1
        # You must initialize logging, otherwise you'll not see debug output.
        logger.setLevel(logging.DEBUG)
        requests_log = logging.getLogger("requests.packages.urllib3")
        requests_log.setLevel(logging.DEBUG)
        requests_log.propagate = True

    pxbktkn = REST_API(pxbkui_url, args.user, args.password)
    if args.file:
        logger.info(f"Reading file {args.file}")
        try:
            with open(args.file, mode="r") as f:
                csvFile = csv.DictReader(f, delimiter=",")
                data = [row for row in csvFile]
                logger.info(data)
                for row in csvFile:
                    logger.info(row)
                    owner_id = searchUUID(pxbkui_url, pxbktkn, row["ownername"])
                    # createSchedPol(pxbkapi_url, pxbktkn, rec[0], args.orgID, rec[1], rec[2], rec[3])

        except FileNotFoundError:
            logger.info(f"Error: The file {args.s3cred_file} was not found.")
        # owner_id=searchUUID(pxbkui_url,pxbktkn,args.owner_name)
        # createAWSCldCred(pxbktkn,pxbkapi_url,name,orgID,owner_name,accessID,secretKey)
        pass
    else:
        logger.info(f"Creating schedule policy {args.schedType} - {args.schedName}")
        ownerrec = searchUUID(pxbkui_url, pxbktkn.token, args.owner_name)
        createSchedPol(
            pxbkapi_url,
            pxbktkn.token,
            args.credname,
            args.orgID,
            ownerrec["id"],
            args.accessID,
            args.secretKey,
        )
