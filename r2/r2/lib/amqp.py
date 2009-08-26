from threading import local
from datetime import datetime
import time
import errno
import socket

from amqplib import client_0_8 as amqp

from r2.lib.cache import LocalCache
from pylons import g

amqp_host = g.amqp_host
amqp_user = g.amqp_user
amqp_pass = g.amqp_pass
amqp_virtual_host = g.amqp_virtual_host

connection = None
channel = local()
have_init = False

#there are two ways of interacting with this module: add_item and
#handle_items. add_item should only be called from the utils.worker
#thread since it might block for an arbitrary amount of time while
#trying to get a connection amqp.

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
            print 'error connecting to amqp'
            time.sleep(1)

    #don't run init_queue until someone actually needs it. this allows
    #the app server to start and serve most pages if amqp isn't
    #running
    if not have_init:
        init_queue()
        have_init = True

def get_channel(reconnect = False):
    global connection
    global channel

    if not connection or reconnect:
        channel.chan = None
        connection = None
        get_connection()

    if not getattr(channel, 'chan', None):
        channel.chan = connection.channel()
    return channel.chan

def init_queue():
    chan = get_channel()

    #we'll have one exchange for now
    chan.exchange_declare(exchange='reddit_exchange',
                          type='direct',
                          durable=True,
                          auto_delete=False)

    #prec_links queue
    chan.queue_declare(queue='prec_links',
                       durable=True,
                       exclusive=False,
                       auto_delete=False)

    chan.queue_bind(queue='prec_links',
                    exchange='reddit_exchange',
                    routing_key='prec_links')


def add_item(routing_key, body, message_id = None):
    """adds an item onto a queue. If the connection to amqp is lost it
    will try to reconnect and then call itself again."""
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

def handle_items(queue, callback, ack = True):
    """Call callback() on every item in a particular queue. If the
    connection to the queue is lost, it will die."""

    chan = get_channel()
    while True:
        #reset the local cache, this will likely be a very long-running process
        g.cache.caches = (LocalCache(),) + g.cache.caches[1:]

        msg = chan.basic_get(queue)
        if msg:
            callback(msg)
            if ack:
                chan.basic_ack(msg.delivery_tag)
        else:
            time.sleep(1)

