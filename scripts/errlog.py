#! /usr/bin/python

from r2.lib import amqp
from pylons import g
from datetime import datetime
from md5 import md5
from random import shuffle, choice

import pickle

try:
  words = file(g.words_file).read().split("\n")
except IOError:
  words = []

shuffle(words)

def randword():
    try:
      return choice(words)
    except IndexError:
      return '???'

rk = q = 'error_q'

def run(limit=100):
    daystring = datetime.now(g.tz).strftime("%Y/%m/%d")

    def myfunc(msgs, chan):
        for msg in msgs:
            try:
                d = pickle.loads(msg.body)
            except TypeError:
                print "wtf is %r" % msg.body

            exc = d['exception']
            exc_desc = str(exc)
            exc_type = exc.__class__.__name__

            tb = []

            key_material = "exc_type"

            for tpl in d['traceback']:
                tb.append(tpl)
                filename, lineno, funcname, text = tpl
                key_material += "%s %s " % (filename, funcname)

            fingerprint = md5(key_material).hexdigest()

            nickname_key = "error_nickname-" + fingerprint

            nickname = g.hardcache.get(nickname_key)

            if nickname is None:
                nickname = '"%s" Error' % randword().capitalize()
                g.hardcache.set(nickname_key, nickname, 86400 * 365)

            err_key = "-".join(["error", daystring, fingerprint])

            existing = g.hardcache.get(err_key)

            if not existing:
                exc_str = "%s: %s" % (exc_type, exc_desc)
                existing = dict(exception=exc_str, traceback=tb, occurrences=[])

            occ = "<%s:%s, pid=%s, %s>" % (d['host'], d['port'], d['pid'], d['time'])

            existing['occurrences'].append(occ)

            g.hardcache.set(err_key, existing, 7 * 86400)

            print "%s %s" % (nickname, occ)

    amqp.handle_items(q, myfunc, limit=limit, drain=True)
