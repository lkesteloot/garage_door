
# Garage door

Code for a Raspberry Pi program that:

* Monitors a garage door to see if it's open.
* Sends an SMS if it's been open too long.
* Provides a web page for opening and closing the door.
* Plays music on the speaker when a button is pressed.

# Configure

Modify the constants at the top of `dist/opt/garage/garage.py` (`AUTH_USERNAME`, etc.).

# Install

    make install

# Dependencies

* sudo apt-get install upstart
* sudo apt-get install python-dev
* sudo apt-get install python-rpi.gpio
* sudo apt-get install python-tornado
* sudo apt-get install sqlite3

