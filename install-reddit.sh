#!/bin/bash -e
# The contents of this file are subject to the Common Public Attribution
# License Version 1.0. (the "License"); you may not use this file except in
# compliance with the License. You may obtain a copy of the License at
# http://code.reddit.com/LICENSE. The License is based on the Mozilla Public
# License Version 1.1, but Sections 14 and 15 have been added to cover use of
# software over a computer network and provide for limited attribution for the
# Original Developer. In addition, Exhibit A has been modified to be consistent
# with Exhibit B.
#
# Software distributed under the License is distributed on an "AS IS" basis,
# WITHOUT WARRANTY OF ANY KIND, either express or implied. See the License for
# the specific language governing rights and limitations under the License.
#
# The Original Code is reddit.
#
# The Original Developer is the Initial Developer.  The Initial Developer of
# the Original Code is reddit Inc.
#
# All portions of the code written by reddit are Copyright (c) 2006-2013 reddit
# Inc. All Rights Reserved.
###############################################################################

###############################################################################
# reddit dev environment installer
# --------------------------------
# This script installs a reddit stack suitable for development. DO NOT run this
# on a system that you use for other purposes as it might delete important
# files, truncate your databases, and otherwise do mean things to you.
#
# By default, this script will install the reddit code in the current user's
# home directory and all of its dependencies (including libraries and database
# servers) at the system level. The installed reddit will expect to be visited
# on the domain "reddit.local" unless specified otherwise.  Configuring name
# resolution for the domain is expected to be done outside the installed
# environment (e.g. in your host machine's /etc/hosts file) and is not
# something this script handles.
#
# Several configuration options (listed in the "Configuration" section below)
# are overridable with environment variables. e.g.
#
#    sudo REDDIT_DOMAIN=example.com ./install-reddit.sh
#
###############################################################################
set -e

###############################################################################
# Configuration
###############################################################################
# which user to install the code for; defaults to the user invoking this script
REDDIT_USER=${REDDIT_USER:-$SUDO_USER}

# the group to run reddit code as; must exist already
REDDIT_GROUP=${REDDIT_GROUP:-nogroup}

# the root directory to base the install in. must exist already
REDDIT_HOME=${REDDIT_HOME:-/home/$REDDIT_USER}

# the domain that you will connect to your reddit install with.
# MUST contain a . in it somewhere as browsers won't do cookies for dotless
# domains. an IP address will suffice if nothing else is available.
REDDIT_DOMAIN=${REDDIT_DOMAIN:-reddit.local}

###############################################################################
# Sanity Checks
###############################################################################
if [[ $EUID -ne 0 ]]; then
    echo "ERROR: Must be run with root privileges."
    exit 1
fi

# seriously! these checks are here for a reason. the packages from the
# reddit ppa aren't built for anything but precise (12.04) right now, so
# if you try and use this install script on another release you're gonna
# have a bad time.
source /etc/lsb-release
if [ "$DISTRIB_ID" != "Ubuntu" -o "$DISTRIB_RELEASE" != "12.04" ]; then
    echo "ERROR: Only Ubuntu 12.04 is supported."
    exit 1
fi

###############################################################################
# Install prerequisites
###############################################################################
set -x

# aptitude configuration
APTITUDE_OPTIONS="-y"
export DEBIAN_FRONTEND=noninteractive

# run an aptitude update to make sure python-software-properties
# dependencies are found
apt-get update

# add the reddit ppa for some custom packages
apt-get install $APTITUDE_OPTIONS python-software-properties
apt-add-repository -y ppa:reddit/ppa

# pin the ppa -- packages present in the ppa will take precedence over
# ones in other repositories (unless further pinning is done)
cat <<HERE > /etc/apt/preferences.d/reddit
Package: *
Pin: release o=LP-PPA-reddit
Pin-Priority: 600
HERE

# grab the new ppas' package listings
apt-get update

# install prerequisites
cat <<PACKAGES | xargs apt-get install $APTITUDE_OPTIONS
netcat-openbsd
git-core

python-dev
python-setuptools
python-routes
python-pylons
python-boto
python-tz
python-crypto
python-babel
cython
python-sqlalchemy
python-beautifulsoup
python-cssutils
python-chardet
python-psycopg2
python-pycassa
python-imaging
python-pycaptcha
python-amqplib
python-pylibmc
python-bcrypt
python-snudown
python-l2cs
python-lxml
python-zope.interface
python-kazoo
python-stripe

