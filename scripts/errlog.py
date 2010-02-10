#! /usr/bin/python

from r2.lib import amqp, emailer
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

def run(limit=100, streamfile=None, verbose=False):
    if streamfile:
        stream_fp = open(streamfile, "a")
    else:
        stream_fp = None

    def log(msg, important=False):
        if stream_fp:
            stream_fp.write(msg + "\n")
            stream_fp.flush()
        if important:
            print msg

    def myfunc(msgs, chan):
        daystring = datetime.now(g.display_tz).strftime("%Y/%m/%d")

        for msg in msgs:
            try:
                d = pickle.loads(msg.body)
            except TypeError:
                log ("wtf is %r" % msg.body, True)

            exc = d['exception']
            exc_desc = str(exc)
            exc_type = exc.__class__.__name__
            exc_str = "%s: %s" % (exc_type, exc_desc)

            occ = "<%s:%s, pid=%-5s, %s>" % (
                  d['host'], d['port'], d['pid'], d['time'])

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
                news = ("A new kind of thing just happened! " +
                        "I'm going to call it a %s\n\n" % nickname)

                news += "Where and when: %s\n\n" % occ
                news += "Traceback:\n"
                news += "\n".join(pretty_lines)
                news += exc_str
                news += "\n"

                emailer.nerds_email(news, "Exception Watcher")

                g.hardcache.set(nickname_key, nickname, 86400 * 365)
                g.hardcache.set("error_status-" + fingerprint, "new", 86400)

            err_key = "-".join(["error", daystring, fingerprint])

            existing = g.hardcache.get(err_key)

            if not existing:
                existing = dict(exception=exc_str, traceback=tb, occurrences=[])

            existing['occurrences'].append(occ)

            g.hardcache.set(err_key, existing, 7 * 86400)

            log ("%s %s" % (occ, nickname), verbose)


    amqp.handle_items(q, myfunc, limit=limit, drain=False, verbose=verbose)
