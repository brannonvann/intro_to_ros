# neato

Turn your neato vacuum into a ROS robot. This project contains the code and instructions required to run ROS on a neato robotic vacuum.

This project is currently under development but is expected to work. Please reach out with an issue here: <https://github.com/brannonvann/neato/issues>

## Sources

This project is derived from the repository located at <https://github.com/SV-ROS/intro_to_ros>. I leveraged the project previously and found it to be very useful. This project leverages much of the code included in that project and originally created by created by Michael Ferguson. It interacts with most of the Neato API and has some clever logic that allows it to interact with a serial port without compromising the main thread for ROS.

I learned of the above package from a [Servo Magazine article](https://www.servomagazine.com/magazine/article/neato-ros-robot-navigation). They include instructions to expand on the readme in the above repository which helped me. I included those instructions where applicable in the below instructions.

This makes use of the ubiquity robotics image. This saved an enormous amount of time and makes the process far easier. Their image is excellent. I don't have one if their physical products but I would imagine they are equally great. Thank you ubiquity robotics. If you are looking for a robot base you can check out their products at <ubiquityrobotics.com>

Several of the tasks below were researched and found on various sites. I sourced those references. Thank you all for your contributions.

## Setup

This setup makes use of two computers; A raspberry pi and another computer such as a laptop. In my case I leveraged a Raspberry Pi 3 B+ (and a Pi 4 B on another) and a laptop running Ubuntu 18.04. The Raspberry Pi is the ROS master and interacts with the Neato Vac via USB. The second computer is used to control navigation of the robot through rviz. I suppose this secondary computer would not be necessary if you don't wish to create a map and have the robot navigate to locations. You could just drive it around with a controller or add additional ROS packages (or your own) to do other things.

### Raspberry Pi Setup

1.  Acquire a Raspberry Pi. I used a Model 3 B+ or 4 B however I believe these instructions will apply to other models as well.
1.  Install the Ubiquity Robotics image 2020-11-07-ubiquity-xenial-lxde from https://downloads.ubiquityrobotics.com/pi.html
1.  Install on SD card using balenaEtcher following the instructions at the link above <https://www.balena.io/etcher/>
1.  Plug into usb power and boot
1.  On another computer, join `ubiquityrobotXXXX` wi-fi, the password is `robotseverywhere`
1.  ssh into the raspberry pi `ssh ubuntu@10.42.0.1` password: `ubuntu`
1.  update password: `sudo passwd ubuntu`
1.  update hostname: `sudo pifi set-hostname HOSTNAME` and replace HOSTNAME with whatever you would like your pi's hostname to be.
1.  Add wi-fi connection: `sudo pifi add SSID PASSWORD`. Replace SSID and PASSWORD with your wi-fi's ssid and password.

1.  Restart raspberry pi: `sudo shutdown -r now`

1.  Update Ubuntu: `sudo apt-get update && sudo apt-get upgrade`

1.  Disable magni-base (the base of the ubiquityrobotics robot): `sudo systemctl disable magni-base`

1.  Install VNC Server (Optional)

    This will allow you to connect to the Pi via VNC if you want.

    source: <https://techloverhd.com/2015/05/install-lxde-vnc-gui-on-ubuntu-debian-server/>

    source for copy paste support: <https://raspberrypi.stackexchange.com/a/4475/126746>

        sudo apt-get install nano xorg lxde-core tightvncserver autocutsel

        vncserver

        vncserver -kill :1

        nano ~/.vnc/xstartup

    Change and update the file by adding the lines below (cmd+o, cmd+x).

        autocutsel -fork
        lxterminal &
        /usr/bin/lxsession -s LXDE &

        Full contents below.

        #!/bin/sh

        xrdb $HOME/.Xresources
        xsetroot -solid grey
        autocutsel -fork
        #x-terminal-emulator -geometry 80x24+10+10 -ls -title "$VNCDESKTOP Desktop" &
        #x-window-manager &
        # Fix to make GNOME work
        export XKL_XMODMAP_DISABLE=1
        /etc/X11/Xsession
        lxterminal &
        /usr/bin/lxsession -s LXDE &

    save start the server from your ssh terminal

        vncserver

    Setup a service. I used these instructions as reference: <https://raspberrypi.stackexchange.com/questions/27676/auto-start-tightvncserver-on-raspberry-pi-2>

        sudo nano /etc/init.d/tightvncserver

    add this to the new file and save. Note the user in this case is `ubuntu`

        #!/bin/sh
        # /etc/init.d/tightvncserver
        # Set the VNCUSER variable to the name of the user to start tightvncserver under
        VNCUSER='ubuntu'
        case "$1" in
        start)
            su $VNCUSER -c '/usr/bin/tightvncserver :1 -geometry 1440x900'
            echo "Starting TightVNC server for $VNCUSER"
            ;;
        stop)
            pkill Xtightvnc
            echo "Tightvncserver stopped"
            ;;
        *)
            echo "Usage: /etc/init.d/tightvncserver {start|stop}"
            exit 1
            ;;
        esac
        exit 0

    Edit file permissions:

        sudo chmod 755 /etc/init.d/tightvncserver
        sudo update-rc.d tightvncserver defaults

    For reference only, start, stop, and restart vnc service using the following commands:

        service tightvncserver start
        service tightvncserver stop
        service tightvncserver restart

    Restart the raspberry pi for it to take effect:

        sudo shutdown -r now

    It should now start up automatically at when the Raspberry Pi is started.

    Access the server from vnc client on another computer using IP_ADDRESS:1 or HOST_NAME:1 (replace IP_ADDRESS or HOST_NAME) with the raspberry pi's using the password you setup above.

