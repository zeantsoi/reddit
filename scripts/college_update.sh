#!/bin/bash

DIR=/home/bsimpson/
LOG=$DIR/college.log
cd $DIR/reddit-public/r2
echo "Updating college subscriptions at `date`" >> $LOG
/usr/local/bin/paster run run.ini $DIR/reddit-public/r2/r2/models/college.py -c "update()" >> $LOG 2>&1
echo "Update finished at `date`" >> $LOG
