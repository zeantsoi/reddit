#!/bin/bash

if [ $# -ne 5 ]; then
  echo "usage: $0 INIPATH NAME TITLE DATE CREATOR"
  exit 1
fi

paster run "$1" -c "from r2.models import *; create_timereddit('$2', '$3', '$4', '$5')"

