#!/usr/bin/python
import argparse
import re
import time
import urllib2
import json
import yaml
from base64 import b64encode


class NagiosBoundaryCheck:
    def __init__(self, configDict):
        ###
        # I expect warning or critical configuration to look like:
        # warning:
        #       expression: regex
        # <or>  lessthan: number
        # <or>  greaterthan: number
        ###
        if configDict == False:
            self.type = "fake"
        elif("expression" in configDict):
            self.type = "exp"
            self.boundary = configDict["expression"]
        elif("lessthan" in configDict):
            self.type = "lt"
            self.boundaryfloat = float(configDict["lessthan"])
        elif("greaterthan" in configDict):
            self.type = "gt"
            self.boundaryfloat = float(configDict["greaterthan"])
        else:
            raise ValueError("A warning or critical boundary should have an 'expression', 'lessthan' or 'greaterthan' value")

        self.message = "" if not "message" in configDict else configDict["message"]

    def inBadState(self, value):
        if(self.type == "fake"):
            return False
        elif(self.type == "exp"):
            return re.match(self.boundary, value)
        elif (self.type == "lt"):
            return float(value) < self.boundaryfloat
        elif (self.type == "gt"):
            return float(value) > self.boundaryfloat

    def getMessage(self):
        return self.message

## Configureable values, to be moved to the config file
TIMEOUT=10
RETRIES=3


## Const values
NAGIOS_OK = 0
NAGIOS_WARNING = 1
NAGIOS_CRITICAL = 2
NAGIOS_UNKNOWN = 3
NAGIOS_DICT = {NAGIOS_OK: "OK", NAGIOS_WARNING: "WARNING", NAGIOS_CRITICAL: "CRITICAL", NAGIOS_UNKNOWN: "UNKNOWN"}
RESULTBLOCK="[RESULT]"
SERVERBLOCK="[SERVER]"


lazyMap = {}
def getValueOverJSON(url, key, auth):
    global lazyMap
    data = False
    error = False
    result = False
    attempts = 0
    while attempts < RETRIES:
        try:
            request = urllib2.Request(url)
            request.add_header("Authorization", "Basic " + auth)
            response = urllib2.urlopen(request, timeout=TIMEOUT)
            data = json.loads(response.read())
            attempts = RETRIES
        except urllib2.URLError as e:
            print(str(e))
            if "Connection refused" in str(e):
                error = "Connection refused, giving up connecting to " + url + " attempt " + str(attempts)
                attempts = RETRIES
            elif "timed out" in str(e):
                error = "URL error, probably a timeout when connecting to " + url + " attempt " + str(attempts)
                attempts += 1
                time.sleep(10)
            else:
                error = "Unknown URL error for: " + url + " : " + str(e)
                attempts = RETRIES
        except Exception as e:
            attempts += 1
            error = "Could not correct to " + url + " attempt " + str(attempts) + " with error: " + str(e)
    if key in data:
        result = data[key]
    else:
        if "status" in data and data["status"] == 404:
            error = "WLS management page for url " + url + " did not exist"
        else:
            error = "Could not find the attribute '"+key+"' on the WLS management response page for " + url

    return (str(result), error)

if __name__ == "__main__":
    configfile = open("restwlsconfig.yaml","r")
    configurations = yaml.load(configfile)

    description = '''
    This is a support script for the "zzwlshealth" health check, used by the F5 load balancer and WebLogic to
    see which WebLogic instance can receive requests. Use this script to disable a server and tell the load
    balancer to stop sending requests to this specific instance.
    
    Known checks:
    '''
    for name in configurations["configurations"]:
        description += name

    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("-c", "--check", help="Check name to run. If none, all are run (useless in a Nagios context)")
    parser.add_argument("-v", "--verbose", action='store_true', help="Enable verbose logging, not useable in Nagios contexts")
    parser.add_argument("-b", "--basicauth", action="store_true", help="Ask for credentials to generate a base auth header value, useable in the config")
    args = parser.parse_args()

    if args.basicauth:
        user = raw_input("Please enter the user you wish to use for monitoring [weblogic]: ")
        if not user:
            user = "weblogic"
        password = raw_input("Please enter the password for this user: ")
        userAndPass = b64encode(user + ":" + password)
        print("Your authstring is " + userAndPass)
        exit(0)

    nagiosResult = NAGIOS_OK
    nagiosMessage = ""

    for name in configurations["configurations"]:
        config = configurations["configurations"][name]
        ## Skip unnamed configurations as they are probably used as templates
        if "name" in config.keys():
            ## Some setup
            warningCheck = NagiosBoundaryCheck(False if "warning" not in config else config["warning"])
            criticalCheck = NagiosBoundaryCheck(False if "critical" not in config else config["critical"])

            ## Set up the basic auth header
            if "username" in config:
                auth = b64encode(config["username"] + ":" + config["password"])
            else:
                auth = config["authstring"]

            for server in config["servers"]:
                if nagiosMessage != "":
                    nagiosMessage += ", "

                url = config["baseurl"] + config["url"]
                url = url.replace("[SERVER]", server)
                result = getValueOverJSON(url, config["resultattribute"],auth)

                ## If the error message is not empty
                if result[1]:
                    nagiosResult = NAGIOS_UNKNOWN
                    nagiosMessage += server + " reports " + result[1]
                else:
                    nagiosMessage += config["message"]
                    if criticalCheck.inBadState(result[0]):
                        nagiosResult = NAGIOS_CRITICAL if nagiosResult < NAGIOS_CRITICAL else nagiosResult
                        nagiosMessage += criticalCheck.getMessage()
                    elif warningCheck.inBadState(result[0]):
                        nagiosResult = NAGIOS_WARNING if nagiosResult < NAGIOS_WARNING else nagiosResult
                        nagiosMessage += warningCheck.getMessage()

                ## After handling the result, transform macros in the message
                if nagiosMessage.find(RESULTBLOCK) > -1:
                    nagiosMessage = nagiosMessage.replace(RESULTBLOCK, result[0])
                if nagiosMessage.find(SERVERBLOCK) > -1:
                    nagiosMessage = nagiosMessage.replace(SERVERBLOCK, server)

            print(NAGIOS_DICT[nagiosResult] + ": " + nagiosMessage)
            print(nagiosResult)
            exit(nagiosResult)

