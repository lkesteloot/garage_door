
# Program to monitor and control a garage door.

import tornado.ioloop
import tornado.web
import tornado.options
import RPi.GPIO as GPIO
import urllib
import urllib2
import base64
import time
import logging
import sqlite3
import functools
import subprocess
import re

# We have a B rev 2.
REED_PIN = 11 # Board pin 11, GPIO pin 17.
RELAY_PIN = 12 # Board pin 12, GPIO pin 18.
LED_PIN = 13 # Board pin 13, GPIO pin 27 (on B rev 2).
BUTTON_PIN = 15 # Board pin 15, GPIO pin 22.
AUTH_USERNAME = "PUT CONTROL USERNAME HERE"
AUTH_PASSWORD = "PUT CONTROL PASSWORD HERE"
TWILIO_SID = "PUT TWILIO SID HERE"
TWILIO_TOKEN = "PUT TWILIO TOKEN HERE"
TWILIO_SOURCE_PHONE_NUMBER = "PUT TWILIO SOURCE PHONE NUMBER HERE"
ADMIN_PHONE_NUMBER = "PUT YOUR PHONE NUMBER HERE"
ALL_PHONE_NUMBERS = [ADMIN_PHONE_NUMBER]
CHECK_PERIOD_S = 1
DEBOUNCE_S = 0.030
WARN_TIME_S = 60*5
SEND_TEXT_ENABLED = True
# Low bit rate:
RADIO_URL = "http://stream-sd.radioparadise.com:9000/rp_32.ogg"
# High bit rate:
RADIO_URL = "http://stream-tx3.radioparadise.com:80/mp3-192"

gIoLoop = None
gDoorIsOpen = False
gLastDoorChangeTime = time.time()
gWarned = False
gDb = None
gDebounceTimeout = None
gPreviousButton = False
gPlayer = None
gSongName = None
gSongUrl = None

# -----------------------------------------------------------------------------------------------
# Utilities

def pluralize(count, singular_noun, plural_noun=None):
    if count == 1:
        return "%d %s" % (count, singular_noun)
    else:
        return "%d %s" % (count, plural_noun or singular_noun + "s")

