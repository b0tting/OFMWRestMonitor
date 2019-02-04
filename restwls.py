#!/usr/bin/python
import argparse
import re
import time
import urllib
import urllib2
import json
import yaml
from base64 import b64encode
import sys, os

class NagiosBoundaryCheck:
    def __init__(self, configDict, defaultMessage):
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
        self.message = defaultMessage if not "message" in configDict else configDict["message"]

    def inBadState(self, value):
        if(self.type == "fake"):
            return False
        elif(self.type == "exp"):
            return re.match(self.boundary, value)
        else:
            try:
                if (self.type == "lt"):
                    return float(value) < self.boundaryfloat
                elif (self.type == "gt"):
                    return float(value) > self.boundaryfloat
            except ValueError as e:
                raise ValueError("check expected a numerical value from WebLogic but got '" + str(value) + "'")

    def getPerformanceIndicator(self):
        return self.boundaryfloat if hasattr(self, "boundaryfloat") else False

    def getMessage(self):
        return self.message

## Const values
NAGIOS_OK = 0
NAGIOS_WARNING = 1
NAGIOS_CRITICAL = 2
NAGIOS_UNKNOWN = 3
NAGIOS_DICT = {NAGIOS_OK: "OK", NAGIOS_WARNING: "WARNING", NAGIOS_CRITICAL: "CRITICAL", NAGIOS_UNKNOWN: "UNKNOWN"}
RESULTBLOCK="[RESULT]"
SERVERBLOCK="[SERVER]"
CONFIG_FILE="restwlsconfig.yaml"
TIMEOUT_DEFAULT=10
RETRIES_DEFAULT=3

lazyMap = {}
def getValueOverJSON(url, params, key, auth, retries, timeout):
    global lazyMap
    data = False
    error = False
    result = 0
    attempts = 0
    while attempts < retries:
        try:
            if params:
                encoded = urllib.urlencode(params)
                request = urllib2.Request(url + "?" + encoded)
            else:
                request = urllib2.Request(url)
            request.add_header("Authorization", "Basic " + auth)
            response = urllib2.urlopen(request, timeout=timeout)
            responseData = response.read()
            if("Gateway Timeout") in responseData:
                raise Exception("WLS Management URL gateway timeout")
            data = json.loads(responseData)
            attempts = retries
        except urllib2.HTTPError as e:
            if "404" in str(e):
                error = "management URL incorrect for " + url + ", '" + str(e) + "'"
                attempts = retries
            else:
                error = "unknown URL error for " + url + ", '" + str(e) + "'"
                attempts = retries
        except urllib2.URLError as e:
            print(e.reason)
            if "Connection refused" in str(e):
                error = "Connection refused, giving up connecting to " + url + " attempt " + str(attempts)
                attempts = retries
            elif "timed out" in str(e):
                error = "URL error, probably a timeout when connecting to " + url + " attempt " + str(attempts)
                attempts += 1
                time.sleep(10)
        except Exception as e:
            attempts += 1
            error = "Could not correct to " + url + " attempt " + str(attempts) + " with error: " + str(e)
    ## Let's parse!
    if data:
        current = data
        try:
            keys = key.split(".")
            for curkey in keys:
                if(curkey in current):
                    current = current[curkey]
                else:
                    raise Exception("Could not find next variable " + curkey + " (" + key + ") in result from " + url)
            result = current
        except Exception as e:
            if "status" in data and data["status"] == 404:
                error = "WLS management page for url " + url + " did not exist"
            else:
                error = str(e)

    return (str(result), error)

def getCheckNames(configurations):
    return [name for name in configurations["configurations"] if "url" in configurations["configurations"][name]]