nodejs
node-less
gettext
make
optipng
jpegoptim

memcached
postgresql
postgresql-client
rabbitmq-server
cassandra
haproxy
nginx
stunnel
gunicorn
sutro
PACKAGES

# paper over stack size issues with cassandra
sed -i s/-Xss128k/-Xss228k/ /etc/cassandra/cassandra-env.sh

###############################################################################
# Wait for all the services to be up
###############################################################################
# cassandra doesn't auto-start after install
service cassandra start

# check each port for connectivity
echo "Waiting for services to be available, see source for port meanings..."
# 11211 - memcache
# 5432 - postgres
# 5672 - rabbitmq
# 9160 - cassandra
for port in 11211 5432 5672 9160; do
    while ! nc -vz localhost $port; do
        sleep 1
    done
done

###############################################################################
# Install the reddit source repositories
###############################################################################
if [ ! -d $REDDIT_HOME/src ]; then
    mkdir -p $REDDIT_HOME/src
    chown $REDDIT_USER $REDDIT_HOME/src
fi

if [ ! -d $REDDIT_HOME/src/reddit ]; then
    sudo -u $REDDIT_USER git clone https://github.com/reddit/reddit.git src/reddit
fi

if [ ! -d $REDDIT_HOME/src/i18n ]; then
    sudo -u $REDDIT_USER git clone https://github.com/reddit/reddit-i18n.git src/i18n
fi

###############################################################################
# Configure Cassandra
###############################################################################
if ! echo | cassandra-cli -h localhost -k reddit &> /dev/null; then
    echo "create keyspace reddit;" | cassandra-cli -h localhost -B
fi

cat <<CASS | cassandra-cli -B -h localhost -k reddit || true
create column family permacache with column_type = 'Standard' and
                                     comparator = 'BytesType';
CASS

###############################################################################
# Configure PostgreSQL
###############################################################################
SQL="SELECT COUNT(1) FROM pg_catalog.pg_database WHERE datname = 'reddit';"
IS_DATABASE_CREATED=$(sudo -u postgres psql -t -c "$SQL")

if [ $IS_DATABASE_CREATED -ne 1 ]; then
    cat <<PGSCRIPT | sudo -u postgres psql
CREATE DATABASE reddit WITH ENCODING = 'utf8' TEMPLATE template0;
CREATE USER reddit WITH PASSWORD 'password';
PGSCRIPT
fi

sudo -u postgres psql reddit < $REDDIT_HOME/src/reddit/sql/functions.sql

###############################################################################
# Configure RabbitMQ
###############################################################################
if ! rabbitmqctl list_vhosts | egrep "^/$"
then
    rabbitmqctl add_vhost /
fi

if ! rabbitmqctl list_users | egrep "^reddit"
then
    rabbitmqctl add_user reddit reddit
fi

rabbitmqctl set_permissions -p / reddit ".*" ".*" ".*"

###############################################################################
# Install and configure the reddit code
###############################################################################
cd $REDDIT_HOME/src/reddit/r2
sudo -u $REDDIT_USER make pyx # generate the .c files from .pyx
sudo -u $REDDIT_USER python setup.py build
python setup.py develop --no-deps

cd $REDDIT_HOME/src/i18n/
sudo -u $REDDIT_USER python setup.py build
python setup.py develop --no-deps
sudo -u $REDDIT_USER make

# this builds static files and should be run *after* languages are installed
# so that the proper language-specific static files can be generated.
cd $REDDIT_HOME/src/reddit/r2
sudo -u $REDDIT_USER make

cd $REDDIT_HOME/src/reddit/r2

if [ ! -f development.update ]; then
    cat > development.update <<DEVELOPMENT
# after editing this file, run "make ini" to
# generate a new development.ini

[DEFAULT]
debug = true

disable_ads = true
disable_captcha = true
disable_ratelimit = true
disable_require_admin_otp = true

page_cache_time = 0

domain = $REDDIT_DOMAIN

media_provider = filesystem
media_fs_root = /srv/www/media
media_fs_base_url_http = http://%(domain)s/media/
media_fs_base_url_https = https://%(domain)s/media/

