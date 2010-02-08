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

def run(limit=100, verbose=False):
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
            exc_str = "%s: %s" % (exc_type, exc_desc)

            occ = "<%s:%s, pid=%s, %s>" % (d['host'], d['port'], d['pid'], d['time'])

            tb = []

            key_material = "exc_type"
            pretty_lines = []

            for tpl in d['traceback']:
                tb.append(tpl)
                filename, lineno, funcname, text = tpl
                key_material += "%s %s " % (filename, funcname)
                pretty_lines.append ("%s:%s: %s()" % (filename, lineno, funcname))
                pretty_lines.append ("    %s" % text)

            fingerprint = md5(key_material).hexdigest()

            nickname_key = "error_nickname-" + fingerprint

            nickname = g.hardcache.get(nickname_key)

            if nickname is None:
                nickname = '"%s" Error' % randword().capitalize()
                print "A new kind of thing just happened! ",
                print "I'm going to call it a " + nickname
                print ""
                print "Where and when: %s" % occ
                print ""
                print "Traceback:"
                print "\n".join(pretty_lines)
                print exc_str
                print "\n\n\n"
                g.hardcache.set(nickname_key, nickname, 86400 * 365)

            err_key = "-".join(["error", daystring, fingerprint])

            existing = g.hardcache.get(err_key)

            if not existing:
                existing = dict(exception=exc_str, traceback=tb, occurrences=[])

            existing['occurrences'].append(occ)

            g.hardcache.set(err_key, existing, 7 * 86400)

            if verbose:
                print "%s %s" % (nickname, occ)


    amqp.handle_items(q, myfunc, limit=limit, drain=True, verbose=verbose)