1.  Make sure ROS files are up to date: `rosdep update`

1.  On both computers, download the neato files.

    Note: do this on both your PC/Laptop and the Raspberry PI.,

    <https://github.com/brannonvann/neato>

         mkdir -p ~/catkin_ws/src
         cd ~/catkin_ws/src
         git clone https://github.com/brannonvann/neato.git

1.  Install the dependencies using the following command:

        cd ~/catkin_ws
        rosdep install --from-paths src --ignore-src -r -y

1.  Run catkin_make on the catkin workspace

        cd ~/catkin_ws
        catkin_make

1.  On Raspberry Pi, update .bashrc to include the setup for neato. Make the following changes and save the file. (cmd+o, cmd+x)

        nano ~/.bashrc

    At the end of the file paste the below command aliases. This will allow you to use the command before the equal sign to execute the command after the equal sign.

        alias startnav='roslaunch neato base_nav.launch'
        alias startmap='roslaunch neato base_map.launch'
        alias startui='roslaunch neato map_gui.launch'
        alias savemap='roscd neato_nav/maps && rosrun map_server map_saver'
        alias stopneato='python ~/catkin_ws/src/neato/scripts/stop_neato.py'
        alias offneato='python ~/catkin_ws/src/neato/scripts/power_off_neato.py'

1.  Reopen terminal or run `source ~/.bashrc`

1.  Check date on the computer to make sure it is correct.

        date

    To update it install ntppdate and update using ubuntu.

        sudo apt-get install ntpdate
        sudo ntpdate ntp.ubuntu.com

1.  Plug in your Neato to the usb port. If you only have the Neato plugged in via USB this should be the correct port. If you have an older pi, I believe you may give yourself rights to access the neato robot via usb `sudo chmod 666 /dev/ttyUSB0` but I did not verify this.

        sudo chmod 666 /dev/ttyACM0

    If the command fails then check if the usb is reading/writing to a different file.

        ls /dev/ttyACM*

    or for an older raspberry pi

        ls /dev/USB*

    If it is going to another file, like ttyACM1 when there was no ttyACM0 then I found unplugging the USB from the neato waiting a minute and plugging back in resolved the issue and it started using ttyACM0 again.

1.  Setup A file share. Choose one of the options below.

I tried all three. So far each have their advantages and disadvantages. I prefer the Netatalk or SSH option but both have trouble with git from VS Code. Samba doesn't have a problem with git but the connection drops frequently and it changed my line endings.

1. File Share Option: SSH via VS Code

You can access your file system using SSH which of course is already setup. Using a text editor such as VS Code has that functionality and can be setup using these instructions: <https://code.visualstudio.com/docs/remote/remote-overview> Furthermore, setup keys to simplify the access (and make it a bit more secure): <https://code.visualstudio.com/docs/remote/troubleshooting#_quick-start-using-ssh-keys>