[server:main]
port = 8001
DEVELOPMENT
    chown $REDDIT_USER development.update
fi

sudo -u $REDDIT_USER make ini

if [ ! -L run.ini ]; then
    sudo -u $REDDIT_USER ln -s development.ini run.ini
fi

###############################################################################
# some useful helper scripts
###############################################################################
cat > /usr/local/bin/reddit-run <<REDDITRUN
#!/bin/bash
exec paster --plugin=r2 run $REDDIT_HOME/src/reddit/r2/run.ini "\$@"
REDDITRUN

cat > /usr/local/bin/reddit-shell <<REDDITSHELL
#!/bin/bash
exec paster --plugin=r2 shell $REDDIT_HOME/src/reddit/r2/run.ini
REDDITSHELL

chmod 755 /usr/local/bin/reddit-run /usr/local/bin/reddit-shell

###############################################################################
# nginx
###############################################################################

mkdir -p /srv/www/media
chown $REDDIT_USER:$REDDIT_GROUP /srv/www/media

cat > /etc/nginx/sites-available/reddit-media <<MEDIA
server {
    listen 9000;

    expires max;

    location /media/ {
        alias /srv/www/media/;
    }
}
MEDIA

# remove the default nginx site that may conflict with haproxy
rm /etc/nginx/sites-enabled/default
# put our config in place
ln -s /etc/nginx/sites-available/reddit-media /etc/nginx/sites-enabled/

service nginx restart

###############################################################################
# haproxy
###############################################################################
if [ -e /etc/haproxy/haproxy.cfg ]; then
    BACKUP_HAPROXY=$(mktemp /etc/haproxy/haproxy.cfg.XXX)
    echo "Backing up /etc/haproxy/haproxy.cfg to $BACKUP_HAPROXY"
    cat /etc/haproxy/haproxy.cfg > $BACKUP_HAPROXY
fi

# make sure haproxy is enabled
cat > /etc/default/haproxy <<DEFAULT
ENABLED=1
DEFAULT

# configure haproxy
cat > /etc/haproxy/haproxy.cfg <<HAPROXY
global
    maxconn 350

frontend frontend
    mode http

    bind 0.0.0.0:80
    bind 127.0.0.1:8080

    timeout client 24h
    option forwardfor except 127.0.0.1
    option httpclose

    # make sure that requests have x-forwarded-proto: https iff tls
    reqidel ^X-Forwarded-Proto:.*
    acl is-ssl dst_port 8080
    reqadd X-Forwarded-Proto:\ https if is-ssl

    # send websockets to sutro
    acl is-websocket hdr(Upgrade) -i WebSocket
    use_backend sutro if is-websocket

    # send media stuff to the local nginx
    acl is-media path_beg /media/
    use_backend media if is-media

    default_backend reddit

backend reddit
    mode http
    timeout connect 4000
    timeout server 30000
    timeout queue 60000
    balance roundrobin

    server app01-8001 localhost:8001 maxconn 1

backend sutro
    mode http
    timeout connect 4s
    timeout server 24h
    balance roundrobin

    server sutro localhost:8002 maxconn 250

backend media
    mode http
    timeout connect 4000
    timeout server 30000
    timeout queue 60000
    balance roundrobin

    server nginx localhost:9000 maxconn 20
HAPROXY

# this will start it even if currently stopped
service haproxy restart

###############################################################################
# stunnel
###############################################################################
cat > /etc/stunnel/stunnel.conf <<STUNNELCONF
foreground = no

; replace these with real certificates
cert = /etc/ssl/certs/ssl-cert-snakeoil.pem
key = /etc/ssl/private/ssl-cert-snakeoil.key

