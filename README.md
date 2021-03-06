# WebLogic Nagios monitoring over REST

So, when trying to monitor Oracle Fusion Middleware installations using your in place on-site monitoring such as Nagios, you have a number of options. The obvious ones are to use WLST or any other java JMX based tooling. 
But the java process is expensive resource-wise. And you wouldn't be the first to create a situation where WLST scripts take such a long time to start and finish that they are piling on top of each other, draining your production machine of it's precious resources. 

An alternative would be to use SNMP. But in the WebLogic implementation it is hard to find your own configured components such as specific datasources. 

With WebLogic 12c (12.2.1.2 and up) we have a new option in the form of a REST interface. Easy, lightweight and somewhat complete. Check_wls_rest is a script that can be configured to grab specific variables from there with a Nagios valid return code and performance data.  

## Installation
The configuration file requires the Python YAML library. Pick one: 
``` 
pip install -r requirements.txt
yum install python-yaml
apt install python-yaml
```

## How to configure with Nagios
Let's assume you want to monitor the number of stuck threads on the AdminServer of your current domain. 
##### REST URL
First you'll need to figure out the right WLS REST management URL. You could start from http://myserver:7001/management/weblogic/latest/domainRuntime in a browser, but lets open http://myserver:7001/management/weblogic/latest/domainRuntime/serverRuntimes/AdminServer directly. Find the "threadpoolRuntime" URL and open that, which should be http://myserver:7001/management/weblogic/latest/domainRuntime/serverRuntimes/AdminServer/threadPoolRuntime. The number of stuck threads are found in the stuckThreadCount attribute. We'll need that and the URL.

##### Configure restwlsconfig.yaml
Let's skip YAML templating for now. Create a new check like following:
```
configurations:
    stuck_thread_counter:
      baseurl: http://myserver:7001/management/weblogic/latest
      username: weblogicmonitor
      password: welcome01
      servers: AdminServer
      resultattribute: stuckThreadCount
      message: [SERVER] has [RESULT] stuck threads
      url: /management/weblogic/latest/domainRuntime/serverRuntimes/[SERVER]/threadPoolRuntime
      critical:
        greaterthan: 10
        message: [SERVER] currently has [RESULT] stuck threads and should reboot!
```
This should give an OK if the number of stuck threads is less than 10. Otherwise, it will return a Nagios critical message.

##### Testing
When you run the restwls script with the -h parameter, it will display a help message and the names of all known tests. If you run the restwls script without any parameters it will then run all tests.

To run just your own script run with the -c parameter. If results are as expected (a nice "OK: AdminServer has 0 stuck threads") you can add your check to Nagios, if it has local access. 

##### NRPE  
To run over NRPE, just add the following to your NRPE configuration. 
```
command[chk_stucks]=/usr/bin/python /usr/local/check_wls_rest.py -c stuck_thread_counter
```
The chk_stucks label is the command given to the NRPE configuration in Nagios. The stuck_thread_counter label refers to the stuck_thread_counter entry in the script YAML file. The script will then grab the correct configuration from the YAML config, check the given URL and parse the results to return a succesful Nagios result.

If you run the script with the -g parameter it will generate an NRPE configuration for all known checks.    
  
##### JMX beans not found when browsing REST pages
There is a bug in the 12.2.1.3 WebLogic (Metalink bug id 29712200) where the convenience URLs generated in the REST pages are incorrect. If you click through the pages in a browser and get "not found" errors, take a good look at the URL. It could be that part is missing. 

This happens for example with JMS server URLs: the link generated in the browser is /management/weblogic/latest/domainRuntime/serverRuntimes/AdminServer/JMSServers/JMSServer1 instead of the required /management/weblogic/latest/domainRuntime/serverRuntimes/AdminServer/JMSRuntime/JMSServers/JMSServer1 (as in, the JMSRuntime bit is missing)

## Security considerations
### Firewalling
As this script is suggested to be run on the monitored system itself the 7001 port should be closed for any system (including your monitoring) except for bastion machines.

### On the password 
Somewhere, somehow, this script will need a username and password combination. And that can be intercepted. In the config file, you can either give a base64 header string (generated by running the script with the -b option) or give a cleartext username and password. 

Note that the base64 header is still trivial to decipher for any intruder. Please monitor your file permissions and create a special user for monitoring with only readonly permissions (the monitor role) to limit access.   

## On Jolokia
This check script also works with Jolokia (https://jolokia.org/). Jolokia can be used as an alternative REST JMX client and can be used in a way very similar to the /management URL. It gives me less timeouts and a more complete overview while missing some familiar structure (it just displays everything). Frank Munz wrote a still relevant overview of Jolokia on WebLogic at http://www.munzandmore.com/2012/ora/weblogic-rest-management-jolokia.

To get a good, authenticated WAR you need to add a role mapping to inform WebLogic on how to authenticate users. Installing Jolokia as follows: 

* Download the Jolokia WAR agent
* We should map the Jolokia role to a WebLogic user group, for example, to "Monitors". Add a weblogic.xml file with the following content to the jolokia war in /WEB-INF:
```
<?xml version = '1.0' encoding = 'windows-1252'?>
<weblogic-web-app xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                  xsi:schemaLocation="http://www.bea.com/ns/weblogic/weblogic-web-app.xsd"
                  xmlns="http://www.bea.com/ns/weblogic/weblogic-web-app">
  <security-role-assignment>
    <role-name>jolokia</role-name>
    <principal-name>Monitors</principal-name>
  </security-role-assignment>
</weblogic-web-app>
```
* Deploy this war in WebLogic on the server you wish to monitor (probably NOT the AdminServer). Use the "DD only" security role option. Note that you can monitor the full WebLogic domain configuration from anywhere, but the runtime information only on the server you deployed on.     
* Find the base URL in the "testing" tab of the Jolokia deployment in the WebLogic admin console
* Feed this a mBean name in the URL, like "com.bea:Name=AdminServer": 
```
http://myServer:7001/jolokia-war-1.6.0/read/com.bea:Name=AdminServer,Type=Server?ignoreErrors=true&mimeType=application/json
```
* You can log in with any user that is a member of the "Monitors" group

In the script, use the "parameters" attribute of your check to add the mimetype and ignoreErrors parameters. See the restwlsconfig.yaml.jolokiaexample for a good example to jump off on.  