1.  File Share Option: Netatalk

    Source: <https://gist.github.com/kylemcdonald/c748835f1624e2bf552bf3bd4e6fbcac>

    Build and install netatalk.

        cd ~
        nano install_netatalk3.sh
        chmod u+x install_netatalk3.sh

    Paste the contents below into the file:

        #!/bin/bash

        # Enable extended attributes on filesystem
        # http://netatalk.sourceforge.net/wiki/index.php/Install_Netatalk_3.1.11_on_Ubuntu_16.04_Xenial#Setting_Up

        # Get system to updated state and install required packages
        sudo apt update
        sudo apt full-upgrade -y
        sudo apt install -y clang make libdb-dev libgcrypt20-dev libavahi-client-dev libpam0g-dev

        # Get code
        cd ~
        wget https://iweb.dl.sourceforge.net/project/netatalk/netatalk/3.1.11/netatalk-3.1.11.tar.bz2
        tar xf netatalk-3.1.11.tar.bz2 && rm netatalk-3.1.11.tar.bz2
        cd netatalk-3.1.11

        # Build and install
        ./configure --with-init-style=systemd --disable-static
        make -j $(grep -c ^processor /proc/cpuinfo)
        sudo make install-strip

        # Add to /usr/local/etc/afp.conf (uncomment)
        # [Homes]
        # basedir regex = /home

        # Enable and start
        sudo systemctl enable netatalk
        sudo systemctl start netatalk

    Execute the script:

        install_netatalk3.sh

    Setup to share the home folder.

        sudo nano /etc/netatalk/afp.conf

    Uncommented the `[Homes]` section and configure like:

        [Homes]
        basedir regex = /home

    Save and exit nano(cmd+o, cmd+x) and restart netatalk

        sudo /etc/init.d/netatalk restart

1.  File Share Option: Samba

    When I first configured my pi, I used Netatalk but there were problems with accessing the git files so I switched to samba. Below is the setup for Samba.

        sudo apt-get install samba samba-common-bin'

    Edit the config file

        sudo nano /etc/samba/smb.conf

    find the section called Share Definitions uncomment/set the following settings. Comments removed for brevity.

        #======================= Share Definitions =======================
        [homes]
        comment = Home Directories
        browseable = yes
        read only = no
        create mask = 0775
        directory mask = 0775
        valid users = ubuntu

    For reference only, start, stop, and restart samba service using the following commands:

        sudo /etc/init.d/samba start
        sudo /etc/init.d/samba stop
        sudo /etc/init.d/samba restart