; protocol version and ciphers
sslVersion = all
ciphers = ECDHE-RSA-RC4-SHA:ECDHE-ECDSA-RC4-SHA:ECDH-RSA-RC4-SHA:ECDH-ECDSA-RC4-SHA:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-SHA384:ECDHE-ECDSA-AES256-SHA384:ECDHE-RSA-AES256-SHA:ECDHE-ECDSA-AES256-SHA:SRP-DSS-AES-256-CBC-SHA:SRP-RSA-AES-256-CBC-SHA:DHE-DSS-AES256-GCM-SHA384:DHE-RSA-AES256-GCM-SHA384:DHE-RSA-AES256-SHA256:DHE-DSS-AES256-SHA256:DHE-RSA-AES256-SHA:DHE-DSS-AES256-SHA:DHE-RSA-CAMELLIA256-SHA:DHE-DSS-CAMELLIA256-SHA:ECDH-RSA-AES256-GCM-SHA384:ECDH-ECDSA-AES256-GCM-SHA384:ECDH-RSA-AES256-SHA384:ECDH-ECDSA-AES256-SHA384:ECDH-RSA-AES256-SHA:ECDH-ECDSA-AES256-SHA:AES256-GCM-SHA384:AES256-SHA256:AES256-SHA:CAMELLIA256-SHA:PSK-AES256-CBC-SHA:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-SHA256:ECDHE-ECDSA-AES128-SHA256:ECDHE-RSA-AES128-SHA:ECDHE-ECDSA-AES128-SHA:SRP-DSS-AES-128-CBC-SHA:SRP-RSA-AES-128-CBC-SHA:DHE-DSS-AES128-GCM-SHA256:DHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES128-SHA256:DHE-DSS-AES128-SHA256:DHE-RSA-AES128-SHA:DHE-DSS-AES128-SHA:DHE-RSA-SEED-SHA:DHE-DSS-SEED-SHA:DHE-RSA-CAMELLIA128-SHA:DHE-DSS-CAMELLIA128-SHA:ECDH-RSA-AES128-GCM-SHA256:ECDH-ECDSA-AES128-GCM-SHA256:ECDH-RSA-AES128-SHA256:ECDH-ECDSA-AES128-SHA256:ECDH-RSA-AES128-SHA:ECDH-ECDSA-AES128-SHA:AES128-GCM-SHA256:AES128-SHA256:AES128-SHA:SEED-SHA:CAMELLIA128-SHA:PSK-AES128-CBC-SHA:RC4-SHA:DES-CBC3-SHA:RC4-MD5
options = NO_SSLv2
options = DONT_INSERT_EMPTY_FRAGMENTS
options = CIPHER_SERVER_PREFERENCE

; security
chroot = /var/lib/stunnel4/
setuid = stunnel4
setgid = stunnel4
pid = /stunnel4.pid

; performance
socket = l:TCP_NODELAY=1
socket = r:TCP_NODELAY=1

; logging
output = /var/log/stunnel4/stunnel.log
syslog = no

[https]
accept = 443
connect = 8080
TIMEOUTclose = 0
sslVersion = all
; this requires a patched version of stunnel which is in the reddit ppa
xforwardedfor = yes
STUNNELCONF

sed -i s/ENABLED=0/ENABLED=1/ /etc/default/stunnel4

service stunnel4 restart

###############################################################################
# sutro (websocket server)
###############################################################################

if [ ! -f /etc/sutro.ini ]; then
    cat > /etc/sutro.ini <<SUTRO
[app:main]
paste.app_factory = sutro.app:make_app

amqp.host = localhost
amqp.port = 5672
amqp.vhost = /
amqp.username = reddit
amqp.password = reddit

web.allowed_origins = $REDDIT_DOMAIN
web.mac_secret = YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXowMTIzNDU2Nzg5
web.ping_interval = 300

stats.host =
stats.port = 0

[server:main]
use = egg:gunicorn#main
worker_class = sutro.socketserver.SutroWorker
workers = 1
worker_connections = 250
host = 127.0.0.1
port = 8002
graceful_timeout = 5
forward_allow_ips = 127.0.0.1

[loggers]
keys = root

[handlers]
keys = syslog

[formatters]
keys = generic

[logger_root]
level = INFO
handlers = syslog

[handler_syslog]
class = handlers.SysLogHandler
args = ("/dev/log", "local7")
formatter = generic
level = NOTSET

[formatter_generic]
format = [%(name)s] %(message)s
SUTRO
fi

if [ ! -f /etc/init/sutro.conf ]; then
    cat > /etc/init/sutro.conf << UPSTART_SUTRO
description "sutro websocket server"

stop on runlevel [!2345]
start on runlevel [2345]

respawn
respawn limit 10 5
kill timeout 15

limit nofile 65535 65535

