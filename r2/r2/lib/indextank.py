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
"""
    Module for communication reddit-level communication with IndexTank
"""

from __future__ import with_statement

from pylons import g, config

from r2.models import *
from r2.lib.cache import SelfEmptyingCache
from r2.lib import amqp
from r2.lib.solrsearch import indexed_types

def run_changed(drain=False):
    """
        Run by `cron` (through `paster run`) on a schedule to send Things to
        IndexTank
    """
    def _run_changed(msgs, chan):
        print "changed: Processing %d items" % len(msgs)

        num_to_process = g.cache.get("indextank-allowance")
        if not num_to_process:
            print "discarding %d msgs" % len(msgs)
            return
        if num_to_process < 0:
            print "Okay, who put %d in indextank-allowance?" % num_to_process
            g.cache.delete("indextank-allowance")
            return

        fullnames = set([x.body for x in msgs])
        things = Thing._by_fullname(fullnames, data=True, return_dict=False)
        things = [x for x in things if isinstance(x, indexed_types)]

        update_things = [x for x in things if not x._spam and not x._deleted]
        delete_things = [x for x in things if x._spam or x._deleted]

        num_updates = len(update_things)
        num_deletes = len(delete_things)

        update_things = update_things[:num_to_process]

        num_processed = len(update_things)
        num_to_process -= len(update_things)

        delete_things = delete_things[:num_to_process]

        num_processed += len(delete_things)
        num_to_process -= len(delete_things)

        g.cache.set("indextank-allowance", num_to_process)

        num_discarded_updates = num_updates - len(update_things)
        num_discarded_deletes = num_deletes - len(delete_things)

        if update_things:
            print "Here is where we would add %r" % update_things
        if delete_things:
            for i in delete_things:
                print "Here is where we would delete %r" % i._fullname

        if num_discarded_updates:
            print "discarding %d updates" % num_discarded_updates

        if num_discarded_deletes:
            print "discarding %d deletes" % num_discarded_deletes

    amqp.handle_items('indextank_changes', _run_changed, limit=1000,
                      drain=drain)
