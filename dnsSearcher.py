#!/usr/bin/python       
from dns import resolver,reversename

sNetworkAddress = '10.34.114'
aiHostAddresses = range(1,255)
dns1=resolver.Resolver()
dns1.nameservers=['10.34.115.200']
dns2=resolver.Resolver()
dns2.nameservers=['10.34.113.61']
dns3=resolver.Resolver()
dns3.nameservers=['10.39.108.23']

print( "Starting Scan...")
f=open('f:/ted/hosts.csv','w')
with open('f:/ted/bobbyIPS.txt') as input_file:
    print (input_file)
    for i, address in enumerate(input_file):
        addr=reversename.from_address(address.encode('ascii', 'ignore').strip())
        try:
            name1= str(dns1.query(addr,"PTR")[0])
        except Exception as inst:
            name1="unknown"        
        try:
            name2= str(dns2.query(addr,"PTR")[0])
        except Exception as inst:
            name2="unknown"        
        try:
            name3= str(dns3.query(addr,"PTR")[0])
        except Exception as inst:
            name3="unknown"        
        outLine= "%s,%s,%s,%s\n"% (name1,name2,name3,address.strip())
        f.write(outLine)
        f.flush()
f.close()
print ("{0} line(s) printed".format(i+1))