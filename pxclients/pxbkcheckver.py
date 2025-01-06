import argparse
import getpass
import json
import logging

import requests


def _prompt_for_password(args):
    """
    if no password is specified on the command line, prompt for it
    """
    if not args.password:
        args.password = getpass.getpass(prompt='"Please enter password for host %s and user %s: '% (args.host, args.user))
    return args

def grab_token(user,passwd,url):          
        pxbk_authep = "/auth/realms/master/protocol/openid-connect/token"
        pxbk_authrequest =  f"grant_type=password&client_id=pxcentral&username={user}&password={passwd}&token-duration=365d"
        pxbk_url= url+pxbk_authep
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        response = requests.post(pxbk_url,verify=False,data=pxbk_authrequest,headers=headers)
        resp = response.json()
        return resp["access_token"]
    
def get_jwt_token(consumer_key, consumer_secret, url):
        data = 'grant_type=client_credentials&client_id=' + consumer_key + '&client_secret=' + consumer_secret
        header = {"Content-type": "application/x-www-form-urlencoded"}
        try:
            response = requests.post(url, data=data, headers=header)
            access_token = json.loads(response.text)
            final_response=access_token['access_token']
        except requests.exceptions as err:
            print(err)
            final_response = 'error'
        return final_response

def checkpxbkstatus(token,url):
        pxbk_version = "/v1/version"
        ckurl=url+pxbk_version
        pxbkheaders = {"accept": "application/json" , "Authorization": f"bearer {token}" }
        try:
            response = requests.get(ckurl, headers=pxbkheaders, verify=False)
            response.raise_for_status()
            if response.status_code == 200:
                print("200 returned")
                print(response.text)
                return response.json()
            else:
                return None
        except Exception as e:
            print(f"Request Error: {e}")
            return None
   
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Check PX - Backup status")
    parser.add_argument('-u', '--user',required=True,action='store',help='User name to use when connecting to host')
    parser.add_argument('-p', '--password',required=False, action='store',help='Password to use when connecting to host')
    parser.add_argument('-s', '--host',required=True,action='store',help='px-backup host FQDN address to connect to')
    parser.add_argument("--debug-cm", action="store_true", help="Enable debug")

    args = _prompt_for_password(parser.parse_args())
    debug_cm = args.debug_cm
    pxbk_url="https://px-backup-ui-px-backup.apps."+args.host
    
    if debug_cm == True:
        print("Debug true")
        # These two lines enable debugging at httplib level (requests->urllib3->http.client)
        # You will see the REQUEST, including HEADERS and DATA, and RESPONSE with HEADERS but without DATA.
        # The only thing missing will be the response.body which is not logged.
        try:
            import http.client as http_client
        except ImportError:
            # Python 2
            import httplib as http_client
        http_client.HTTPConnection.debuglevel = 1
        # You must initialize logging, otherwise you'll not see debug output.
        logging.basicConfig()
        logging.getLogger().setLevel(logging.DEBUG)
        requests_log = logging.getLogger("requests.packages.urllib3")
        requests_log.setLevel(logging.DEBUG)
        requests_log.propagate = True

    pxbk_accesstoken = grab_token(args.user,args.password,pxbk_url)
    status = checkpxbkstatus(pxbk_accesstoken,pxbk_url)
    print (status)