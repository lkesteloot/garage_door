
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

# License

Copyright 2019 Lawrence Kesteloot

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
