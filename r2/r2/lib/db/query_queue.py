import cPickle as pickle
from datetime import datetime

from r2.lib import amqp

from pylons import g

working_prefix = 'working_'
prefix = 'prec_link_'
TIMEOUT = 120

def add_query(cached_results):
    amqp.add_item('prec_links', pickle.dumps(cached_results, -1))

def run():
    def callback(msg):
        cr = pickle.loads(msg.body)
        iden = cr.query._iden()

        working_key = working_prefix + iden
        key = prefix + iden

        last_time = g.memcache.get(key)
        #check to see if we've computed this job since it was added to the queue
        if  last_time and last_time > msg.timestamp:
            print 'skipping, already computed ', key
            return

        #check if someone else is working on this
        elif not g.memcache.add(working_key, 1, TIMEOUT):
            print 'skipping, someone else is working', working_key
            return

        cr = pickle.loads(msg.body)

        print 'working: ', cr.query._rules
        cr.update()

        g.memcache.set(key, datetime.now())
        g.memcache.delete(working_key)

    amqp.handle_items('prec_links', callback)
