So, when trying to monitor Oracle Fusion Middleware installations using your in place on-site monitoring such as Nagios, you have a number of options. The obvious ones are to use WLST or any other java JMX based tooling. 

But the java process is expensive. And you wouldn't be the first to create a situation where WLST scripts take such a long time to start and finish that they are piling on top of each other, draining your production machine of it's precious resources. 

A better option would be to use SNMP. But SNMP is hard and in the WebLogic implementation it is hard to find your own configured components such as datasources. 

With WebLogic 12c (12.2.1.2 and up) we have a new option in the form of a REST interface. Easy, lightweight and somewhat complete. 

## NRPE
This script should be used over the NRPE agent. For example, you could have a custom NRPE file with the following command:

```
command[chk_datasources]=/usr/local/restwls.py datasources_health
```
The chk_datasources label is the command given to the NRPE configuration in Nagios. The datasources_health label refers to the datasources_health entry in the OFMWRestMonitor YAML file.

The script will then grab the correct configuration from the YAML config, check the given URL and parse the results to return a succesful Nagios result. 
  

## Security considerations
### Firewalling
As this script is suggested to be run on the monitored system itself the 7001 port should be closed for any system (including your monitoring) except for bastion machines.

### On the password 
The base64 header is included in the configuration file which is trivial to decipher for any intruder. However, considering you have decent controls on your filesystem and permissions there are a lot of easier ways to retrieve passwords from your WebLogic system:
- Anyone with access to the WebLogic configuration files can extract and cleartext any password used. 
- There is a range of deserialization vulnerabilities known on port 7001. Anyone with access to that port does not even need a password.  

I suggest you create a WebLogic user with only readonly permissions (the monitor role) to limit access.   

