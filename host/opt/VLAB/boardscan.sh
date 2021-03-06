#!/bin/bash

# Check the currently identified boards in /dev/vlab and if any of them
# do not have their associated boardserver container running then create it.

DIR=/dev/vlab

if [ -d "$DIR" ]; then
	for f in $DIR/*
	do
		serial=`basename $f`
		running=`docker inspect -f {{.State.Running}} cnt-$serial`

		if [ "$running" != "true" ] ; then
			/opt/VLAB/boardevent.sh attach $serial
		fi
	done
fi
