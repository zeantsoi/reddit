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

from r2.models import Link
from r2.lib.utils import Storage
#from r2.lib.utils.trial_utils import *

class Trial(Storage):
    def __init__(self, defendant):
        if not on_trial(defendant):
            raise ValueError ("Defendant %s is not on trial" % defendant._id)
        self.defendant = defendant

    def convict(self):
#        train_spam_filter(self.defendant, "spam")
        if self.defendant._spam:
            pass #TODO: PM submitter
        else:
            pass #TODO: ban it

    def acquit(self):
#        train_spam_filter(self.defendant, "ham")
        if self.defendant._spam:
            pass
#            self.defendant._date = datetime.now(g.tz)
#            self.defendant._spam = False
            #TODO: PM submitter

    def mistrial(self):
        #TODO: PM mods
        if self.defendant._spam:
            pass #TODO: PM submitter

    def verdict(self):
        from r2.models import Jury

        ups = 0
        downs = 0
        nones = 0

        now = datetime.now(g.tz)
        defendant_age = now - self.defendant._date
        if defendant_age.days > 0:
            return "timeout"

        latest_juryvote = None
        for j in Jury.by_defendant(self.defendant):
            if j._name == "0":
                nones += 1
                continue

            # For non-zero votes, update latest_juryvote
            if latest_juryvote is None:
                latest_juryvote = j._date
            else:
                latest_juryvote = max(latest_juryvote, j._date)

            if j._name == "1":
                ups += 1
            elif j._name == "-1":
                downs += 1
            else:
                raise ValueError("weird jury vote: [%s]" % j._name)

        print "%d ups, %d downs, %d haven't voted yet" % (ups, downs, nones)

        if ups + downs < 5:
            g.log.debug("not enough voters yet")
            return None

        # If a trial is less than an hour old, and votes are still trickling in
        # (i.e., there was one in the past five minutes), it's not yet time to
        # declare a verdict.
        if defendant_age.seconds < 3600 and (now - latest_juryvote).seconds < 300:
            g.log.debug("votes still trickling in")
            return None

        up_pct = ups / float(ups + downs)

        if up_pct < 0.33:
            return "guilty"
        elif up_pct > 0.67:
            return "innocent"
        else:
            g.log.debug("hung jury, so far")
            return None # no decision yet; wait for more voters

    def check_verdict(self):
        verdict = self.verdict()
        if verdict is None:
            return # no verdict yet

        if verdict == "guilty":
            self.convict()
        elif verdict == "innocent":
            self.acquit()
        elif verdict == "timeout":
            self.mistrial()
        else:
            raise ValueError("Invalid verdict [%s]" % verdict)

#        self.defendant.verdict = verdict
#        self.defendant._commit()
#        g.hardcache.delete(self.defendant._trial_key())
#        all_defendants(_update=True)

        return verdict