exec gunicorn_paster /etc/sutro.ini
UPSTART_SUTRO
fi

start sutro

###############################################################################
# Upstart Environment
###############################################################################
CONSUMER_CONFIG_ROOT=$REDDIT_HOME/consumer-count.d
cp $REDDIT_HOME/src/reddit/upstart/* /etc/init/

if [ ! -f /etc/default/reddit ]; then
    cat > /etc/default/reddit <<DEFAULT
export REDDIT_ROOT=$REDDIT_HOME/src/reddit/r2
export REDDIT_INI=$REDDIT_HOME/src/reddit/r2/run.ini
export REDDIT_USER=$REDDIT_USER
export REDDIT_GROUP=$REDDIT_GROUP
export REDDIT_CONSUMER_CONFIG=$CONSUMER_CONFIG_ROOT
alias wrap-job=$REDDIT_HOME/src/reddit/scripts/wrap-job
alias manage-consumers=$REDDIT_HOME/src/reddit/scripts/manage-consumers
DEFAULT
fi

###############################################################################
# Queue Processors
###############################################################################
mkdir -p $CONSUMER_CONFIG_ROOT

function set_consumer_count {
    if [ ! -f $CONSUMER_CONFIG_ROOT/$1 ]; then
        echo $2 > $CONSUMER_CONFIG_ROOT/$1
    fi
}

set_consumer_count log_q 0
set_consumer_count cloudsearch_q 0
set_consumer_count scraper_q 1
set_consumer_count commentstree_q 1
set_consumer_count newcomments_q 1
set_consumer_count vote_link_q 1
set_consumer_count vote_comment_q 1

chown -R $REDDIT_USER:$REDDIT_GROUP $CONSUMER_CONFIG_ROOT/

initctl emit reddit-start

###############################################################################
# Cron Jobs
###############################################################################
if [ ! -f /etc/cron.d/reddit ]; then
    cat > /etc/cron.d/reddit <<CRON
0    3 * * * root /sbin/start --quiet reddit-job-update_sr_names
30  16 * * * root /sbin/start --quiet reddit-job-update_reddits
0    * * * * root /sbin/start --quiet reddit-job-update_promos
*/5  * * * * root /sbin/start --quiet reddit-job-clean_up_hardcache
*/2  * * * * root /sbin/start --quiet reddit-job-broken_things
*/2  * * * * root /sbin/start --quiet reddit-job-rising
0    * * * * root /sbin/start --quiet reddit-job-trylater

# jobs that recalculate time-limited listings (e.g. top this year)
PGPASSWORD=password
*/15 * * * * $REDDIT_USER $REDDIT_HOME/src/reddit/scripts/compute_time_listings link year '("hour", "day", "week", "month", "year")'
*/15 * * * * $REDDIT_USER $REDDIT_HOME/src/reddit/scripts/compute_time_listings comment year '("hour", "day", "week", "month", "year")'

# disabled by default, uncomment if you need these jobs
#*    * * * * root /sbin/start --quiet reddit-job-email
#0    0 * * * root /sbin/start --quiet reddit-job-update_gold_users
CRON
fi

###############################################################################
# All done!
###############################################################################
cd $REDDIT_HOME

cat <<CONCLUSION

Congratulations! reddit is now installed.

The reddit application code is managed with upstart, to see what's currently
running, run

    sudo initctl list | grep reddit

Cron jobs start with "reddit-job-" and queue processors start with
"reddit-consumer-". The crons are managed by /etc/cron.d/reddit. You can
initiate a restart of all the consumers by running:

    sudo initctl emit reddit-restart

or target specific ones:

    sudo initctl emit reddit-restart TARGET=scraper_q

See the GitHub wiki for more information on these jobs:

* https://github.com/reddit/reddit/wiki/Cron-jobs
* https://github.com/reddit/reddit/wiki/Services

Now that the core of reddit is installed, you may want to do some additional
steps:

* Ensure that $REDDIT_DOMAIN resolves to this machine.

* To populate the database with test data, run:

    cd $REDDIT_HOME/src/reddit/r2
    reddit-run r2/models/populatedb.py -c 'populate()'

* Manually run reddit-job-update_reddits immediately after populating the db
  or adding your own subreddits.
CONCLUSION
