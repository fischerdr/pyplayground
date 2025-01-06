import argparse
import csv
import getpass
import json
import logging
import sys

import requests


def _prompt_for_password(args):
    """
    if no password is specified on the command line, prompt for it
    """
    if not args.password:
        args.password = getpass.getpass(prompt='"Please enter password for host %s and user %s: '% (args.host, args.user))
    return args

def grab_token(url,user,passwd):          
    pxbk_authep = "/auth/realms/master/protocol/openid-connect/token"
    pxbk_authrequest =  f"grant_type=password&client_id=pxcentral&username={user}&password={passwd}&token-duration=365d"
    pxbk_url= url+pxbk_authep
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    print (pxbkui_url)
    try:
        response = requests.post(pxbk_url,verify=False,data=pxbk_authrequest,headers=headers)
        access_token = json.loads(response.text)
        final_response=access_token['access_token']
    except requests.exceptions as err:
        print(err)
        final_response = 'error'
    return final_response        

def findownerID(url,token,name):
    usr_search = f"{url}/auth/admin/realms/master/users?search={name}"
    payload={}
    pxbkheaders = {"accept": "application/json" , "Authorization": f"bearer {token}" }
    response = requests.request("GET", usr_search, headers=pxbkheaders, data=payload,verify=False)
    usr_rec= search(name,response.json())
    print (usr_rec)
    return (usr_rec)

def createAWSCldCred(url,token,name,orgID,ownerid,accessID,secretKey):
    s3addurl = url+"/v1/cloudcredential"
    payload = json.dumps({
    "metadata": {
        "name": name,
        "org_id": orgID,
        "owner": ownerid,
        "ownership": {
        "owner": ownerid,
        "groups": [
            {
            "id": "px-admin-group",
            "access": "Admin"
            }
        ],
        "public": {}
        }
    },
    "cloud_credential": {
        "type": "AWS",
        "aws_config": {
        "access_key": accessID,
        "secret_key": secretKey
        }
    }
    })
    pxbkheaders = {"Content-Type": "application/json","Accept": "application/json" , "Authorization": f"bearer {token}" }
    response = requests.request("POST", s3addurl, headers=pxbkheaders, data=payload,verify=False)
    print (response.text)
    return response


def search(name, users):
    #return [element for element in users if element['username'] == name]
    return next(filter(lambda obj: obj.get('username') == name, users), None)

def load_s3creds_from_file(file_path):
    try:

        with open(file_path, mode='r') as f:
            csvFile = csv.reader(f)
            for lines in csvFile:
                print(lines)
        print(f"Loaded {len(csvFile)} nodes from file {file_path}")
        return csvFile
    except FileNotFoundError:
        print(f"Error: The file {file_path} was not found.")
        return []
    
    
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Add S3 AWS type cred")
    parser.add_argument('-u', '--user',required=True,action='store',help='User name to use when connecting to host')
    parser.add_argument('-p', '--password',required=False, action='store',help='Password to use when connecting to host')
    parser.add_argument('-s', '--host',required=True,action='store',help='px-backup host FQDN address to connect to')
    parser.add_argument("--debug-cm", action="store_true", help="Enable debug")
    cmdlinegroup = parser.add_argument_group('cmdline group')
    cmdlinegroup.add_argument("--credname",help="Name for resource in PX-backup ")
    cmdlinegroup.add_argument("--secretKey" ,help="S3 secret key")
    cmdlinegroup.add_argument("--owner-name" ,help="User name to own the resource")
    cmdlinegroup.add_argument("--accessID" ,help="S3 access key")
    cmdlinegroup.add_argument("--orgID",default='default',action='store',help="Portworx org - should be -> default")
    exclusive_group = parser.add_mutually_exclusive_group(required=True)
    exclusive_group.add_argument("--s3cred-file", help="Path to a file containing AWS cred list format: name:owner_username:accessid:secretID")
    exclusive_group.add_argument("-add",default=False,action="store_true",help="Add single entry with credname,accessID,secretkey,owner-name as REQUIRED parms")
    
    args = _prompt_for_password(parser.parse_args())
    
    if args.add:
        req_args= bool(args.credname) + bool(args.secretKey) + bool(args.owner_name) + bool(args.accessID)
        if req_args != 4:
            parser.print_help()
            sys.exit(1)
            
    if args.password == "":
        parser.print_help()
        sys.exit(1)

    debug_cm = args.debug_cm
    pxbkui_url="https://px-backup-ui-px-backup.apps."+args.host
    pxbkapi_url="https://px-backup-api-px-backup.apps."+args.host
    
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

    pxbk_accesstoken = grab_token(pxbkui_url,args.user,args.password)
    if args.s3cred_file:
        try:

            with open(args.s3cred_file, mode='r') as f:
                csvFile = csv.reader(f,delimiter=":")
                for rec in csvFile:
                    print(rec)
                    owner_id=findownerID(pxbkui_url,pxbk_accesstoken,rec[1])
                    createAWSCldCred(pxbkapi_url,pxbk_accesstoken,rec[0],args.orgID,rec[1],rec[2],rec[3])
                    
                
        except FileNotFoundError:
            print(f"Error: The file {args.s3cred_file} was not found.")
        
        
        #owner_id=findownerID(pxbkui_url,pxbk_accesstoken,args.owner_name)
        #createAWSCldCred(pxbk_accesstoken,pxbkapi_url,name,orgID,owner_name,accessID,secretKey)
        pass
    else:
        ownerrec=findownerID(pxbkui_url,pxbk_accesstoken,args.owner_name)
        createAWSCldCred(pxbkapi_url,pxbk_accesstoken,args.credname,args.orgID,ownerrec['id'],args.accessID,args.secretKey)
        
    
