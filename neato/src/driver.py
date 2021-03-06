#!/usr/bin/env python

# Generic driver for the Neato XV-11 Robot Vacuum
# Copyright (c) 2010 University at Albany. All right reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#     * Redistributions of source code must retain the above copyright
#       notice, this list of conditions and the following disclaimer.
#     * Redistributions in binary form must reproduce the above copyright
#       notice, this list of conditions and the following disclaimer in the
#       documentation and/or other materials provided with the distribution.
#     * Neither the name of the University at Albany nor the names of its
#       contributors may be used to endorse or promote products derived
#       from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL VANADIUM LABS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA,
# OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE
# OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF
# ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""
driver.py is a generic driver for the Neato XV-11 Robotic Vacuum.
"""

__author__ = "ferguson@cs.albany.edu (Michael Ferguson)"

import serial
import rospy
import roslib
import time
import threading

from enum import Enum
from math import sin, cos, pi
from tf.broadcaster import TransformBroadcaster
from nav_msgs.msg import Odometry
from geometry_msgs.msg import Twist
from geometry_msgs.msg import Quaternion
from neato.msg import ButtonEvent, BumperEvent, Sensors
from sensor_msgs.msg import LaserScan, BatteryState

BASE_WIDTH = 248  # millimeters
MAX_SPEED = 300  # millimeters/second
CMD_RATE = 2

START_LIDAR = rospy.get_param('START_LIDAR', True)


class LED(Enum):
    BacklightOn = "BacklightOn"
    BacklightOff = "BacklightOff"
    ButtonAmber = "ButtonAmber"
    ButtonGreen = "ButtonGreen"
    LEDRed = "LEDRed"
    LEDGreen = "LEDGreen"
    ButtonAmberDim = "ButtonAmberDim"
    ButtonGreenDim = "ButtonGreenDim"
    ButtonOff = "ButtonOff"


class Neato:

    def __init__(self):
        """ Start up connection to the Neato Robot. """
        rospy.init_node('neato')  # ,anonymous = True

        port = rospy.get_param('~port', "/dev/ttyACM0")
        rospy.loginfo("Using port: %s" % port)

        self.port = serial.Serial(port, 115200, timeout=0.1)

        if not self.port.isOpen():
            rospy.logerror("Failed To Open Serial Port")
            return

        rospy.loginfo("Opened Serial Port %s" % port)

        # Storage for state tracking
        self.state = {"LeftWheel_PositionInMM": 0, "RightWheel_PositionInMM": 0,
                      "LSIDEBIT": False, "RSIDEBIT": False,
                      "LFRONTBIT": False, "RFRONTBIT": False,
                      "LeftDropInMM": 0, "RightDropInMM": 0,
                      "LeftMagSensor": 0, "RightMagSensor": 0,
                      "BTN_SOFT_KEY": False, "BTN_SCROLL_UP": False,
                      "BTN_START": False, "BTN_BACK": False,
                      "BTN_SCROLL_DOWN": False
                      }

        self.stop_state = True
        self.moving_forward = False
        self.lifted = False

        # turn things on
        self.comsData = []
        self.responseData = []
        self.currentResponse = []

        self.reading = False

        self.readLock = threading.RLock()
        self.readThread = threading.Thread(None, self.read)
        self.readThread.start()

        self.port.flushInput()
        self.sendCmd("\n\n\n")
        self.port.flushInput()

        self.setTestMode("On")
        self.setLed(LED.BacklightOn)
        self.setLed(LED.LEDGreen)

        time.sleep(0.5)

        self.base_width = BASE_WIDTH
        self.max_speed = MAX_SPEED

        # set initial read values from neato
        self.getDigitalSensors()
        time.sleep(0.5)
        self.getAnalogSensors()
        time.sleep(0.5)
        self.getCharger()
        time.sleep(0.5)
        self.getButtons()

        self.flush()

        # initialize publishers and subscribers
        rospy.Subscriber("cmd_vel", Twist, self.cmdVelCb)
        self.scanPub = rospy.Publisher('base_scan', LaserScan, queue_size=10)
        self.odomPub = rospy.Publisher('odom', Odometry, queue_size=10)
        self.batteryPub = rospy.Publisher(
            'sensor_msgs', BatteryState, queue_size=10)
        self.buttonEventPub = rospy.Publisher(
            'neato/button_event', ButtonEvent, queue_size=10)
        self.bumperEventPub = rospy.Publisher(
            'neato/bumper_event', BumperEvent, queue_size=10)
        self.sensorsPub = rospy.Publisher(
            'neato/sensors', Sensors, queue_size=10)

        self.odomBroadcaster = TransformBroadcaster()
        self.cmd_vel = [0, 0]
        self.old_vel = self.cmd_vel

    def spin(self):
        encoders = [0, 0]

        self.x = 0  # position in xy plane
        self.y = 0
        self.th = 0
        then = rospy.Time.now()

        # things that don't ever change
        scan_link = rospy.get_param('~frame_id', 'base_laser_link')
        scan = LaserScan(header=rospy.Header(frame_id=scan_link))

        scan.angle_min = 0.0
        scan.angle_max = 359.0 * pi / 180.0
        scan.angle_increment = pi / 180.0
        scan.range_min = 0.020
        scan.range_max = 5.0

        odom = Odometry(header=rospy.Header(frame_id="odom"),
                        child_frame_id='base_footprint')

        # main loop of driver
        r = rospy.Rate(20)
        cycle_count = 0
        self.bumperEngaged = None

        while not rospy.is_shutdown():

            # Emergency shutdown checks.
            if int(self.chargerValues["FuelPercent"]) < 10:
                rospy.logerr("Neato battery is less than 10%. Terminating Node")
                rospy.signal_shutdown(
                    "Neato battery is less than 10%. Terminating Node")
                break
            if self.chargerValues["BatteryFailure"] == "1":
                rospy.logerr("Neato battery failure. Terminating Node")
                rospy.signal_shutdown(
                    "Neato battery failure. Terminating Node")
                break
            if self.chargerValues["EmptyFuel"] == "1":
                rospy.logerr("Neato battery is empty. Terminating Node")
                break

            # get motor encoder values
            left, right = self.getMotors()

            if not self.lifted and cycle_count % 2 == 0:

                # bumper engaged procedure
                # left or right bumpers
                if self.moving_forward and self.bumperEngaged == 0:
                    # left bump
                    self.setMotors(-100, -110, MAX_SPEED/2)

                if self.moving_forward and self.bumperEngaged == 1:
                    # right bump
                    self.setMotors(-110, -100, MAX_SPEED/2)

                # all other bumpers
                elif self.moving_forward and self.bumperEngaged > 1:
                    self.setMotors(-100, -100, MAX_SPEED/2)

                # undock proceedure
                if self.cmd_vel[0] and self.chargerValues["ChargingActive"]:
                    self.setMotors(-400, -400, MAX_SPEED/2)

                else:
                    # send updated movement commands
                    self.setMotors(self.cmd_vel[0], self.cmd_vel[1],
                                   max(abs(self.cmd_vel[0]), abs(self.cmd_vel[1])))

            self.old_vel = self.cmd_vel

            # prepare laser scan
            scan.header.stamp = rospy.Time.now()

            self.getldsscan()
            scan.ranges, scan.intensities = self.getScanRanges()

            # now update position information
            dt = (scan.header.stamp - then).to_sec()
            then = scan.header.stamp

            d_left = (left - encoders[0]) / 1000.0
            d_right = (right - encoders[1]) / 1000.0
            encoders = [left, right]

            dx = (d_left + d_right) / 2
            dth = (d_right - d_left) / (self.base_width / 1000.0)

            x = cos(dth) * dx
            y = -sin(dth) * dx
            self.x += cos(self.th) * x - sin(self.th) * y
            self.y += sin(self.th) * x + cos(self.th) * y
            self.th += dth

            # prepare tf from base_link to odom
            quaternion = Quaternion()
            quaternion.z = sin(self.th / 2.0)
            quaternion.w = cos(self.th / 2.0)

            # prepare odometry
            odom.header.stamp = rospy.Time.now()
            odom.pose.pose.position.x = self.x
            odom.pose.pose.position.y = self.y
            odom.pose.pose.position.z = 0
            odom.pose.pose.orientation = quaternion
            odom.twist.twist.linear.x = dx / dt
            odom.twist.twist.angular.z = dth / dt

            # read sensors and data
            # Neato cannot handle reads of all sensors every cycle.
            # use cycle_count to rate limit the reads or
            # you will get errors like:
            # navigation costmap2DROS transform timeout.
            # Could not get robot pose.

            if cycle_count % 2 == 0:
                self.getDigitalSensors()

                for i, b in enumerate(("LSIDEBIT", "RSIDEBIT",
                                       "LFRONTBIT", "RFRONTBIT")):

                    engaged = None
                    engaged = self.digitalSensors[b]  # Bumper Switches
                    self.bumperHandler(b, engaged, i)

            if cycle_count == 2:
                self.getAnalogSensors()

                for i, b in enumerate(("LeftDropInMM", "RightDropInMM",
                                       "LeftMagSensor", "RightMagSensor")):

                    engaged = None
                    if i < 2:
                        # Optical Sensors (no drop: ~0-60)
                        engaged = (self.analogSensors[b] > 100)
                    else:
                        # Mag Sensors (no mag: ~ +/-20)
                        engaged = (abs(self.analogSensors[b]) > 20)

                    self.bumperHandler(b, engaged, i)

            if cycle_count == 1:
                self.getButtons()

                # region Publish Button Events

                for i, b in enumerate(("BTN_SOFT_KEY", "BTN_SCROLL_UP", "BTN_START",
                                       "BTN_BACK", "BTN_SCROLL_DOWN")):
                    engaged = (self.buttons[b] == 1)
                    if engaged != self.state[b]:
                        buttonEvent = ButtonEvent()
                        buttonEvent.button = i
                        buttonEvent.engaged = engaged
                        self.buttonEventPub.publish(buttonEvent)

                    self.state[b] = engaged

                # endregion Publish Button Info

            if cycle_count == 3:
                self.getCharger()

                # region Publish Battery Info
                # pulls data from analogSensors and charger info to publish battery state
                battery = BatteryState()
                # http://docs.ros.org/en/api/sensor_msgs/html/msg/BatteryState.html

                power_supply_health = 1  # POWER_SUPPLY_HEALTH_GOOD
                if self.chargerValues["BatteryOverTemp"]:
                    power_supply_health = 2  # POWER_SUPPLY_HEALTH_OVERHEAT
                elif self.chargerValues["EmptyFuel"]:
                    power_supply_health = 3  # POWER_SUPPLY_HEALTH_DEAD
                elif self.chargerValues["BatteryFailure"]:
                    power_supply_health = 5  # POWER_SUPPLY_HEALTH_UNSPEC_FAILURE

                power_supply_status = 3  # POWER_SUPPLY_STATUS_NOT_CHARGING
                if self.chargerValues["ChargingActive"]:
                    power_supply_status = 1  # POWER_SUPPLY_STATUS_CHARGING
                elif (self.chargerValues["FuelPercent"] == 100):
                    power_supply_status = 4  # POWER_SUPPLY_STATUS_FULL

                battery.voltage = self.analogSensors["BatteryVoltageInmV"] // 1000
                # battery.temperature = self.analogSensors["BatteryTemp0InC"]
                battery.current = self.analogSensors["CurrentInmA"] // 1000
                # battery.charge
                # battery.capacity
                # battery.design_capacity
                battery.percentage = self.chargerValues["FuelPercent"]
                battery.power_supply_status = power_supply_status
                battery.power_supply_health = power_supply_health
                battery.power_supply_technology = 1  # POWER_SUPPLY_TECHNOLOGY_NIMH
                battery.present = self.chargerValues['FuelPercent'] > 0
                # battery.cell_voltage
                # battery.cell_temperature
                # battery.location
                # battery.serial_number
                self.batteryPub.publish(battery)

                # endregion Publish Battery Info

            self.publishSensors()
            # region publish lidar and odom
            self.odomBroadcaster.sendTransform(
                (self.x, self.y, 0),
                (quaternion.x, quaternion.y, quaternion.z, quaternion.w), then,
                "base_footprint", "odom")
            self.scanPub.publish(scan)
            self.odomPub.publish(odom)

            # endregion publish lidar and odom

            # wait, then do it again
            r.sleep()

            cycle_count = cycle_count + 1
            if cycle_count == 4:
                cycle_count = 0

        # shut down
        self.setLed(LED.BacklightOff)
        self.setLed(LED.ButtonOff)
        self.setLdsRotation("Off")
        self.testmode("Off")

    def publishSensors():

        # region Publish Sensors

        self.sensors = Sensors()

        # for i, s in enumerate(self.analogSensors):
        #    self.sensors[s] = self.analogSensors[s]

        # for i, s in enumerate(self.digitalSensors):
        #    self.sensors[s] = self.digitalSensors

        # if you receive an error similar to "KeyError: 'XTemp0InC'" after startup
        # just comment out the value. It means it's not supported by your neato.

        self.WallSensorInMM = self.analogSensors["WallSensorInMM"]
        self.sensors.BatteryVoltageInmV = self.analogSensors["BatteryVoltageInmV"]
        self.sensors.LeftDropInMM = self.analogSensors["LeftDropInMM"]
        self.sensors.RightDropInMM = self.analogSensors["RightDropInMM"]
        # self.sensors.XTemp0InC = self.analogSensors["XTemp0InC"]
        # self.sensors.XTemp1InC = self.analogSensors["XTemp1InC"]
        self.sensors.LeftMagSensor = self.analogSensors["LeftMagSensor"]
        self.sensors.RightMagSensor = self.analogSensors["RightMagSensor"]
        self.sensors.UIButtonInmV = self.analogSensors["UIButtonInmV"]
        self.sensors.VacuumCurrentInmA = self.analogSensors["VacuumCurrentInmA"]
        self.sensors.ChargeVoltInmV = self.analogSensors["ChargeVoltInmV"]
        self.sensors.BatteryTemp0InC = self.analogSensors["BatteryTemp0InC"]
        self.sensors.BatteryTemp1InC = self.analogSensors["BatteryTemp1InC"]
        self.sensors.CurrentInmA = self.analogSensors["CurrentInmA"]
        self.sensors.SideBrushCurrentInmA = self.analogSensors["SideBrushCurrentInmA"]
        self.sensors.VoltageReferenceInmV = self.analogSensors["VoltageReferenceInmV"]
        self.sensors.AccelXInmG = self.analogSensors["AccelXInmG"]
        self.sensors.AccelYInmG = self.analogSensors["AccelYInmG"]
        self.sensors.AccelZInmG = self.analogSensors["AccelZInmG"]

        self.sensors.SNSR_DC_JACK_CONNECT = self.digitalSensors["SNSR_DC_JACK_CONNECT"]
        self.sensors.SNSR_DUSTBIN_IS_IN = self.digitalSensors["SNSR_DUSTBIN_IS_IN"]
        self.sensors.SNSR_LEFT_WHEEL_EXTENDED = self.digitalSensors["SNSR_LEFT_WHEEL_EXTENDED"]
        self.sensors.SNSR_RIGHT_WHEEL_EXTENDED = self.digitalSensors[
            "SNSR_RIGHT_WHEEL_EXTENDED"]
        self.sensors.LSIDEBIT = self.digitalSensors["LSIDEBIT"]
        self.sensors.LFRONTBIT = self.digitalSensors["LFRONTBIT"]
        self.sensors.RSIDEBIT = self.digitalSensors["RSIDEBIT"]
        self.sensors.RFRONTBIT = self.digitalSensors["RFRONTBIT"]

        self.lifted = (
            self.sensors.SNSR_LEFT_WHEEL_EXTENDED or self.sensors.SNSR_RIGHT_WHEEL_EXTENDED)

        self.sensorsPub.publish(self.sensors)

        # endregion Publish Sensors

    def bumperHandler(self, name, engaged, i):
        if engaged != self.state[name]:

            # set bumper
            if not this.bumperEngaged:
                this.bumperEngaged = bumperIndex

            # clear bumper
            elif this.bumperEngaged == bumperIndex and not engaged:
                this.bumperEngaged = None

            bumperEvent = BumperEvent()
            bumperEvent.bumper = bumperIndex
            bumperEvent.engaged = engaged
            # rospy.loginfobumperEvent)
            self.bumperEventPub.publish(bumperEvent)

        self.state[name] = engaged

    def sign(self, a):
        if a >= 0:
            return 1
        else:
            return -1

    def cmdVelCb(self, req):
        x = req.linear.x * 1000
        th = req.angular.z * (self.base_width / 2)
        k = max(abs(x - th), abs(x + th))
        # sending commands higher than max speed will fail

        if k > self.max_speed:
            x = x * self.max_speed / k
            th = th * self.max_speed / k

        self.cmd_vel = [int(x - th), int(x + th)]

    def exit(self):
        self.setLdsRotation("Off")
        self.setLed(LED.ButtonOff)

        time.sleep(1)

        self.testmode("Off")
        self.port.flush()

        self.reading = False
        self.readThread.join()

        self.port.close()

    def testmode(self, value):
        """ Turn test mode on/off. """
        self.sendCmd("testmode " + value)

    def setLdsRotation(self, value):
        self.sendCmd("setldsrotation " + value)

    def getldsscan(self):
        """ Ask neato for an array of scan reads. """
        self.sendCmd("getldsscan")

    def getScanRanges(self):
        """ Read values of a scan -- call requestScan first! """
        ranges = list()
        intensities = list()

        angle = 0

        if not self.readTo("AngleInDegrees"):
            self.flush()
            return ranges, intensities

        last = False
        while not last:  # angle < 360:
            try:
                vals, last = self.getResponse()
            except Exception as ex:
                rospy.logerr("Exception Reading Neato lidar: " + str(ex))
                last = True
                vals = []

            vals = vals.split(",")

            if ((not last) and ord(vals[0][0]) >= 48
                    and ord(vals[0][0]) <= 57):
                # rospy.loginfo(angle, vals)
                try:
                    a = int(vals[0])
                    r = int(vals[1])
                    i = int(vals[2])
                    e = int(vals[3])

                    while (angle < a):
                        ranges.append(0)
                        intensities.append(0)
                        angle += 1

                    if (e == 0):
                        ranges.append(r / 1000.0)
                        intensities.append(i)
                    else:
                        ranges.append(0)
                        intensities.append(0)
                except:
                    ranges.append(0)
                    intensities.append(0)

                angle += 1

        if len(ranges) != 360:
            rospy.loginfo("Missing laser scans: got %d points" % len(ranges))

        return ranges, intensities

    def setMotors(self, l, r, s):
        """ Set motors, distance left & right + speed """
        # This is a work-around for a bug in the Neato API. The bug is that the
        # robot won't stop instantly if a 0-velocity command is sent - the robot
        # could continue moving for up to a second. To work around this bug, the
        # first time a 0-velocity is sent in, a velocity of 1,1,1 is sent. Then,
        # the zero is sent. This effectively causes the robot to stop instantly.
        if (int(l) == 0 and int(r) == 0 and int(s) == 0):
            if (not self.stop_state):
                self.stop_state = True
                l = 1
                r = 1
                s = 1
        else:
            self.stop_state = False

        self.moving_forward = (l > 0 or r > 0)

        self.sendCmd("setmotor" + " lwheeldist " + str(int(l)) +
                     " rwheeldist " + str(int(r)) + " speed " + str(int(s)))

    def getMotors(self):
        """ Update values for motors in the self.state dictionary.
            Returns current left, right encoder values. """

        self.sendCmd("getmotors")

        if not self.readTo("Parameter"):
            self.flush()
            return [0, 0]

        last = False
        while not last:
            # for i in range(len(xv11_motor_info)):
            try:
                vals, last = self.getResponse()
                # rospy.loginfo(vals,last)
                values = vals.split(",")
                self.state[values[0]] = float(values[1])
            except Exception as ex:
                rospy.logerr("Exception Reading Neato motors: " + str(ex))

        return [
            self.state["LeftWheel_PositionInMM"],
            self.state["RightWheel_PositionInMM"]
        ]

    def getAnalogSensors(self):
        """ Update values for analog sensors in the self.state dictionary. """

        self.sendCmd("getanalogsensors")

        if not self.readTo("SensorName"):
            self.flush()
            return

        last = False
        analogSensors = {}
        while not last:  # for i in range(len(xv11_analog_sensors)):
            try:
                vals, last = self.getResponse()
                values = vals.split(",")
                # self.state[values[0]] = int(values[1])
                analogSensors[values[0]] = int(values[1])
            except Exception as ex:
                rospy.logerr("Exception Reading Neato Analog sensors: " +
                             str(ex))

        if analogSensors:
            self.analogSensors = analogSensors

        return analogSensors

    def getDigitalSensors(self):
        """ Update values for digital sensors in the self.state dictionary. """

        self.sendCmd("getdigitalsensors")

        if not self.readTo("Digital Sensor Name"):
            self.flush()
            return {}

        last = False
        digitalSensors = {}
        while not last:  # for i in range(len(xv11_digital_sensors)):
            try:
                vals, last = self.getResponse()
                # rospy.loginfo(vals)
                values = vals.split(",")
                # rospy.loginfo("Got Sensor: %s=%s" %(values[0],values[1]))
                # self.state[values[0]] = int(values[1])
                digitalSensors[values[0]] = int(values[1])
            except Exception as ex:
                rospy.logerr("Exception Reading Neato Digital sensors: " +
                             str(ex))

        if digitalSensors:
            self.digitalSensors = digitalSensors

        return digitalSensors

    def getButtons(self):
        """ Get button values from neato. """

        self.sendCmd("GetButtons")

        if not self.readTo("Button Name"):
            self.flush()
            return {}

        last = False
        buttons = {}
        while not last:
            vals, last = self.getResponse()
            values = vals.split(",")
            try:
                # self.state[values[0]] = (values[1] == '1')
                buttons[values[0]] = (values[1] == '1')
            except Exception as ex:
                rospy.logerr("Exception Reading Neato button info: " +
                             str(ex))

        if buttons:
            self.buttons = buttons

        return buttons

    def getCharger(self):
        """ Update values for charger/battery related info in self.state dictionary. """

        self.sendCmd("getcharger")

        if not self.readTo("Label"):
            self.flush()
            return

        last = False
        chargerValues = {}
        while not last:  # for i in range(len(xv11_charger_info)):

            vals, last = self.getResponse()
            values = vals.split(",")
            try:
                if values[0] in ["VBattV", "VExtV"]:
                    # convert to millivolt to maintain as int and become mVBattV & mVExtV.
                    # self.state['m' + values[0]] = int(float(values[1]) * 100)
                    chargerValues['m' + values[0]] = int(
                        float(values[1]) * 100)
                elif values[0] in ["BatteryOverTemp", "ChargingActive", "ChargingEnabled", "ConfidentOnFuel", "OnReservedFuel", "EmptyFuel", "BatteryFailure", "ExtPwrPresent"]:
                    # boolean values
                    # self.state[values[0]] = (values[1] == '1')
                    chargerValues[values[0]] = (values[1] == '1')
                elif values[0] in ["FuelPercent", "MaxPWM", "PWM"]:
                    # int values
                    # self.state[values[0]] = int(values[1])
                    chargerValues[values[0]] = int(values[1])
                # other values not supported.

            except Exception as ex:
                rospy.logerr("Exception Reading Neato charger info: " +
                             str(ex))

        if chargerValues:
            self.chargerValues = chargerValues
        return chargerValues

    def setLed(self, command):
        self.sendCmd("setled %s" % command)

    def sendCmd(self, cmd):
        # rospy.loginfo("Sent command: %s"%cmd)
        self.port.write("%s\n" % cmd)

    def readTo(self, tag, timeout=1):
        try:
            line, last = self.getResponse(timeout)
        except:
            return False

        if line == "":
            return False

        while line.split(",")[0] != tag:
            try:
                line, last = self.getResponse(timeout)
                if line == "":
                    return False
            except:
                return False

        return True

    # thread to read data from the serial port
    # buffers each line in a list (self.comsData)
    # when an end of response (^Z) is read, adds the complete list of response lines to self.responseData and resets the comsData list for the next command response.
    def read(self):
        self.reading = True
        line = ""

        while (self.reading and not rospy.is_shutdown()):
            try:
                # read from serial 1 char at a time so we can parse each character
                val = self.port.read(1)
            except Exception as ex:
                rospy.logerr("Exception Reading Neato Serial: " + str(ex))
                val = []

            if len(val) > 0:
                '''
                if ord(val[0]) < 32:
                    rospy.loginfo"'%s'"% hex(ord(val[0])))
                else:
                    rospy.loginfo"'%s'"%str(val))
                '''

                if ord(val[0]) == 13:  # ignore the CRs
                    pass

                elif ord(val[0]) == 26:  # ^Z (end of response)
                    if len(line) > 0:
                        # add last line to response set if it is not empty
                        self.comsData.append(line)
                        # rospy.loginfo"Got Last Line: %s" % line)
                        line = ""  # clear the line buffer for the next line

                    # rospy.loginfo("Got Last")
                    with self.readLock:  # got the end of the command response so add the full set of response data as a new item in self.responseData
                        self.responseData.append(list(self.comsData))

                    self.comsData = [
                    ]  # clear the bucket for the lines of the next command response

                # NL, terminate the current line and add it to the response data list (comsData) (if it is not a blank line)
                elif ord(val[0]) == 10:
                    if len(line) > 0:
                        self.comsData.append(line)
                        # rospy.loginfo"Got Line: %s" % line)
                        line = ""  # clear the bufer for the next line
                else:
                    line = line + val  # add the character to the current line buffer

    # read response data for a command
    # returns tuple (line,last)
    # line is one complete line of text from the command response
    # last = true if the line was the last line of the response data (indicated by a ^Z from the neato)
    # returns the next line of data from the buffer.
    # if the line was the last line last = true
    # if no data is avaialable and we timeout returns line=""
    def getResponse(self, timeout=1):

        # if we don't have any data in currentResponse, wait for more data to come in (or timeout)
        while (len(self.currentResponse)
               == 0) and (not rospy.is_shutdown()) and timeout > 0:

            # pop a new response data list out of self.responseData (should contain all data lines returned for the last sent command)
            with self.readLock:
                if len(self.responseData) > 0:
                    self.currentResponse = self.responseData.pop(0)
                    # rospy.loginfo("New Response Set")
                else:
                    self.currentResponse = []  # no data to get

            if len(self.currentResponse
                   ) == 0:  # nothing in the buffer so wait (or until timeout)
                time.sleep(0.010)
                timeout = timeout - 0.010

        # default to nothing to return
        line = ""
        last = False

        # if currentResponse has data pop the next line
        if not len(self.currentResponse) == 0:
            line = self.currentResponse.pop(0)
            # rospy.loginfo(line,len(self.currentResponse))
            if len(self.currentResponse) == 0:
                last = True  # if this was the last line in the response set the last flag
        else:
            rospy.loginfo("Time Out")  # no data so must have timedout
        # rospy.loginfo("Got Response: %s, Last: %d" %(line,last))
        return (line, last)

    def flush(self):
        while (1):
            l, last = self.getResponse(1)
            if l == "":
                return


if __name__ == "__main__":
    robot = Neato()
    robot.spin()
