import argparse
import yaml
parser = argparse.ArgumentParser()
parser.add_argument('files', metavar='YAMLFILES', type=argparse.FileType('r'), nargs='*')
args = parser.parse_args()

y = {'apiVersion': 'v1', 'kind': 'Config', 'clusters': [],'contexts': [],
    'current-context': None, 'preferences': {}, 'users': []}
for a in args.files:
    f = yaml.load(a, Loader=yaml.Loader)
    y['clusters'].append(f['clusters'][0])
    y['contexts'].append(f['contexts'][0])
    y['users'].append(f['users'][0])
    y['current-context'] = f['contexts'][0]['name']

print(yaml.dump(y, Dumper=yaml.Dumper))