if __name__ == "__main__":
    if(os.path.exists(CONFIG_FILE)):
        configfile = open(CONFIG_FILE,"r")
        configurations = yaml.load(configfile)
    else:
        print("Could not find a YAML config file named " + CONFIG_FILE + "!")
        configurations = ["configurations"]

    description = '''
This is a support script for the "zzwlshealth" health check, used by the F5 load balancer and WebLogic to
see which WebLogic instance can receive requests. Use this script to disable a server and tell the load
balancer to stop sending requests to this specific instance.

This file expects a config file named restwlsconfig.yaml

Known checks:
'''
    description += "\n".join(getCheckNames(configurations))
    description += "\n"

    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("-c", "--check", help="Check name to run. If none, all are run (useless in a Nagios context)")
    parser.add_argument("-v", "--verbose", action='store_true', help="Enable verbose logging, not useable in Nagios contexts")
    parser.add_argument("-b", "--basicauth", action="store_true", help="Ask for credentials to generate a base auth header value, useable in the config")
    parser.add_argument("-g", "--generatenrpe", action="store_true", help="Generate the NRPE lines for all known checks")
    args = parser.parse_args()

    if args.basicauth:
        user = raw_input("Please enter the user you wish to use for monitoring [weblogic]: ")
        if not user:
            user = "weblogic"
        password = raw_input("Please enter the password for this user: ")
        userAndPass = b64encode(user + ":" + password)
        print("Your authstring is " + userAndPass)
        exit(0)

    if args.generatenrpe:
        result = "# NRPE entries generated by " + sys.argv[0] + "\n"
        pathname = os.path.realpath(__file__)
        for name in getCheckNames(configurations):
            result += "command[" + name + "]=/usr/bin/python " + pathname + " -c " + name + "\n"
        print result
        exit(0)


    if args.check:
        if args.check not in getCheckNames(configurations):
            print("UNKNOWN: Could not find " + args.check + " in the list of known checks. Run script with -h parameter to get a list of known checks.")
            exit(NAGIOS_UNKNOWN)
    else:
        print(parser.description)
        print("No known checks ocheck name was given, so we will run all known checks for testing purposes. Run with -h for more options.\n")


    for name in getCheckNames(configurations):
        config = configurations["configurations"][name]

        ## Skip unnamed configurations as they are probably used as templates
        if not args.check or args.check == name:
            ## Some setup
            nagiosResult = NAGIOS_OK
            nagiosMessage = ""
            nagiosPerformanceData = ""

            warningCheck = NagiosBoundaryCheck(False if "warning" not in config else config["warning"], config["message"])
            criticalCheck = NagiosBoundaryCheck(False if "critical" not in config else config["critical"], config["message"])
            performanceData = False if "performancedata" not in config else config["performancedata"]
            unknownToCrit = False if "unknownascritical" not in config else config["unknownascritical"]
            params = False if "parameters" not in config else config["parameters"]

            ## Set up the basic auth header
            if "username" in config:
                auth = b64encode(config["username"] + ":" + config["password"])
            else:
                auth = config["authstring"]

            servers = config["servers"].split(",") if type(config["servers"]) != list else config["servers"]

            for server in servers:
                if nagiosMessage != "":
                    nagiosMessage += ". "

                url = config["baseurl"] + config["url"]
                url = url.replace("[SERVER]", server)
                result = getValueOverJSON(url,
                                          params,
                                          config["resultattribute"],
                                          auth,
                                          retries= config["retries"] if "retries" in config else RETRIES_DEFAULT,
                                          timeout= config["timeout"] if "timeout" in config else TIMEOUT_DEFAULT)

                ## If the error message is not empty
                if result[1]:
                    nagiosResult = NAGIOS_UNKNOWN
                    nagiosMessage += server + " reports " + result[1]
                else:
                    try:
                        if criticalCheck.inBadState(result[0]):
                            nagiosResult = NAGIOS_CRITICAL if nagiosResult < NAGIOS_CRITICAL else nagiosResult
                            nagiosMessage += criticalCheck.getMessage()
                        elif warningCheck.inBadState(result[0]):
                            nagiosResult = NAGIOS_WARNING if nagiosResult < NAGIOS_WARNING else nagiosResult
                            nagiosMessage += warningCheck.getMessage()
                        else:
                            nagiosMessage += config["message"]
                    except ValueError as e:
                        nagiosResult = NAGIOS_UNKNOWN
                        nagiosMessage += "Unexpected result, " + str(e)

                ## After handling the result, transform macros in the message
                if nagiosMessage.find(RESULTBLOCK) > -1:
                    nagiosMessage = nagiosMessage.replace(RESULTBLOCK, result[0])
                if nagiosMessage.find(SERVERBLOCK) > -1:
                    nagiosMessage = nagiosMessage.replace(SERVERBLOCK, server)

                ## Now add performance data
                if performanceData:
                    if nagiosPerformanceData != "":
                        nagiosPerformanceData += " "

                    nagiosPerformanceData += "'" + server + "'=" + result[0]
                    nagiosPerformanceData += ";"
                    if warningCheck.getPerformanceIndicator():
                        nagiosPerformanceData += str(warningCheck.getPerformanceIndicator())
                    if criticalCheck.getPerformanceIndicator():
                        nagiosPerformanceData += ";" + str(criticalCheck.getPerformanceIndicator())

                if unknownToCrit and nagiosResult == NAGIOS_UNKNOWN:
                    nagiosResult = NAGIOS_CRITICAL

            if performanceData:
                print(NAGIOS_DICT[nagiosResult] + ": " + nagiosMessage + " | " + nagiosPerformanceData)
            else:
                print(NAGIOS_DICT[nagiosResult] + ": " + nagiosMessage)

            ## If running just one check, exit here
            if args.check:
                exit(nagiosResult)
    exit(0)

