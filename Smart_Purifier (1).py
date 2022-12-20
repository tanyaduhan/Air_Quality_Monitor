"""
===============================================================================
IOT Final Project: Smart Environment Purifier System
===============================================================================
"""


import os, busio, digitalio, board
import time, sys, json, atexit, math
from time import sleep
from helper import SlotHelper
from threading import Thread
from adc import ADC
from Adafruit_IO import Client, Feed, RequestError
from text_msg import send_msg
from rpi_rf import RFDevice
from signal import signal, SIGTERM, SIGHUP, SIGINT, pause
from rpi_lcd import LCD
from gpiozero import PWMOutputDevice, PWMLED

# GPIO pin and variable setup
gpioSend = 20  # GPIO pin of RF transmitter
gpioReceive = 21  # GPIO pin of RF receiver
ledPin = 26  # GPIO pin of red running LED
fanPin = 14  # GPIO pin of induction fan
updateInterval = 5  # Time in seconds between air quality updates
code = None
lcd = LCD()

led = PWMLED(ledPin)
fan = PWMOutputDevice(fanPin)

# Adafruit setup (Enter account details account)
ADAFRUIT_IO_KEY = ''
ADAFRUIT_IO_USERNAME = ''
aio = Client(ADAFRUIT_IO_USERNAME, ADAFRUIT_IO_KEY)

# ============================================================================

led.on()
fan.on()
lcd.clear()
lcd.text('SMART PURIFIER', 1)
lcd.text('INITIALIZING....', 2)
    
# Setting up Adafruit dashboard feeds
try:
    sensorValue = aio.feeds('sensor-value')
    onOff = aio.feeds('on-slash-off')
    notif = aio.feeds('notification')
    trigger = aio.feeds('trigger')
except RequestError:  # create a digital feed
    feed1 = Feed(name='Sensor Value')
    sensorValue = aio.create_feed(feed1)
    feed2 = Feed(name='ON/OFF')
    onOff = aio.create_feed(feed2)
    feed3 = Feed(name='Notification')
    notif = aio.feeds(feed3)
    feed4 = Feed(name='Trigger')
    trigger = aio.feeds(feed4)


def main():
    led.on()
    global code, protocol, pulselength, length, repeat
    
    signal(SIGTERM, safeExit)
    signal(SIGHUP, safeExit)
    atexit.register(exithandler)
    
    # Check if file containing RF code exists, create it if not (eg: on first startup)
    try:
        with open('rfCode.txt') as file:
            rfCode = file.read()
    except (IOError, FileNotFoundError):
        open('rfCode.txt', 'w')
        
        main()

    # If file is empty, go through RF setup process, then restart main function.
    if len(rfCode) == 0:
        rfSetup(gpioReceive)
        main()
    
    rfVals = json.loads(rfCode)
    
    # Assign values to variables then close file
    code = rfVals.get('code')
    protocol = rfVals.get('protocol')
    pulselength = rfVals.get('pulselength')
    length = rfVals.get('length')
    repeat = rfVals.get('repeat')
    
    file.close()
    
    readAir() 
            

# Main function to read current air quality and update Adafruit
def readAir():
    active = False
    sensor = GroveAirQualitySensor(0)
    value = sensor.value
    previous_mode = 'empty'
    
    while True:
        turnOff = aio.receive(onOff.key)
        current_mode = turnOff.value
                
        if previous_mode != current_mode:
            if str(turnOff.value) == 'ON':
                lcd.clear()
                lcd.text('MODE: NORMAL', 1)
                lcd.text('OPERATION ACTIVE', 2)
                mes = 'Reading Air Quality...'
                print(mes)
                            
                aio.send(notif.key, mes)
                previous_tri = 0
                while turnOff.value == 'ON':
                    # Obtain the trigger value
                    tri = aio.receive(trigger.key)
                    current_tri = tri.value
    
                    aio.send(sensorValue.key, value)
                    
                    if value > int(current_tri):
                        mes = '{}, Air Quality: BAD.'.format(value)
                        print(mes)
                        aio.send(notif.key, mes)
                        
                        if active == False:
                            mes1 = 'Activating air purifier...'
                            print(mes1)
                            aio.send(notif.key, mes1)
                            signalToggle(code, protocol, pulselength, length, gpioSend, repeat)
                            lcd.text('Air Quality: BAD', 1)
                            lcd.text('Status: Active', 2)
                            active = True
                            
                    elif value > 100:
                        led.pulse(fade_out_time = 3)
                        lcd.text('WARNING: DANGER', 1)
                        lcd.text('LOW AIR QUALITY', 2)
                        mes = ('AUTOMATIC WARNING MESSAGE FROM SMART PURIFIER:\n\n',
                               'Dangerously low air quality levels detected at home.')
                        aio.send(notif.key, mes)
                        send_msg(mes)
                    else:
                        mes = '{}, Air Quality: OK.'.format(value)
                        print(mes)
                        lcd.text('Air Quality: OK', 1)
                        lcd.text('Status: Inactive', 2)
                        aio.send(notif.key, mes)
                        
                        if active == True:
                            mes1 = 'Deactivating air purifier...'
                            print(mes1)
                            aio.send(notif.key, mes1)
                            signalToggle(code, protocol, pulselength, length, gpioSend, repeat)
                            lcd.text('Status: Inactive', 2)
                            active = False
                    
                    time.sleep(updateInterval)
                    
                    # Send a notification when the value is altered
                    if previous_tri != current_tri:
                        mes = 'Trigger Value Changed to {}'.format(current_tri)
                        aio.send(notif.key, mes)
                    previous_tri = current_tri
                    turnOff = aio.receive(onOff.key)
                    
            else:
                lcd.clear()
                lcd.text('MODE: SLEEP', 1)
                lcd.text('OPERATION PAUSED', 2)
                mes = 'Sleep Mode'
                print(mes)
                aio.send(notif.key, mes)
                active = False
            
        previous_mode = current_mode
        turnOff = aio.receive(onOff.key)
        current_mode = turnOff.value
                

