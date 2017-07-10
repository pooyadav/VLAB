#!/usr/bin/env python3

'''
The VLAB relay shell. Called from bash when a remote user connects, this script 
is given one argument, which is the board class that the user is requesting.

The script checks whether this user is allowed that board, and if so, locks the 
board and assembles the required ssh command to be executed by the calling shell
script which will forward the user's ssh connection on the target board server.

Ian Gray, 2016
'''

import os, sys, getpass, time, logging
import redis
from vlabredis import *

KEYS_DIR = "/vlab/keys/"

logging.basicConfig(filename='/vlab/log/access.log', level=logging.INFO, format='%(asctime)s ; %(levelname)s ; %(name)s ; %(message)s')
log = logging.getLogger(os.path.basename(sys.argv[0]))

db = connecttoredis('localhost')

if len(sys.argv) < 3:
	print("Usage: {} {{requested board class}}".format(sys.argv[0]))
	sys.exit(1)

username = getpass.getuser()
arg = sys.argv[2]


# Is the user requesting a free ephemeral port?
if arg == 'getport':
	port = db.incr("vlab:port")
	if port > 35000:
		port = 30000
		db.set("vlab:port", 30000)
	print("VLABPORT:{}".format(port))
	sys.exit(0)

# Otherwise the arg should be of the form boardclass:port
pos = arg.find(':')
if pos == -1:
	print("Argument should be of the form boardclass:port")
	sys.exit(1)


boardclass = arg[:pos]
tunnelport = arg[(pos + 1):]
try:
	tunnelport = int(tunnelport)
except:
	print("Argument should be of the form boardclass:port")
	sys.exit(1)


# Do the specified user and boardclass exist in redis?
checkInSet(db, 'vlab:boardclasses', boardclass, "Board class {} does not exist.".format(boardclass))
checkInSet(db, 'vlab:users', username, "User {} is not a VLAB user.".format(username))

# Can the user access the requested boardclass?
# Either they are an overlord user, or vlab:user:<username>:allowedboards includes the boardclass in question
if not db.get("vlab:user:{}:overlord".format(username)):
	checkInSet(db, "vlab:user:{}:allowedboards".format(username), 
		boardclass,
		"User {} cannot access board class {}.".format(username, boardclass)
		)


# Do we already own it?
# For each board in the board class, check if one is locked by us
board = None
for b in db.smembers("vlab:boardclass:{}:boards".format(boardclass)):
	if db.get("vlab:board:{}:lock:username".format(b)) == username:
		board = b
		break 

if board == None:
	# Try to grab a lock for the boardclass
	db.set("vlab:boardclass:{}:locking".format(boardclass), 1)
	db.expire("vlab:boardclass:{}:locking".format(boardclass), 2)

	board = db.spop("vlab:boardclass:{}:unlockedboards".format(boardclass))
	if board == None:
		db.delete("vlab:boardclass:{}:locking".format(boardclass))
		print("All boards of type {} are currently in use.".format(boardclass))
		log.critical("NOFREEBOARDS: {}, {}".format(username, boardclass))
		sys.exit(1)

	db.set("vlab:board:{}:lock:username".format(board), username)
	db.set("vlab:board:{}:lock:time".format(board), int(time.time()))
else:
	#Refresh the lock time
	db.set("vlab:board:{}:lock:time".format(board), int(time.time()))


unlockedcount = db.scard("vlab:boardclass:{}:unlockedboards".format(boardclass))
log.info("LOCK: {}, {}, {} remaining in set".format(username, boardclass, unlockedcount))

# Fetch the details of the locked board
boarddetails = getBoardDetails(db, board, ["user", "server", "port"])

# All done. First restart the target container
target = "vlab@{}".format(boarddetails['server'])
keyfile = "{}{}".format(KEYS_DIR, "id_rsa")
cmd = "docker kill cnt-{}".format(board)
sshcmd = "ssh -o \"StrictHostKeyChecking no\" -e none -i {} {} \"{}\"".format(keyfile, target, cmd) 
print("Restarting target container...")
os.system(sshcmd)

cmd = "/opt/VLAB/boardscan.sh"
sshcmd = "ssh -o \"StrictHostKeyChecking no\" -e none -i {} {} \"{}\"".format(keyfile, target, cmd) 
os.system(sshcmd)

print("Restarted.")


# Execute the bounce command
print("SSH to board server...")
time.sleep(1)

# Port details might have changed
boarddetails = getBoardDetails(db, board, ["user", "server", "port"])
tunnel = "-L {}:localhost:3121".format(tunnelport)
keyfile = "{}{}".format(KEYS_DIR, "id_rsa")
target = "root@{}".format(boarddetails['server'])
screenrc = "defhstatus \\\"{} (VLAB)\\\"\\ncaption always\\ncaption string \\\"VLAB shell connected to {} on {}\\\"".format(boardclass, boardclass, boarddetails['server'])
cmd = "echo -e '{}' > /vlab/vlabscreenrc; screen -c /vlab/vlabscreenrc -qdRR - /dev/ttyFPGA 115200; killall -q screen".format(screenrc)
sshcmd = "ssh {} -o \"StrictHostKeyChecking no\" -e none -i {} -p {} -tt {} \"{}\"".format(tunnel, keyfile, boarddetails['port'], target, cmd)
rv = os.system(sshcmd)

print("User disconnected. Resetting board")
log.info("RELEASE: {}, {}".format(username, boardclass))

if db.get("vlab:knownboard:{}:reset".format(board)) == "true":
	cmd = "/opt/xsct/bin/xsdb /vlab/reset.tcl"
	sshcmd = "ssh -o \"StrictHostKeyChecking no\" -i {} -p {} {} \"{}\"".format(keyfile, boarddetails['port'], target, cmd)
	print("Resetting board.")
	os.system(sshcmd)

print("Releasing lock.")
unlockBoard(db, board, boardclass)


