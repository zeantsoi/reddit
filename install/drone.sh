#!/usr/bin/env bash
###############################################################################
# reddit Drone environment installer
# ----------------------------------
# This script re-purposes some of our existing vagrant/Travis install and
# setup scripts for our Drone CI builds.
#
# NOTE: You don't want to run this script directly in your development
# environment, since we assume that it's running within this Docker image
# that Drone runs our builds within: https://github.com/reddit/docker-reddit-py
#
# docker-reddit-py has most of the apt dependencies pre-installed in order to
# significantly reduce our build times.
#
# Refer to .drone.yml in the repo root to see where this script gets called
# during a build.
###############################################################################

###############################################################################
# Install prerequisites
###############################################################################

# Under normal operation, this won't install anything new. We're re-using the
# logic that checks to make sure all services have finished starting before
# continuing.
install/install_services.sh

###############################################################################
# Install and configure the reddit code
###############################################################################

pushd r2
python setup.py develop
make pyx

# Let plugins patch in any configuration they need by adding a test.update file
# in their root directory.
cp -f example.ini test.ini
for update in ../../*/test.update ; do
  if [[ -r $update ]] ; then
    echo "Adding $update to test.ini"
    tmp=$(mktemp test_update.ini.XXXXXX)
    ./updateini.py test.ini $update > $tmp && mv $tmp test.ini
  fi
done

popd

###############################################################################
# Configure local services
###############################################################################

# Creates the column families required for the tests
install/setup_cassandra.sh
