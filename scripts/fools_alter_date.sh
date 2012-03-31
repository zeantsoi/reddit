#!/bin/bash

if [ $# -ne 3 ]; then
  echo "usage: $0 INIPATH FULLNAME DAY"
  exit 1
fi

paster run "$1" -c "from r2.models import *; apply_timereddit_day_override('$2', '$3')"

