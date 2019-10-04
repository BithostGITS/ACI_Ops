#!/usr/bin/env python

import os
import getpass
import urllib2
import ssl
import json
import sys
import threading
import time
import traceback
import pdb
from localutils.custom_utils import *
import interfaces.change_interface_state as shut_noshut_interfaces
import interfaces.assign_epg_interfaces as assign_epg_interfaces
import interfaces.remove_epgs_interfaces as remove_egps
#import interfaces.show_interface_epgs as show_epgs
import interfaces.show_all_endpoints_on_interface as show_all_endpoints_on_interface
import interfaces.portsanddescriptions as portsanddescriptions
import interfaces.interfacecounters as showinterface
import interfaces.switch_port_view as switch_port_view
import faults_and_logs.new_important_faults as fault_summary
import faults_and_logs.most_recent_port_down as recent_port_down
import faults_and_logs.most_recent_fault_changes as most_recent_fault_changes
import faults_and_logs.most_recent_admin_changes as most_recent_admin_changes
import faults_and_logs.most_recent_event_changes as most_recent_event_changes
import faults_and_logs.alleventsbetweendates as alleventsbetweendates
import faults_and_logs.alleventsbetweendates_fulldetail as alleventsbetweendates_fulldetail
import information.endpoint_search as ipendpoint
import information.routetranslation as epg_troubleshooting
import information.routetranslation as routetranslation
import information.routetrace as check_routing
import information.show_static_routes as show_static_routes
import configuration.create_local_span_session as create_local_span_session
import configuration.span_to_server as span_to_server
import logging

# Create a custom logger
# Allows logging to state detailed info such as module where code is running and 
# specifiy logging levels for file vs console.  Set default level to DEBUG to allow more
# grainular logging levels
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# Define logging handler for file and console logging.  Console logging can be desplayed during
# program run time, similar to print.  Program can display or write to log file if more debug 
# info needed.  DEBUG is lowest and will display all logging messages in program.  
c_handler = logging.StreamHandler()
f_handler = logging.FileHandler('file.log')
c_handler.setLevel(logging.CRITICAL)
f_handler.setLevel(logging.DEBUG)

# Create formatters and add it to handlers.  This creates custom logging format such as timestamp,
# module running, function, debug level, and custom text info (message) like print.
c_format = logging.Formatter('%(name)s - %(levelname)s - %(message)s')
f_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(funcName)s - %(message)s')
c_handler.setFormatter(c_format)
f_handler.setFormatter(f_format)

# Add handlers to the parent custom logger
logger.addHandler(c_handler)
logger.addHandler(f_handler)



# getToken is used if application is run on local machine and not directly on APIC server
# apic key word will be a string ipaddress
def getToken(apic, user, pwd):
    # Set ssl certificate to automatically verify and proceed 
    ssl._create_default_https_context = ssl._create_unverified_context
    # url POST request to login to APIC and recieve cookie hash
    url = "https://{apic}/api/aaaLogin.json".format(apic=apic)
    logger.info(url)
    # POST Login requires user creds provided in the data section of url request
    payload = '{"aaaUser":{"attributes":{"name":"%(user)s","pwd":"%(pwd)s"}}}' % {"pwd":pwd,"user":user}
    request = urllib2.Request(url, data=payload)
    # If APIC is unreachable within 4 sec cancel URL request to server, prevents long timeouts on wrong input
    response = urllib2.urlopen(request, timeout=4)
    # If successful response transfer informaton to a dictionary format using 'loads'
    token = json.loads(response.read())
    # Set global variable to access 'cookie' everywhere in current module
    global cookie
    cookie = token["imdata"][0]["aaaLogin"]["attributes"]["token"]
    return cookie

# Allows automatic APIC session cookie for URL requests if ssh to server 
# and program run directly on server, prevents two logins
def getCookie():
    # location of session token/cookie, open as read-only
    with open('/.aci/.sessions/.token', 'r') as f:
        # Set global variable to access 'cookie' everywhere in current module
        global cookie
        cookie = f.read()
        # Currently unnecessary but 'return' provided until decision for global to be removed or not 
        return cookie # str

