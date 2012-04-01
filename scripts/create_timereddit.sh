#!/bin/bash

if [ $# -lt 5 ]; then
  echo "usage: $0 INIPATH NAME TITLE DATE CREATOR [MODS...]"
  exit 1
fi

ini=$1; shift
name=$1; shift
title=$1; shift
date=$1; shift
creator=$1; shift
mods=$*;

paster run "$ini" -c "from r2.models import *; create_timereddit('$name', '$title', '$date', '$creator', '$mods')"

