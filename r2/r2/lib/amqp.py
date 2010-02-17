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
# The Original Code is Reddit.
#
# The Original Developer is the Initial Developer.  The Initial Developer of the
# Original Code is CondeNet, Inc.
#
# All portions of the code written by CondeNet are Copyright (c) 2006-2010
# CondeNet, Inc. All Rights Reserved.
################################################################################

from Queue import Queue
from threading import local, Thread
from datetime import datetime
import os
import sys
import time
import errno
import socket
import itertools

from amqplib import client_0_8 as amqp

from pylons import g

amqp_host = g.amqp_host
amqp_user = g.amqp_user
amqp_pass = g.amqp_pass
log = g.log
amqp_virtual_host = g.amqp_virtual_host

connection = None
channel = local()
have_init = False

#there are two ways of interacting with this module: add_item and
#handle_items. _add_item (the internal function for adding items to
#amqp that are added using add_item) might block for an arbitrary
#amount of time while trying to get a connection amqp.

class Worker:
    def __init__(self):
        self.q = Queue()
        self.t = Thread(target=self._handle)
        self.t.setDaemon(True)
        self.t.start()

    def _handle(self):
        while True:
            fn = self.q.get()
            try:
                fn()
                self.q.task_done()
            except:
                import traceback
                print traceback.format_exc()

    def do(self, fn, *a, **kw):
        fn1 = lambda: fn(*a, **kw)
        self.q.put(fn1)

    def join(self):
        self.q.join()

worker = Worker()

def get_connection():
    global connection
    global have_init

    while not connection:
        try:
            connection = amqp.Connection(host = amqp_host,
                                         userid = amqp_user,
                                         password = amqp_pass,
                                         virtual_host = amqp_virtual_host,
                                         insist = False)
        except (socket.error, IOError):
            print 'error connecting to amqp %s @ %s' % (amqp_user, amqp_host)
            time.sleep(1)

    # don't run init_queue until someone actually needs it. this
    # allows the app server to start and serve most pages if amqp
    # isn't running
    if not have_init:
        init_queue()
        have_init = True

def get_channel(reconnect = False):
    global connection
    global channel

    # Periodic (and increasing with uptime) errors appearing when
    # connection object is still present, but appears to have been
    # closed.  This checks that the the connection is still open.
    if connection and connection.channels is None:
        log.error("Error: amqp.py, connection object with no available channels.  Reconnecting...")
        connection = None

    if not connection or reconnect:
        channel.chan = None
        connection = None
        get_connection()

    if not getattr(channel, 'chan', None):
        channel.chan = connection.channel()
    return channel.chan


def init_queue():
    from r2.lib.queues import RedditQueueMap

    exchange = 'reddit_exchange'

    chan = get_channel()

    RedditQueueMap(exchange, chan).init()


def _add_item(routing_key, body, message_id = None):
    """adds an item onto a queue. If the connection to amqp is lost it
    will try to reconnect and then call itself again."""
    if not amqp_host:
        log.error("Ignoring amqp message %r to %r" % (body, routing_key))
        return

    chan = get_channel()
    msg = amqp.Message(body,
                       timestamp = datetime.now(),
                       delivery_mode = 2)
    if message_id:
        msg.properties['message_id'] = message_id

    try:
        chan.basic_publish(msg,
                           exchange = 'reddit_exchange',
                           routing_key = routing_key)
    except Exception as e:
        if e.errno == errno.EPIPE:
            get_channel(True)
            add_item(routing_key, body, message_id)
        else:
            raise

def add_item(routing_key, body, message_id = None):
    if amqp_host:
        log.debug("amqp: adding item %r to %r" % (body, routing_key))

    worker.do(_add_item, routing_key, body, message_id = message_id)

def handle_items(queue, callback, ack = True, limit = 1, drain = False,
                 verbose=True):
    """Call callback() on every item in a particular queue. If the
       connection to the queue is lost, it will die. Intended to be
       used as a long-running process."""

    chan = get_channel()
    countdown = None

    while True:

        # NB: None != 0, so we don't need an "is not None" check here
        if countdown == 0:
            break

        msg = chan.basic_get(queue)
        if not msg and drain:
            return
        elif not msg:
            time.sleep(1)
            continue

        if countdown is None and drain and 'message_count' in msg.delivery_info:
            countdown = 1 + msg.delivery_info['message_count']

        g.reset_caches()

        items = []

        while msg and countdown != 0:
            items.append(msg)
            if countdown is not None:
                countdown -= 1
            if len(items) >= limit:
                break # the innermost loop only
            msg = chan.basic_get(queue)

        try:
            count_str = ''
            if 'message_count' in items[-1].delivery_info:
                # the count from the last message, if the count is
                # available
                count_str = '(%d remaining)' % items[-1].delivery_info['message_count']
            if verbose:
                print "%s: %d items %s" % (queue, len(items), count_str)
            callback(items, chan)

            if ack:
                for item in items:
                    chan.basic_ack(item.delivery_tag)

            # flush any log messages printed by the callback
            sys.stdout.flush()
        except:
            for item in items:
                # explicitly reject the items that we've not processed
                chan.basic_reject(item.delivery_tag, requeue = True)
            raise

def empty_queue(queue):
    """debug function to completely erase the contents of a queue"""
    chan = get_channel()
    chan.queue_purge(queue)