# Test if script is run on APIC or on local computer
def localOrRemote():
    # If path exisits the program is running on APIC server and bypass login
    if os.path.isfile('/.aci/.sessions/.token'):
        # APIC requires IP in urlpath to use a loopback address with said token above
        apic = "localhost"
        # Set global variable to access 'cookie' everywhere in current module
        global cookie
        cookie = getCookie()
        user = getpass.getuser()
        # return apic hostname and discovered cookie
        return apic, user, cookie # str , str
    else:
        if os.environ.get('apic'):
            apic = os.environ.get('apic')
            user = os.environ.get('user')
            pwd = os.environ.get('password')
            cookie = getToken(apic,user,pwd)
            return apic, user, cookie
        else:    
            # if '.token' file doesn't exist than prompt APIC ip and username/password login.
            # Set defaults variables before login, allow variable to change if login attempts fail.
            # if both are False the first to 'if' conditions will not match, cause haven't attempted login.
            unauthenticated = False
            timedout = False
            # error value required to prevent Exception stating error variable not defined for use below
            error = ''
            # Loop for login Attempts, requires 'break' to exit loop
            while True:
                # Clear console ouput creating clean login screen for login attempt
                clear_screen()
                if unauthenticated:
                    #import pdb; pdb.set_trace()
                    # print error reason after cleared console screen
                    print(error)
                    # reset unauthenticated to prevent 'if' capture if failure is a different reason
                    unauthenticated = False
                # Server doesn't respond in time to login request (unreachable default 4 sec)
                elif timedout:
                    import pdb; pdb.set_trace()
                    # print error reason after cleared console screen
                    print(error)
                    # reask IP in cause IP typed incorrectly
                    apic = raw_input("Enter IP address or FQDN of APIC: ")
                    # reset time
                    timedout = False
                else:
                    print(error)
                    apic = raw_input("\nEnter IP address or FQDN of APIC: ")
                try:
                    user = raw_input('\nUsername: ')
                    pwd = getpass.getpass('Password: ')
                    getToken(apic, user,pwd)
                except urllib2.HTTPError as auth:
                    unauthenticated = True
                    error = '\n\x1b[1;31;40mAuthentication failed\x1b[0m\n'
                    continue
                except urllib2.URLError as e:
                    timedout = True
                    error = "\n\x1b[1;31;40mThere was an '%s' error connecting to APIC '%s'\x1b[0m\n" % (e.reason,apic)
                    continue
                except KeyboardInterrupt as k:
                    print("\nEnding Program\n")
                    exit()
                except Exception as e:
                    print(e)
                    print("\n\x1b[1;31;40mError has occured, please try again\x1b[0m\n")
                    continue
                break
    return apic, user, cookie

def reauthenticate(apic, error):
    unauthenticated = True
    timedout = False
    while True:
        clear_screen()
        if unauthenticated:
            #import pdb; pdb.set_trace()
            print(error)
            unauthenticated = False
        elif timedout:
            print(error)
            apic = raw_input("Enter IP address or FQDN of APIC: ")
            timedout = False
        try:
            if os.environ.get('apic'):
                print('\nLogging back into Apic...')
                time.sleep(1)
                apic = os.environ.get('apic')
                user = os.environ.get('user')
                pwd = os.environ.get('password')
                cookie = getToken(apic,user,pwd)
            else:
                user = raw_input('\nUsername: ')
                pwd = getpass.getpass('Password: ')
                cookie = getToken(apic, user,pwd)
        except urllib2.HTTPError:
            unauthenticated = True
            error = '\n\x1b[1;31;40mAuthentication failed\x1b[0m\n'
            continue
        except urllib2.URLError as e:
            timedout = True
            error = "\n\x1b[1;31;40mThere was an '%s' error connecting to APIC '%s'\x1b[0m\n" % (e.reason,apic)
            continue
        except Exception as e:
            print("\n\x1b[1;31;40mError has occured, please try again\x1b[0m\n")
            import pdb; pdb.set_trace()
            continue
        return cookie

class AuthenticationFailure(Exception):
    """Authentication Failure"""
    pass