def secondsToString(seconds):
    seconds = int(seconds)
    hours = seconds // (60*60)
    minutes = (seconds // 60) % 60
    seconds = seconds % 60

    fields = []
    if hours != 0:
        fields.append(pluralize(hours, "hour"))
    if minutes != 0:
        fields.append(pluralize(minutes, "minute"))
    if seconds != 0 or not fields:
        fields.append(pluralize(seconds, "second"))

    return " ".join(fields)

# Decorator for Tornado get/post methods for Basic auth. The "authFn"
# parameter should be a function that takes a username and password
# and returns whether they are authorized.
def authenticated(authFn):
    def decore(f):
        def _request_auth(handler):
            handler.set_header('WWW-Authenticate', 'Basic realm=garage')
            handler.set_status(401)
            handler.finish()

        @functools.wraps(f)
        def new_f(*args):
            handler = args[0]

            auth_header = handler.request.headers.get('Authorization')
            if auth_header is None or not auth_header.startswith('Basic '):
                _request_auth(handler)
            else:
                auth_decoded = base64.decodestring(auth_header[6:])
                username, password = auth_decoded.split(':', 2)

                if authFn(username, password):
                    # Insert username as second parameter (after "self").
                    newArgs = args[:1] + (username,) + args[1:]
                    f(*newArgs)
                else:
                    addEvent("Invalid auth for control page")
                    _request_auth(handler)

        return new_f
    return decore

# -----------------------------------------------------------------------------------------------
# GPIO

def initGpio():
    GPIO.cleanup()
    GPIO.setmode(GPIO.BOARD)
    GPIO.setup(RELAY_PIN, GPIO.OUT, initial=GPIO.HIGH)
    GPIO.setup(LED_PIN, GPIO.OUT, initial=GPIO.LOW)
    GPIO.setup(REED_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.add_event_detect(BUTTON_PIN, GPIO.BOTH, callback=onButtonActivity)

def isDoorOpen():
    return GPIO.input(REED_PIN) == GPIO.HIGH

def toggleDoor():
    GPIO.output(RELAY_PIN, GPIO.LOW)
    time.sleep(0.25)
    GPIO.output(RELAY_PIN, GPIO.HIGH)

def turnOnLed():
    GPIO.output(LED_PIN, GPIO.HIGH)

def turnOffLed():
    GPIO.output(LED_PIN, GPIO.LOW)

def isButtonPressed():
    return GPIO.input(BUTTON_PIN) == GPIO.LOW

# Called when an interrupt comes in for the button's state changing.
def onButtonActivity(channel):
    # We're called on a GPIO thread, so we first make sure to get back to
    # the main Tornado thread.
    gIoLoop.add_callback(onButtonActivityMainThread)

# Called on the main thread when the button state changes. This can be noisy
# when on button press or release, so avoid doing anything until the button
# state has settled.
def onButtonActivityMainThread():
    global gDebounceTimeout

    # Keep delaying action while the button is bouncing.
    if gDebounceTimeout is not None:
        gIoLoop.remove_timeout(gDebounceTimeout)
        gDebounceTimeout = None

    # Wait a bit before deciding on this.
    gDebounceTimeout = gIoLoop.add_timeout(time.time() + DEBOUNCE_S, debouncedButtonChange)

# This is a change in button state that's been debounced. Note that we're not
# completely guaranteed that the button state has changed since the last time
# this was called, since the button may have been both pressed and released
# in that time.
def debouncedButtonChange():
    global gPlayer, gPreviousButton

    # Look for a positive edge.
    newButton = isButtonPressed()
    if not gPreviousButton and newButton:
        if gPlayer:
            turnOffRadio()
        else:
            turnOnRadio()
    gPreviousButton = newButton

# -----------------------------------------------------------------------------------------------
# Database

def initDb(filename):
    global gDb

    gDb = sqlite3.connect(filename)
    c = gDb.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS event (
                     id INTEGER PRIMARY KEY AUTOINCREMENT,
                     message text NOT NULL,
                     created_at text NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    gDb.commit()
    c.close()

def addEvent(message):
    global gDb

    logging.info("%s", message)

    c = gDb.cursor()
    c.execute("""INSERT INTO event (message) VALUES (?)""", (message,))
    gDb.commit()
    c.close()

def getRecentEvents(count):
    global gDb

    c = gDb.cursor()
    c.execute("""SELECT message, created_at
                 FROM event
                 ORDER BY id DESC
                 LIMIT ?""", (count,))
    events = list(c)
    c.close()

    return events

# -----------------------------------------------------------------------------------------------
# Twilio

def sendText(phoneNumber, message):
    # Allow a list of numbers.
    if isinstance(phoneNumber, list):
        for number in phoneNumber:
            sendText(number, message)
        return

    addEvent("Send SMS to %s: %s" % (phoneNumber, message))

    if not SEND_TEXT_ENABLED:
        return

    url = "https://api.twilio.com/2010-04-01/Accounts/%s/SMS/Messages.json" % TWILIO_SID
    data = {
        "From": TWILIO_SOURCE_PHONE_NUMBER,
        "To": phoneNumber,
        "Body": message,
    }
    headers = {
        "Authorization": "Basic " + base64.b64encode(TWILIO_SID + ":" + TWILIO_TOKEN),
    }
    request = urllib2.Request(url, urllib.urlencode(data), headers)
    try:
        f = urllib2.urlopen(request)
        d = f.read()
        f.close()
    except urllib2.HTTPError as e:
        addEvent("Can't send Twilio text (%s)" % (e,))
        logging.exception("Can't send Twilio text (%s)" % (e,))

# -----------------------------------------------------------------------------------------------
# Tasks

def checkDoor():
    global gDoorIsOpen, gLastDoorChangeTime, gWarned

    now = time.time()

    isOpen = isDoorOpen()
    if isOpen != gDoorIsOpen:
        gDoorIsOpen = isOpen
        gLastDoorChangeTime = now
        if not isOpen and gWarned:
            sendText(ALL_PHONE_NUMBERS, "The garage door has closed.")
        gWarned = False
        addEvent("Door is now %s" % ("open" if gDoorIsOpen else "closed"))

    timeSinceChange = now - gLastDoorChangeTime
    if gDoorIsOpen and not gWarned and timeSinceChange >= WARN_TIME_S:
        timeSinceChangeString = secondsToString(timeSinceChange)
        addEvent("Door open too long (%s), sending alert" % timeSinceChangeString)
        sendText(ALL_PHONE_NUMBERS, "The garage door has been open %s." % timeSinceChangeString)
        gWarned = True

    scheduleTimeout()

def scheduleTimeout():
    gIoLoop.add_timeout(time.time() + CHECK_PERIOD_S, checkDoor)

# -----------------------------------------------------------------------------------------------
# Radio

def turnOnRadio():
    global gPlayer

    # Make sure it's off first.
    turnOffRadio()

    logging.info("Starting player")
    turnOnLed()

    # sudo apt-get install mplayer
    args = [
        "/usr/bin/mplayer",
        "-msglevel", "all=4",
        "-noconsolecontrols",
        "-nojoystick",
        "-nolirc",
        "-nomouseinput",
        RADIO_URL]
    gPlayer = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)

    # Listen for stdout and stderr.
    gIoLoop.add_handler(gPlayer.stdout.fileno(), handlePlayerOut, gIoLoop.READ)
    gIoLoop.add_handler(gPlayer.stderr.fileno(), handlePlayerOut, gIoLoop.READ)

def turnOffRadio():
    global gPlayer, gSongName, gSongUrl

    if gPlayer:
        logging.info("Stopping player")
        gPlayer.terminate()
        gPlayer.wait()
        gIoLoop.remove_handler(gPlayer.stdout)
        gIoLoop.remove_handler(gPlayer.stderr)
        gPlayer = None
        gSongName = None
        gSongUrl = None

    turnOffLed()

# Handle output from player.
def handlePlayerOut(fd, events):
    global gPlayer, gSongName, gSongUrl

    if gPlayer and events & gIoLoop.READ:
        if fd == gPlayer.stdout.fileno():
            line = gPlayer.stdout.readline()
        elif fd == gPlayer.stderr.fileno():
            line = gPlayer.stderr.readline()
        else:
            return
        songName, songUrl = extractSongInfo(line)
        if songName:
            gSongName = songName
            gSongUrl = songUrl
            logging.info("Song: %s", gSongName)
    elif events & gIoLoop.ERROR:
        logging.info("Error reading from player, stopping playback")
        turnOffRadio()

SONG_INFO_PATTERN = re.compile(r"^ICY Info: StreamTitle='(.*)';StreamUrl='(.*)';$")
def extractSongInfo(line):
    # ICY Info: StreamTitle='Tori Amos - Glory of the 80's';StreamUrl='http://www.radioparadise.com/graphics/covers/m/B00001IVJS.jpg';
    result = SONG_INFO_PATTERN.match(line.strip())
    if result:
        return result.group(1), result.group(2)
    else:
        return None, None

# -----------------------------------------------------------------------------------------------
# Web

class MainHandler(tornado.web.RequestHandler):
    def get(self):
        howLong = time.time() - gLastDoorChangeTime
        howLongString = secondsToString(howLong)
        recentEvents = getRecentEvents(10)
        self.render("index.html",
                isOpen=gDoorIsOpen,
                howLong=howLong,
                howLongString=howLongString,
                recentEvents=recentEvents,
                songName=gSongName,
                songUrl=gSongUrl)

def controlAuth(username, password):
    return username == AUTH_USERNAME and password == AUTH_PASSWORD

class ControlHandler(tornado.web.RequestHandler):
    @authenticated(controlAuth)
    def get(self, username):
        howLong = time.time() - gLastDoorChangeTime
        howLongString = secondsToString(howLong)
        self.render("control.html",
                isOpen=gDoorIsOpen,
                howLong=howLong,
                howLongString=howLongString)

class ToggleHandler(tornado.web.RequestHandler):
    @authenticated(controlAuth)
    def post(self, username):
        addEvent("Toggling door (by " + username + ")")
        sendText(ADMIN_PHONE_NUMBER, "Door toggled by " + username + ".")
        toggleDoor()
        # We use a different URL for control and toggle so that refreshing won't
        # toggle again. This is a Chrome bug (21245).
        self.redirect("/control", status=303)

# -----------------------------------------------------------------------------------------------
# Main

def main():
    global gIoLoop
    gIoLoop = tornado.ioloop.IOLoop.instance()

    tornado.options.define("db", default=":memory:",
            help="filename to use for database",
            type=str, metavar="FILENAME")
    tornado.options.define("port", default=8888,
            help="web server port",
            type=int, metavar="PORT")
    tornado.options.define("git", default=None,
            help="git hash",
            type=str, metavar="HASH")
    tornado.options.parse_command_line()
    if tornado.options.options.git:
        logging.info("Git hash is %s", tornado.options.options.git)
    initGpio()
    initDb(tornado.options.options.db)
    application = tornado.web.Application([
        (r"/", MainHandler),
        (r"/control", ControlHandler),
        (r"/control/toggle", ToggleHandler),
    ], template_path="templates", static_path="static")
    application.listen(tornado.options.options.port)
    addEvent("Starting server on port %d" % tornado.options.options.port)
    checkDoor()
    gIoLoop.start()

if __name__ == "__main__":
    main()
