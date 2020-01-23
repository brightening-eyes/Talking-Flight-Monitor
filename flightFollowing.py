
# -*- coding: iso-8859-15 -*-
#==============================================================================
# Voice Flight Following - Periodically announce cities along your flight path
# Copyright (C) 2019 by Jason Fayre
# based on the VoiceATIS addon by   Oliver Clemens
# 
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version.
# 
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.	 See the GNU General Public License for more
# details.
# 
# You should have received a copy of the GNU General Public License along with
# this program.	 If not, see <https://www.gnu.org/licenses/>.
#==============================================================================

from __future__ import division


import logging
# Import built-ins
import os
import sys
import time
import warnings
import winsound
from configparser import ConfigParser

from contextlib import closing
from math import degrees, floor

import keyboard
import requests

from aviationFormula.aviationFormula import calcBearing
from babel import Locale
from babel.dates import get_timezone, get_timezone_name
import pyglet
from accessible_output2.outputs import sapi5
from accessible_output2.outputs import auto
import numpy as np

# Import own packages.
from VaLogger import VaLogger

# initialize the log settings
logging.basicConfig(filename = 'error.log', level = logging.INFO)
# Set encoding
#reload(sys)
#sys.setdefaultencoding('iso-8859-15')  # @UndefinedVariable

# Import pyuipc package (except failure with debug mode). 


try:
    import pyuipc
    pyuipcImported = True
    debug = False
except ImportError:
        pyuipcImported = False
        debug = True

## Main Class of FlightFollowing.
# Run constructor to run the program.
class FlightFollowing:
#  - b: a 1-byte unsigned value, to be converted into a Python int
#  - c: a 1-byte signed value, to be converted into a Python int
#  - h: a 2-byte signed value, to be converted into a Python int
#  - H: a 2-byte unsigned value, to be converted into a Python int
#  - d: a 4-byte signed value, to be converted into a Python int
#  - u: a 4-byte unsigned value, to be converted into a Python long
#  - l: an 8-byte signed value, to be converted into a Python long
#  - L: an 8-byte unsigned value, to be converted into a Python long
#  - f: an 8-byte floating point value, to be converted into a Python double
# main offsets for reading instrumentation.
    OFFSETS = [(0x034E,'H'),	# com1freq
               (0x3118,'H'),	# com2freq
               (0x3122,'b'),	# radioActive
               (0x0560,'l'),	# ac Latitude
               (0x0568,'l'),	# ac Longitude
               (0x30f0,'h'),	# flaps angle
               (0x0366,'h'),	# on ground flag: 0 = airborne
               (0x0bc8,'h'),	# parking Brake: 0 off, 32767 on
               (0x3324,'d'),	#altitude in feet or meters
               (0x0020,'u'),	# ground altitude x 256
               (0x0bcc,'u'),	# spoilers armed: 0 - off, 1 - armed
               (0x07bc,'u'), # AP master switch
               (0x07c4,'u'), # AP Nav1 lock
               (0x07c8,'u'), # AP heading lock
               (0x07cc,'H'), # Autopilot heading value, as degrees*65536/360
               (0x07d0,'u'), # AP Altitude lock
               (0x07d4,'u'), # Autopilot altitude value, as metres*65536
               (0x07dc,'u'), # AP airspeed hold
               (0x07e2,'h'), # AP airspeed in knots
               (0x0580,'u'), # Heading, *360/(65536*65536) for degrees TRUE.[Can be set in slew or pause states]
               (0x02a0,'h'), # Magnetic variation (signed, –ve = West). For degrees *360/65536. Convert True headings to Magnetic by subtracting this value, Magnetic headings to True by adding this value.
               (0x0354,'H'), # transponder in BCD format
               (0x6048,'f'), # distance to next waypoint
               (0x60a4,-6), # next waypoint string
               (0x60e4,'u'), # time enroute to next waypoint in seconds
               (0x2f80,'b'), # Panel autobrake switch: 0=RTO, 1=Off, 2=brake1, 3=brake2, 4=brake3, 5=max
               (0x02b8,'u'), # TAS: True Air Speed, as knots * 128
               (0x02bc,'u'), # IAS: Indicated Air Speed, as knots * 128
               (0x0808,'u'), # Yaw damper
               (0x080c,'u'), # autothrottle TOGA
               (0x0810,'u'), # Auto throttle arm
               (0x11c6,'h'), # Mach speed *20480
               (0x60e8,'u'), # next waypoint ETA in seconds (localtime)
               (0x6050,'f'), # magnetic baring to next waypoint in radions
               (0x6137,-5), # destination airport ID string
               (0x6198,'u'), # time enroute to destination in seconds
               (0x619c,'u'), # Destination ETA in seconds (localtime)
               (0x61a0,'f'), # route total distance in meters
               (0x61a8,'f'), # estimated fuel burn in gallons






 
    ]