def main():
    unauthenticated = False
    apic, current_user, cookie = localOrRemote()
    keyinterrupt = False
    while True:
        try:
            clear_screen()
            if unauthenticated:
                error = '\n\x1b[1;31;40mAuthentication Failed or timed out...restarting program\x1b[0m'
                cookie = reauthenticate(apic, error)
            unauthenticated = False
            clear_screen()
            if keyinterrupt:
                pass #cookie = refreshToken(apic, cookie)
            print('\n What would you like to do?:\n\n' +
                            '\t\x1b[1;32;40m  [INTERFACES]\n'+
                            '\t ---------------------------------------------------\n' +
                            '\t| 1.)  Shut/NoShut interfaces\n' + 
                            '\t| 2.)  Add EPGs to interfaces\n' +
                            '\t| 3.)  Remove EPGs from interfaces\n' + 
                            '\t| 4.)  Show interfaces status\n' +
                            '\t| 5.)  Show interface stats and EPGs\n' + 
                            '\t| 6.)  Show leaf port view\n' +
                            '\t| 7.)  Show leaf port view (detail)\n' + 
                            '\t| 8.)  Show Endpoints on interface (beta)\n' +
                            '\t ---------------------------------------------------\n\n' +
                            '\t  [FAULTS and LOGS]\n'
                            '\t ---------------------------------------------------\n' +
                            '\t| 9.)  Faults Summary\n' + 
                            '\t| 10.) Recent Port up/down intefaces\n'
                            '\t| 11.) Recent Faults\n' +
                            '\t| 12.) Recent Admin Changes\n' + 
                            '\t| 13.) Recent Events\n' +
                            '\t| 14.) Faults/Admin/Events Between Dates\n' + 
                            '\t| 15.) Faults/Admin/Events Between Dates (Detail)\n' +
                            '\t ---------------------------------------------------\n\n' +
                            '\t  [INFORMATION]\n'
                            '\t ---------------------------------------------------\n' +
                            '\t| 16.) Endpoint Search\n' + 
                            #'\t| 16.) Show Leaf/Spine/APIC info (Not Available)\n' +
                            #'\t| 17.) EPG to EPG troubleshooting (alpha)\n' +
                            #'\t| 18.) Route lookup to endpoint (alpha)\n' +
                            #'\t| 17.) Show all static routes\n' + 
                            '\t ---------------------------------------------------\n\n' +
                            '\t  [CONFIGURATION]\n'
                            '\t ---------------------------------------------------\n' +
                            '\t| 17.) Configure Local Span\n' + 
                            '\t| 18.) Capture server traffic ERSPAN to server (beta)\n' + 
                            #'\t| 20.) Create EPGs (Not Available)\n' +
                            #'\t| 21.) Configure interface Descriptions (Not Available)\n' + 
                            #'\t| 21.) Import/Export interface Descriptions (Not Available)\n' + 
                            '\t ---------------------------------------------------\x1b[0m')
            print('\x1b[7')
            print('\x1b[1;33;40m\x1b[5;70H -----------------------------\x1b[0m')
            print('\x1b[1;33;40m\x1b[6;70H|           Hint:             |\x1b[0m')
            print('\x1b[1;33;40m\x1b[7;70H|  Type "exit" on any input   |\x1b[0m')
            print('\x1b[1;33;40m\x1b[8;70H|    to return to main menu   |\x1b[0m')
            print('\x1b[1;33;40m\x1b[9;70H -----------------------------\x1b[0m')
            print('\x1b[8')
            cookie = refreshToken(apic, cookie)
            choosen = custom_raw_input('\x1b[u\x1b[40;1H Select a number: ')
            if choosen == '1':
                try:
                    shut_noshut_interfaces.main(apic,cookie)
                    keyinterrupt = False
                except KeyboardInterrupt as k:
                    print('\nExit to Main menu\n')
                    keyinterrupt = True
                    continue		
            elif choosen == '2':
                try:
                    assign_epg_interfaces.main(apic,cookie)
                    keyinterrupt = False
                except KeyboardInterrupt as k:
                    print('\nExit to Main menu\n')
                    keyinterrupt = True
                    continue            
            elif choosen == '3':
                try:
                    remove_egps.main(apic,cookie)
                    keyinterrupt = False
                except KeyboardInterrupt as k:
                    print('\nExit to Main menu\n')
                    keyinterrupt = True
                    continue		
            elif choosen == '4':
                try:
                    portsanddescriptions.main(apic,cookie)
                    keyinterrupt = False
                except KeyboardInterrupt as k:
                    print('\nExit to Main menu\n')
                    keyinterrupt = True
                    continue
            elif choosen == '5':
                try:
                    showinterface.main(apic,cookie)
                    keyinterrupt = False
                except KeyboardInterrupt as k:
                    print('\nExit to Main menu\n')
                    keyinterrupt = True
                    continue
            elif choosen == '6':
                try:
                    switch_port_view.main(apic,cookie)
                    keyinterrupt = False
                except KeyboardInterrupt as k:
                    print('\nExit to Main menu\n')
                    keyinterrupt = True
                    continue
            elif choosen == '7':
                try:
                    switch_port_view.main_detail(apic,cookie)
                    keyinterrupt = False
                except KeyboardInterrupt as k:
                    print('\nExit to Main menu\n')
                    keyinterrupt = True
                    continue              
            elif choosen == '8':
                try:
                    show_all_endpoints_on_interface.main(apic,cookie)
                    keyinterrupt = False
                    continue
                except KeyboardInterrupt as k:
                    print('\nExit to Main menu\n')
                    keyinterrupt = True
                    continue
            elif choosen == '9':
                try:
                    fault_summary.main(apic,cookie)
                    keyinterrupt = False
                except KeyboardInterrupt as k:
                    print('\nExit to Main menu\n')
                    keyinterrupt = True
                    continue		
            elif choosen == '10':
                try:
                    recent_port_down.main(apic,cookie)
                    keyinterrupt = False
                except KeyboardInterrupt as k:
                    print('\nExit to Main menu\n')
                    keyinterrupt = True
                    continue	
            elif choosen == '11':
                try:
                    most_recent_fault_changes.main(apic,cookie)
                    keyinterrupt = False
                except KeyboardInterrupt as k:
                    print('\nExit to Main menu\n')
                    keyinterrupt = True
                    continue
            elif choosen == '12':
                try:
                    most_recent_admin_changes.main(apic,cookie)
                    keyinterrupt = False
                except KeyboardInterrupt as k:
                    print('\nExit to Main menu\n')
                    keyinterrupt = True
                    continue
            elif choosen == '13':
                try:
                    most_recent_event_changes.main(apic,cookie)
                    keyinterrupt = False
                except KeyboardInterrupt as k:
                    print('\nExit to Main menu\n')
                    keyinterrupt = True
                    continue		
            elif choosen == '14':
                try:
                    alleventsbetweendates.main(apic,cookie)
                    keyinterrupt = False
                except KeyboardInterrupt as k:
                    print('\nExit to Main menu\n')
                    keyinterrupt = True
                    continue
            elif choosen == '15':
                try:
                    alleventsbetweendates_fulldetail.main(apic,cookie)
                    keyinterrupt = False
                except KeyboardInterrupt as k:
                    print('\nExit to Main menu\n')
                    keyinterrupt = True
                    continue
            elif choosen == '16':
                try:
                    ipendpoint.main(apic,cookie)
                    keyinterrupt = False
                except KeyboardInterrupt as k:
                    print('\nExit to Main menu\n')
                    keyinterrupt = True
                    continue		
            #elif choosen == '17':
            #    try:
            #        epg_troubleshooting.main(apic,cookie)
            #        keyinterrupt = False
            #    except KeyboardInterrupt as k:
            #        print('\nExit to Main menu\n')
            #        keyinterrupt = True
            #        continue
            #elif choosen == '18':
            #    try:
            #        routetranslation.main(apic,cookie)
            #        keyinterrupt = False
            #        continue
            #    except KeyboardInterrupt as k:
            #        print('\nExit to Main menu\n')
            #        keyinterrupt = True
            #        continue
            #elif choosen == '18':
            #    try:
            #        check_routing.main(apic,cookie)
            #        keyinterrupt = False
            #    except KeyboardInterrupt as k:
            #        print('\nExit to Main menu\n')
            #        keyinterrupt = True
            #        continue      

            #elif choosen == '17':
            #    try:
            #        show_static_routes.main(apic,cookie)
            #        keyinterrupt = False
            #    except KeyboardInterrupt as k:
            #        print('\nExit to Main menu\n')
            #        keyinterrupt = True
            #        continue

            elif choosen == '17':
                try:
                    create_local_span_session.main(apic,cookie)
                    keyinterrupt = False
                except KeyboardInterrupt as k:
                    print('\nExit to Main menu\n')
                    keyinterrupt = True
                    continue
            #elif choosen == 'exit':
            #    raise KeyboardInterrupt
            elif choosen == '18':
                try:
                    span_to_server.main(apic,cookie,current_user)
                    keyinterrupt = False
                except KeyboardInterrupt as k:
                    print('\nExit to Main menu\n')
                    keyinterrupt = True
                    continue

            
        except urllib2.HTTPError:
            logger.exception('HTTPError')
            unauthenticated = True
            continue

        except KeyboardInterrupt:
            logger.exception('KeyboardInterrupt')
            print('\nEnding Program\n')
            exit()
        except Exception:
            logger.exception('Critical Failure')
            raise

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt as k:
        print('\nEnding Program\n')
        exit()