# Function to transmit specified RF frequency to toggle outlet switch with 1 button
def signalToggle(_code, _protocol, _pulselength, _length, _gpio, _repeat):
    rfdevice = RFDevice(_gpio)
    rfdevice.enable_tx()
    rfdevice.tx_repeat = _repeat
    
    print(str(_code) +
          ' [protocol: ' + str(_protocol) +
          ', pulselength: ' + str(_pulselength) +
          ', length: ' + str(_length) +
          ', repeat: ' + str(rfdevice.tx_repeat) + ']')
    
    rfdevice.tx_code(_code, _protocol, _pulselength, _length)


# Function to retrieve specific RF signal used by the outlet switch
def rfSetup(_gpio):
    global code, protocol, pulselength, length, repeat
    
    signal(SIGINT, exithandler)
    
    rfdevice = RFDevice(_gpio)
    rfdevice.enable_rx()
    timestamp = None
    
    lcd.clear()
    lcd.text('MODE:', 1)
    lcd.text('RF SIGNAL SETUP', 2)
    
    print('Manual RF switch signal setup. This may take a few minutes.')
    print('Please repeatedly press the toggle button the remote.')
    print('Listening for RF codes on GPIO ' + str(_gpio))

    # Listen for RF code until one is detected.
    while code == None: 
        if rfdevice.rx_code_timestamp != timestamp:
            timestamp = rfdevice.rx_code_timestamp
            print('CODE ' + str(rfdevice.rx_code) +
                  ' [pulselength ' + str(rfdevice.rx_pulselength) +
                  ', protocol ' + str(rfdevice.rx_proto) + ']')
            
            code = rfdevice.rx_code
            pulselength = rfdevice.rx_pulselength
            protocol = rfdevice.rx_proto
            length = 24
            repeat = 10
        time.sleep(.01)
        
    print('RF code detected. Testing, pay attention to the RF switch...')

    # Send received RF code and ask for user input
    signalToggle(code, protocol, pulselength, length, gpioSend, repeat)
    
    confirm = str(input('Did the switch toggle? (y/n)'))

    # If switch toggled, save code to file and return. else repeat process.
    while confirm.lower() != 'y' and confirm.lower() != 'n':
        print('Error: invalid entry.')
        confirm = input('Did the switch toggle? (y/n)')
        
    if confirm.lower() == 'y':
        print('RF code saved.')
        rfData = {'code': code,
                  'protocol': protocol,
                  'pulselength': pulselength,
                  'length': length,
                  'repeat': repeat}
        
        with open('rfCode.txt', 'w') as file:
            file.write(json.dumps(rfData))
            
        file.close()
            
        return
    else:
        code = None
        rfSetup(gpioReceive)


# Exit handler function for program exit
# pylint: disable=unused-argument
def exithandler():
    lcd.text('SHUTTING DOWN...', 1)
    lcd.text('', 2)
    fan.off()
    print('Exiting...')
    sleep(2)
    led.off()
    lcd.clear()
    lcd.text('MODE: STOPPED', 1)
    lcd.text('RESTART REQUIRED', 2)
    sys.exit(0)


def safeExit(signum, frame):
    exit(1)
    

# Class defining air quality sensor.
# Note: this code was obtained from the sensor manufacturer, as is uses their
#       proprietary raspberry pi base hat to interface with the sensor.
class GroveAirQualitySensor(object):
    """
    Grove Air Quality Sensor class

    Args:
        pin(int): number of analog pin/channel the sensor connected.
    """
    def __init__(self, channel):
        self.channel = channel
        self.adc = ADC()

    @property
    def value(self):
        """
        Get the air quality strength value, badest value is 100.0%.

        Returns:
            (int): ratio, 0(0.0%) - 1000(100.0%)
        """
        
        return self.adc.read(self.channel)
 
 
main()