1.  Setup shutdown button

    Setup a shutdown button and script so they pi can be shutdown in the event of a lost connection without unplugging. Unplugging will likely result in a corrupt microSD and require complete repeat of above instructions. These instructions have the full script with the license. They also have alternate implementations that allow for restarting. I modified the script for the purposes of this raspberry pi. The modified script is below.

    Full script (unmodified) and description and license: <https://learn.sparkfun.com/tutorials/raspberry-pi-safe-reboot-and-shutdown-button/all>

        cd ~
        nano shutdown.py

    Paste the below in the file and use the two pins closest to the ethernet port (GPIO 26 and Ground) to shutdown the pi with a jumper wire or add a button if you wish.

        # LICENSE: This code is released under the MIT License (http://opensource.org/licenses/MIT)
        #
        # Distributed as-is; no warranty is given
        #
        # -----------------------------------------------------------------------------

        import time
        import RPi.GPIO as GPIO

        # Pin definition
        shutdown_pin = 26 # BV: Default was 17

        # Suppress warnings
        GPIO.setwarnings(False)

        # Use "GPIO" pin numbering
        GPIO.setmode(GPIO.BCM)

        # Use built-in internal pullup resistor so the pin is not floating
        # if using a momentary push button without a resistor.
        GPIO.setup(shutdown_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        # Use Qwiic pHAT's pullup resistor so that the pin is not floating
        #GPIO.setup(shutdown_pin, GPIO.IN)

        # modular function to shutdown Pi
        def shut_down():
            print "shutting down"
            command = "/usr/bin/sudo /sbin/shutdown -h now"
            import subprocess
            process = subprocess.Popen(command.split(), stdout=subprocess.PIPE)
            output = process.communicate()[0]
            print output


        # Check button if we want to shutdown the Pi safely
        while True:
            # For troubleshooting, uncomment this line to output button status on command line
        # print GPIO.input(shutdown_pin)
            if GPIO.input(shutdown_pin)== False:
                shut_down()

    Make the script run at startup by adding a line to the rc.local file. Open the file for editing:

        sudo nano /etc/rc.local

    Add this above `exit 0` in the file and save and exit (cmd+o, cmd+x).

        python /home/pi/shutdown.py &

1.  If you have a logitech controller, plug the usb dongle into the raspberry pi. I use the Logitech F710. If you do not have a logitech controller, change the

### Secondary computer setup

Note: These instructions were added in retrospect and may be missing some steps. Reference sites in the [References Section](#references) if problems are encountered.

1.  Make sure ROS files are up to date: `rosdep update`

1.  On both computers, download the neato files.

    Note: do this on both your PC/Laptop and the Raspberry PI.,

    Repo: <https://github.com/brannonvann/neato>

        mkdir -p ~/catkin_ws/src
        cd ~/catkin_ws/src
        git clone https://github.com/brannonvann/neato.git

1.  Install the dependencies using the following command:

        cd ~/catkin_ws
        rosdep install --from-paths src --ignore-src -r -y

1.  do a catkin_make on the workspace

        cd ~/catkin_ws
        catkin_make

1.  Update bashrc to include the setup for neato and set the ros master to the neato computer. I believe you can use the ip address or the hostname. I used the hostname.

    nano ~/.bashrc

Near the end find the line comment out this line with a #:

    source /opt/ros/<distro>/setup.bash

Add the ros master environment variable. it should look like this after the changes. The HOSTNAME should be the one for the Raspberry Pi (Can also be the ip address).

    export ROS_MASTER_URI=http://HOSTNAME:11311

1.  Reopen terminal or run `source ~/.bashrc`

1.  Check date on both computer.

        date

    To update it install ntppdate and update using ubuntu.

        sudo apt-get install ntpdate
        sudo ntpdate ntp.ubuntu.com

## Running the robot

### Make a Map

You can run this package in two modes, Map Making and navigation. You must first make a map if you want to use the navigation.

On the Raspberry Pi run (startmap):

    roslaunch neato base_map.launch

On the secondary computer run (startui):

    roslaunch neato map_gui.launch

The lidar should start spinning on the Neato and Rviz should load on the secondary computer. I found that if the lidar doesn't show on the secondary computer when rviz loads, just close it down and restart the above command from the terminal.

If you are using a logitech controller as described above you can start driving by holding down the 'A' button and driving with the left stick or left D-pad depending on how your controller is configured (switch on top of F710). The 'A' button on the controller is called the enable_button and is configured in the logitech_teleop.launch file. The 'A' button maps to button 1 but this can be changed if you would like.

If you are not using the logitech controller and didn't change the config, the easiest thing to do is open a new terminal on either computer and run `rosrun teleop_twist_keyboard teleop_twist_keyboard.py` and the keys indicated to drive around (i,m,j,l).

### Save Your Map

This project takes advantage of static maps (rather than SLAM) so you will need to save your map after you have driven around. The map will be used to run the navigation.

On a new terminal on the Raspberry Pi run (savemap):

    roscd neato_nav/maps and rosrun map_server map_saver

### Navigate

This will load the map created previously and allow you to click on the map in RVIZ and have your robot navigate to that location. Close your previous roslaunch tasks mentioned above then:

On the Raspberry Pi run (startnav):

    roslaunch neato base_nav.launch

On the secondary computer run (startui):

    roslaunch neato map_gui.launch

You can still drive around manually if you wish using the logitech controller or using the keyboard as described above.

## Edit your map

If you would like, you may edit your map using a image editing program like Gimp. Open the `map.pgm` file saved previously. Use the grey, black, and white colors from your map to edit it. Black is a solid object, white is open space, and grey is unknown space. To save using Gimp, use the "Export as" function and save in raw form.

## Troubleshooting

I have followed this setup a few times and received different results. The one error i received about 50% of the time was `"left_wheel_joint" was received but not found in URDF`. I wasn't able to figure out what the source of this was or how to resolve the issue. The only thing I found to fix this was to follow the instructions again starting at the top with re-imaging the Raspberry Pi. If you know the cause of this or the solution, please let me know.