# Offsets for SimConnect messages.
    SIMC = [(0xb000,'u'), # changed indicator (4 bytes)
        (0xb004,'u'), # type value (4 bytes)
        (0xb008,'u'), # display duration in secs (4 bytes)
        (0xb00c,'u'), # SimConnect event ID (4 bytes)
        (0xb010,'u'), # length of data received (4 bytes)
        (0xb014,2028), # text data (<= 2028 bytes)
    ]
    # attitude indication offsets, since we need fast access to these
    attitude = [(0x0578,'d'), # Pitch, *360/(65536*65536) for degrees. 0=level, –ve=pitch up, +ve=pitch down[Can be set in slew or pause states]
        (0x057c,'d'), # Bank, *360/(65536*65536) for degrees. 0=level, –ve=bank right, +ve=bank left[Can be set in slew or pause states]


    ]
    ## Setup the FlightFollowing object.
    # Also starts the voice generation loop.
    def __init__(self,**optional):
        # Get file path.
        self.rootDir = os.path.abspath(os.path.dirname(sys.argv[0]))
        window = pyglet.window.Window()        
        @window.event
        def on_draw():
            window.clear()

        # Init logging.
        self.logger = VaLogger(os.path.join(self.rootDir,'voiceAtis','logs'))
        # initialize two config parser objects. One for defaults and one for config file.
        self.default_config = ConfigParser(allow_no_value=True)
        self.config = ConfigParser(allow_no_value=True)
        self.default_config['config'] = {'# Flight Following requires a username from the Geonames service':None,
                'geonames_username': 'your_username',
                '# voice rate for SAPI output':None,
                'voice_rate': '5',
                '# speech output: 0 - screen reader, 1 - SAPI5':None,
                'speech_output': '0',
                '# Read closest city info. ':None,
                'flight_following': '1',
                '# Automatically read aircraft instrumentation. If using Ideal Flight, you may want to turn this off.':None,
                'read_instrumentation':'1',
                '# Read SimConnect messages. Not compatible with FSX and requires latest FSUIPC.':None,
                'read_simconnect':'1',
                '# time interval for reading of nearest city, in minutes':None,
                'interval': '10',
                '# Distance units: 0 - Kilometers, 1 - Miles':None,
                'distance_units': '0'}
        self.default_config['hotkeys'] = {'# command key: This key must be pressed before the other commands listed below':None,
                'command_key': ']',
                'agl_key': 'g',
                'asl_key': 'a',
                'heading_key': 'h',
                'ias_key': 's',
                'tas_key': 't',
                'mach_key': 'm',
                'city_key': 'c',
                'waypoint_key': 'w',
                'dest_key': 'd',
                'attitude_key': '[',
                'message_key':'r'}

        # First log message.
        self.logger.info('Flight Following started')
        # check for config file. Create it if it doesn't exist.
        exists = os.path.isfile(self.rootDir + "/flightfollowing.ini")
        if exists:
            self.logger.info("config file exists.")
            self.read_config()
        else:
            self.logger.info ("no config file found. It will be created.")
            self.write_config()
            
        # Establish pyuipc connection
        while True:
            try:
                self.pyuipcConnection = pyuipc.open(0)
                self.pyuipcOffsets = pyuipc.prepare_data(self.OFFSETS)
                self.pyuipcSIMC = pyuipc.prepare_data(self.SIMC)
                self.pyuipcAttitude = pyuipc.prepare_data(self.attitude)
                self.logger.info('FSUIPC connection established.')
                break
            except NameError:
                self.pyuipcConnection = None
                self.logger.warning('Using voiceAtis without FSUIPC.')
                break
            except:
                self.logger.warning('FSUIPC: No simulator detected. Start your simulator first! Retrying in 20 seconds.')
                time.sleep(20)
        
        ## add global hotkey definitions
        self.commandKey = keyboard.add_hotkey(self.config['hotkeys']['command_key'], self.commandMode, args=(), suppress=True, timeout=2)
        # variables to track states of various aircraft instruments
        self.oldTz = 'none' ## variable for storing timezone name
        self.old_flaps = 0
        self.airborne = False
        self.oldBrake = True
        self.oldCom1 = None
        self.oldSpoilers = None
        self.oldApHeading = None
        self.oldApAltitude = None
        self.oldApYawDamper = None
        self.oldApToga = None
        self.oldApAutoThrottle = None
        self.oldTransponder = None
        self.oldWP = None
        self.oldSimCChanged = None
        self.oldAutoBrake = None
        # set up tone arrays for pitch sonification.
        self.DownTones = {}
        self.UpTones = {}
        self.adsr = pyglet.media.synthesis.ADSREnvelope(0.05, 0.02, 0.01)
        self.PitchUpVals = np.around(np.linspace(-0.1, -10, 100), 1)
        self.PitchDownVals = np.around(np.linspace(0.1, 10, 100), 1)
        self.sonifyEnabled = False

        self.PitchUpFreqs = np.linspace(800, 1200, 100)
        self.PitchDownFreqs = np.linspace(600, 200, 100)
        countDown = 0
        countUp = 0

        for i in self.PitchDownVals:
            self.DownTones[i]  = pyglet.media.StaticSource(pyglet.media.synthesis.Sine(duration=0.07, frequency=self.PitchDownFreqs[countDown], envelope=self.adsr))
            countDown += 1

        for i in self.PitchUpVals:
            self.UpTones[i] = pyglet.media.StaticSource(pyglet.media.synthesis.Triangle(duration=0.07, frequency=self.PitchUpFreqs[countUp], envelope=self.adsr))
            countUp += 1


            

        if self.FFEnabled:
            self.AnnounceInfo(triggered=0, dt=0)
        
        
        # Infinite loop.
        try:
            if self.FFEnabled:
                pyglet.clock.schedule_interval(self.AnnounceInfo, self.interval *60)
            if self.InstrEnabled:
                pyglet.clock.schedule_interval(self.readInstruments, 0.5)
            if self.SimCEnabled:
                pyglet.clock.schedule_interval(self.readSimConnectMessages, 0.5)

                
        except KeyboardInterrupt:
            # Actions at Keyboard Interrupt.
            self.logger.info('Loop interrupted by user.')
            if pyuipcImported:
                pyuipc.close()
        except Exception as e:
            logging.error('Error during main loop:' + str(e))
            logging.exception(str(e))

    def read_config(self):
            cfgfile = self.config.read(self.rootDir + "/flightfollowing.ini")
            self.geonames_username = self.config.get('config','geonames_username')
            if self.geonames_username == 'your_username':
                output = sapi5.SAPI5()
                output.speak('Error: edit the flightfollowing.ini file and add your Geo names username. exiting!')
                time.sleep(8)
                exit()

            self.interval = float(self.config.get('config','interval'))
            self.distance_units = self.config.get('config','distance_units')
            self.voice_rate = int(self.config.get('config','voice_rate'))
            if self.config['config']['speech_output'] == '1':
                self.output = sapi5.SAPI5()
                self.output.set_rate(self.voice_rate)
            else:
                self.output = auto.Auto()
            if self.config['config'].getboolean('flight_following'):
                self.FFEnabled = True
            else:
                self.FFEnabled = False
                self.output.speak('Flight Following functions disabled.')
            if self.config['config'].getboolean('read_instrumentation'):
                self.InstrEnabled = True
            else:
                self.InstrEnabled = False
                self.output.speak('instrumentation disabled.')
            if self.config['config'].getboolean('read_simconnect'):
                self.SimCEnabled = True
            else:
                self.SimCEnabled = False
                self.output.speak("Sim Connect messages disabled.")
    def write_config(self):
        with open(self.rootDir + "/flightfollowing.ini", 'w') as configfile:
            self.default_config.write(configfile)
        output = sapi5.SAPI5()
        output.speak('Configuration file created. Open the FlightFollowing.ini file and add your geonames username. Exiting.')
        time.sleep(8)
        exit()
    def sonifyPitch(self, dt):
        self.getPyuipcData()
        self.pitch= round(self.pitch, 1)
        if self.pitch > 0 and self.pitch < 10:
            self.DownTones[self.pitch].play()
        elif self.pitch < 0 and self.pitch > -10:
            self.UpTones[self.pitch].play()
        elif self.pitch == 0:
            pass




                ## handle hotkeys for reading instruments on demand
    def keyHandler(self, instrument):
        if instrument == 'asl':
            self.output.speak(f'{self.ASLAltitude} feet A S L')
            self.reset_hotkeys()
            
            
        elif instrument == 'agl':
            AGLAltitude = self.ASLAltitude - self.groundAltitude
            self.output.speak(F"{round(AGLAltitude)} feet A G L")
            self.reset_hotkeys()
        elif instrument == 'heading':
            self.output.speak(F'Heading: {self.headingCorrected}')
            self.reset_hotkeys()
        elif instrument == 'wp':
            self.readWaypoint(triggered=True)
            self.reset_hotkeys()
        elif instrument == 'tas':
            self.output.speak (F'{self.airspeedTrue} knots true')
            self.reset_hotkeys()
        elif instrument == 'ias':
            self.output.speak (F'{self.airspeedIndicated} knots indicated')
            self.reset_hotkeys()
        elif instrument == 'mach':
            self.output.speak (F'Mach {self.airspeedMach:0.2f}')
            self.reset_hotkeys()
        elif instrument =='dest':
            self.output.speak(F'Time enroute {self.DestTime}. {self.DestETA}')
            self.reset_hotkeys()
        elif instrument == 'attitude':
            if self.sonifyEnabled:
                pyglet.clock.unschedule(self.sonifyPitch)
                self.sonifyEnabled = False
                self.reset_hotkeys()
                self.output.speak ('attitude mode disabled.')
            else:
                pyglet.clock.schedule_interval(self.sonifyPitch, 0.2)
                self.sonifyEnabled = True
                self.output.speak ('attitude mode enabled')
                self.reset_hotkeys()

                





    ## Layered key support for reading various instrumentation
    def commandMode(self):
        self.aslKey= keyboard.add_hotkey (self.config['hotkeys']['asl_key'], self.keyHandler, args=(['asl']), suppress=True, timeout=2)
        self.aglKey = keyboard.add_hotkey (self.config['hotkeys']['agl_key'], self.keyHandler, args=(['agl']), suppress=True, timeout=2)
        self.cityKey = keyboard.add_hotkey(self.config['hotkeys']['city_key'], self.AnnounceInfo, args=('1'))
        self.headingKey = keyboard.add_hotkey (self.config['hotkeys']['heading_key'], self.keyHandler, args=(['heading']), suppress=True, timeout=2)
        self.WPKey = keyboard.add_hotkey (self.config['hotkeys']['waypoint_key'], self.keyHandler, args=(['wp']), suppress=True, timeout=2)
        self.tasKey = keyboard.add_hotkey (self.config['hotkeys']['tas_key'], self.keyHandler, args=(['tas']), suppress=True, timeout=2)
        self.iasKey = keyboard.add_hotkey (self.config['hotkeys']['ias_key'], self.keyHandler, args=(['ias']), suppress=True, timeout=2)
        self.machKey = keyboard.add_hotkey (self.config['hotkeys']['mach_key'], self.keyHandler, args=(['mach']), suppress=True, timeout=2)
        self.messageKey = keyboard.add_hotkey(self.config['hotkeys']['message_key'], self.readSimConnectMessages, args=('1'), suppress=True, timeout=2)
        self.destKey = keyboard.add_hotkey (self.config['hotkeys']['dest_key'], self.keyHandler, args=(['dest']), suppress=True, timeout=2)
        self.attitudeKey = keyboard.add_hotkey (self.config['hotkeys']['attitude_key'], self.keyHandler, args=(['attitude']), suppress=True, timeout=2)


        winsound.Beep(500, 100)

    def reset_hotkeys(self):
        keyboard.remove_all_hotkeys()
        self.commandKey = keyboard.add_hotkey(self.config['hotkeys']['command_key'], self.commandMode, args=(), suppress=True, timeout=2)

    ## read various instrumentation automatically such as flaps
    def readInstruments(self, dt):
        flapsTransit = False
        # Get data from simulator
        self.getPyuipcData()
        # detect if aircraft is on ground or airborne.
        if not self.onGround and not self.airborne:
            self.output.speak ("Positive rate.")
            
            self.airborne = True
        # read parking Brakes
        
        if self.oldBrake != self.parkingBrake:
            if self.parkingBrake:
                self.output.speak ("parking Brake on.")
                self.oldBrake = self.parkingBrake
            else:
                self.output.speak ("parking Brake off.")
                print ("Parking break off")

                self.oldBrake = self.parkingBrake

        
        
        # if flaps position has changed, flaps are in motion. We need to wait until they have stopped moving to read the value.
        if self.flaps != self.old_flaps:
            flapsTransit = True
            while flapsTransit:
                self.getPyuipcData()
                if self.flaps != self.old_flaps:
                    self.old_flaps = self.flaps
                    time.sleep (0.2)
                else:
                    flapsTransit = False
            self.output.speak (F'Flaps {self.flaps:.0f}')
            print (F'Flaps {self.flaps:.0f}')
            self.old_flaps = self.flaps
        # announce radio frequency changes
        if self.com1frequency != self.oldCom1:
            self.output.speak (F"com 1, {self.com1frequency}")
            self.oldCom1 = self.com1frequency
        # spoilers
        if self.spoilers == 1 and self.oldSpoilers != self.spoilers:
            self.output.speak ("spoilers armed.")
            self.oldSpoilers = self.spoilers
        if self.oldApAltitude != self.apAltitude:
            self.output.speak(F"Altitude set to {round(self.apAltitude)}")
            self.oldApAltitude = self.apAltitude
        # transponder
        if self.transponder != self.oldTransponder:
            self.output.speak(F'Squawk {self.transponder:x}')
            self.oldTransponder = self.transponder
        # next waypoint
        if self.nextWPName != self.oldWP:
            time.sleep(3)
            self.getPyuipcData()
            self.readWaypoint(0)
            self.oldWP = self.nextWPName
        # read autobrakes
        if self.autobrake != self.oldAutoBrake:
            if self.autobrake == 0:
                brake = 'R T O'
            elif self.autobrake == 1:
                brake = 'off'
            elif self.autobrake == 2:
                brake = 'position 1'
            elif self.autobrake == 3:
                brake = 'position 2'
            elif self.autobrake == 4:
                brake = 'position 3'
            elif self.autobrake == 5:
                brake = 'maximum'
            self.output.speak (F'Auto brake {brake}')
            self.oldAutoBrake = self.autobrake
        # yaw damper
        if self.oldApYawDamper != self.apYawDamper:
            if self.apYawDamper == 1:
                self.output.speak ('yaw damper on')
            else:
                self.output.speak ('yaw damper off')
            self.oldApYawDamper = self.apYawDamper
        # TOGA
        if self.oldApToga != self.apToga:
            if self.apToga == 1:
                self.output.speak ('TOGA on')
            else:
                self.output.speak ('TOGA off')
            self.oldApToga = self.apToga
        # auto throttle
        if self.oldApAutoThrottle != self.apAutoThrottle:
            if self.apAutoThrottle == 1:
                self.output.speak ('Auto Throttle armed')
            else:
                self.output.speak ('Auto Throttle off')
            self.oldApAutoThrottle = self.apAutoThrottle
        




    def secondsToText(self, secs):
        days = secs//86400
        hours = (secs - days*86400)//3600
        minutes = (secs - days*86400 - hours*3600)//60
        seconds = secs - days*86400 - hours*3600 - minutes*60
        result = ("{0} day{1}, ".format(days, "s" if days!=1 else "") if days else "") + \
        ("{0} hour{1}, ".format(hours, "s" if hours!=1 else "") if hours else "") + \
        ("{0} minute{1}, ".format(minutes, "s" if minutes!=1 else "") if minutes else "") + \
        ("{0} second{1}, ".format(seconds, "s" if seconds!=1 else "") if seconds else "")
        return result
    def readWaypoint(self, triggered=False):
        if self.distance_units == '0':
            distance = self.nextWPDistance / 1000
            self.output.speak(F'Next waypoint: {self.nextWPName}, distance: {distance:.1f} kilometers')    
        else:
            distance = (self.nextWPDistance / 1000)/ 1.609
            self.output.speak(F'Next waypoint: {self.nextWPName}, distance: {distance:.1f} miles')    
        self.output.speak (F'baring: {self.nextWPBaring:.0f}')
        # read estimated time enroute to next waypoint
        strTime = self.secondsToText(self.nextWPTime)
        self.output.speak(strTime)
        # if we were triggered with a hotkey, read the ETA to the next waypoint.
        if triggered:
            self.output.speak(F'ETA: {self.nextWPETA}')
            self.reset_hotkeys()




        

    def readSimConnectMessages(self, triggered):
        # get data from simulator
        self.getPyuipcData()
        if self.SimCEnabled:
            if self.oldSimCChanged != self.SimCChanged or triggered == '1':
                i = 1
                SimCMessageRaw = self.SimCData[:self.SimCLen]
                SimCMessage = SimCMessageRaw.split('\x00')
                for index, message in enumerate(SimCMessage):
                    if index < 2:
                        self.output.speak(f'{message}')
                    else:
                        self.output.speak(f'{i}: {message}')
                        i += 1

                self.oldSimCChanged = self.SimCChanged
                self.reset_hotkeys()
        else:
                self.reset_hotkeys()
                
    ## Announce flight following info
    def AnnounceInfo(self, dt, triggered):
        # If invoked by hotkey, reset hotkey deffinitions.
        if triggered == '1':
            self.reset_hotkeys()
            triggered = '0'
        # Get data from simulator
        self.getPyuipcData()
        # Lookup nearest cities to aircraft position using the Geonames database.
        self.airport="test"
        try:
            response = requests.get('http://api.geonames.org/findNearbyPlaceNameJSON?style=long&lat={}&lng={}&username={}&cities=cities5000&radius=200'.format(self.lat,self.lon, self.geonames_username))
            response.raise_for_status() # throw an exception if we get an error from Geonames.
            data =response.json()
            if len(data['geonames']) >= 1:
                bearing = calcBearing (self.lat, self.lon, float(data["geonames"][0]["lat"]), float(data["geonames"][0]["lng"]))
                bearing = (degrees(bearing) +360) % 360
                if self.distance_units == '1':
                    distance = float(data["geonames"][0]["distance"]) / 1.609
                    units = 'miles'
                else:
                    distance = float(data["geonames"][0]["distance"])
                    units = 'kilometers'
                self.output.speak ('Closest city: {} {}. {:.1f} {}. Bearing: {:.0f}'.format(data["geonames"][0]["name"],data["geonames"][0]["adminName1"],distance,units,bearing))
            else:
                distance = 0
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            logging.error('latitude:{}, longitude:{}'.format(self.lat, self.lon))
            logging.exception('error getting nearest city: ' + str(e))
            self.output.speak ('cannot find nearest city. Geonames connection error. Check error log.')
        except requests.exceptions.HTTPError as e:
            logging.error('latitude:{}, longitude:{}'.format(self.lat, self.lon))
            logging.exception('error getting nearest city. Error while connecting to Geonames.' + str(e))
            self.output.speak ('cannot find nearest city. Geonames may be busy. Check error log.')
            
        ## Check if we are flying over water.
        ## If so, announce body of water.
        ## We will continue to announce over water until the maximum radius of the search is reached.
        try:
            response = requests.get('http://api.geonames.org/oceanJSON?lat={}&lng={}&username={}'.format(self.lat,self.lon, self.geonames_username))
            data = response.json()
            if 'ocean' in data and distance >= 1:
                self.output.speak ('currently over {}'.format(data['ocean']['name']))
                self.oceanic = True
        except Exception as e:
            logging.error('Error determining oceanic information: ' + str(e))
            logging.exception(str(e))
            
        ## Read time zone information
        try:
            response = requests.get('http://api.geonames.org/timezoneJSON?lat={}&lng={}&username={}'.format(self.lat,self.lon, self.geonames_username))
            data = response.json()
            
            if 'timezoneId' in data:
                tz = get_timezone(data['timezoneId'])
                tzName = get_timezone_name(tz, locale=Locale.parse('en_US'))
                if tzName != self.oldTz:
                    self.output.speak ('{}.'.format(tzName))
                    self.oldTz = tzName
        except Exception as e:
            logging.error('Error determining timezone: ' + str(e))
            logging.exception(str(e))


    
    ## Read data from the simulator
    def getPyuipcData(self):
        
        if pyuipcImported:
            results = pyuipc.read(self.pyuipcOffsets)
            # prepare instrumentation variables
            hexCode = hex(results[0])[2:]
            self.com1frequency = float('1{}.{}'.format(hexCode[0:2],hexCode[2:]))
            hexCode = hex(results[1])[2:]
            self.com2frequency = float('1{}.{}'.format(hexCode[0:2],hexCode[2:]))
            # lat lon
            self.lat = results[3] * (90.0/(10001750.0 * 65536.0 * 65536.0))
            self.lon = results[4] * (360.0/(65536.0 * 65536.0 * 65536.0 * 65536.0))
            self.flaps = results[5]/ 256
            self.onGround = bool(results[6])
            self.parkingBrake = bool(results[7])
            # self.ASLAltitude = round(results[8] * 3.28084)
            self.ASLAltitude = round(results[8])
            self.groundAltitude = results[9] / 256 * 3.28084
            self.spoilers = results[10]
            self.apMaster = results[11]
            self.apNavLock = results [12]
            self.apHeadingLock = results[13]
            self.apHeading = round(results[14]/65536*360)
            self.apAltLock = results[15]
            self.apAltitude = results[16] / 65536 * 3.28084
            self.headingTrue = floor(((results[19] * 360) / (65536 * 65536)) + 0.5)
            self.headingCorrected = results[19] - (results[20] * 65536)
            self.headingCorrected = floor(self.headingCorrected * 360 / (65536 * 65536) + 0.5)
            self.transponder = results[21]
            self.nextWPDistance = results[22]
            self.nextWPName= results[23]
            self.nextWPTime = results[24]
            self.autobrake = results[25]
            self.airspeedTrue = round(results[26] / 128)
            self.airspeedIndicated = round(results[27] / 128)
            self.apYawDamper = results[28]
            self.apToga = results[29]
            self.apAutoThrottle = results[30]
            self.airspeedMach = results[31] / 20480
            self.nextWPETA = time.strftime('%H:%M', time.localtime(results[32]))
            self.nextWPBaring = degrees(results[33])
            self.DestID = results[34]
            self.DestTime =self.secondsToText(results[35])
            self.DestETA = time.strftime('%H:%M', time.localtime(results[36]))
            self.RouteDistance = results[37]
            self.FuelBurn = results[38]



            # prepare simConnect message data
            try:
                if self.SimCEnabled:
                    SimCResults= pyuipc.read(self.pyuipcSIMC)
                    self.SimCChanged = SimCResults[0]
                    self.SimCType = SimCResults[1]
                    self.SimCDuration = SimCResults[2]
                    self.SimCEvent = SimCResults[3]
                    self.SimCLen = SimCResults[4]
                    self.SimCData = SimCResults[5]
                # read attitude
                attitudeResults = pyuipc.read(self.pyuipcAttitude)
                self.pitch = attitudeResults[0] * 360 / (65536 * 65536)
                self.bank = attitudeResults[1] * 360 / (65536 * 65536)
            except Exception as e:
                pass

        else:
            self.logger.error ('FSUIPC not found! Exiting')
            exit()

if __name__ == '__main__':
    FlightFollowing = FlightFollowing()
    pyglet.app.run()
    pass
