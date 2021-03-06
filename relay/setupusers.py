#!/usr/bin/env python3

"""
Reads a list of users from CONFIGFILE and populates the redis database with them.
Also checks that each named user has an associated system user account with appropriate shell.
"""

import logging
import os
import shutil
import subprocess
import sys
import time
import redis
import vlabconfig

CONFIG_FILE = '/vlab/vlab.conf'

logging.basicConfig(
	filename='/vlab/log/relay.log',	level=logging.INFO,	format='%(asctime)s ; %(levelname)s ; %(name)s ; %(message)s')
log = logging.getLogger(os.path.basename(sys.argv[0]))

log.info("Begin relay server start up.")

# Open the config file and parse it
config = vlabconfig.open_log(log, CONFIG_FILE)
log.info("{} parsed successfully.".format(CONFIG_FILE))
users = config['users']

# As we are started at the same time as the redis server it may time some time for it to become available
connection_attempts = 1
while True:
	try:
		db = redis.StrictRedis(host='localhost', port=6379, db=0, decode_responses=True)
		db.ping()
		break
	except redis.exceptions.ConnectionError as c:
		log.info("Connection to redis server failed. Retrying...({}/5)".format(connection_attempts))
		time.sleep(2)
	connection_attempts = connection_attempts + 1
	if connection_attempts > 5:
		log.critical("Cannot connect to the redis server. Aborting.")
		sys.exit(6)

log.info("Config file format accepted. Begin user generation.")

# We are now connected, add the user details to the dictionary and construct the users in the container
try:
	for user in users:
		db.sadd("vlab:users", user)
		if "overlord" in users[user]:
			db.set("vlab:user:{}:overlord".format(user), "true")
		if 'allowedboards' in users[user]:
			for bc in users[user]['allowedboards']:
				db.sadd("vlab:user:{}:allowedboards".format(user), bc)

		if os.path.isfile("/vlab/keys/{}.pub".format(user)):
			log.info("\tAdding user: {}".format(user))
			try:
				useradd_output = subprocess.check_output(
					["useradd", "-m", "--shell", "/vlab/shell.py", "{}".format(user)])
			except subprocess.CalledProcessError as e:
				log.critical("CalledProcessError calling useradd. Message: {}".format(e.output))
				sys.exit(52)
			else:
				log.info("\tuseradd complete.")
			log.info("\tAdding keys for user: {}".format(user))
			os.mkdir("/home/{}/.ssh".format(user))
			shutil.copyfile("/vlab/keys/{}.pub".format(user), "/home/{}/.ssh/authorized_keys".format(user))
			shutil.chown("/home/{}/.ssh/".format(user), user="{}".format(user), group="{}".format(user))
			shutil.chown("/home/{}/.ssh/authorized_keys".format(user), user="{}".format(user), group="{}".format(user))
			log.info("\tchmod 600 /home/{}/.ssh/authorized_keys".format(user))
			os.chmod("/home/{}/.ssh/authorized_keys".format(user), 0o600)
except Exception as e:
	log.critical("Error creating users. {}".format(e))
	sys.exit(90)

log.info("Users generated. Adding known boards to redis server.")

# Add the known boards to the dictionary
for board in config['boards'].keys():
	db.sadd("vlab:knownboards", board)
	db.set("vlab:knownboard:{}:class".format(board), config['boards'][board]['class'])
	db.set("vlab:knownboard:{}:type".format(board), config['boards'][board]['type'])
	if 'reset' in config['boards'][board]:
		db.set("vlab:knownboard:{}:reset".format(board), config['boards'][board]['reset'])

# And finally our free port number
db.set("vlab:port", 30000)

log.info("Relay server start up completed successfully.")
sys.exit(0)
