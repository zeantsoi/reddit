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

from pylons import c, g, request
from r2.models import Thing, Account
from r2.lib.utils import ip_and_slash16
from r2.lib.memoize import memoize
from r2.lib.log import log_text

@memoize('trial_utils.all_defendants')
def all_defendants_cache():
    fnames = g.hardcache.backend.ids_by_category("trial")
    return fnames

def all_defendants(_update=False):
    all = all_defendants_cache(_update=_update)
    return Thing._by_fullname(all, data=True).values()

def trial_key(thing):
    return "trial-" + thing._fullname

def on_trial(thing):
    return g.hardcache.get(trial_key(thing))

def indict(defendant):
    tk = trial_key(defendant)

    if defendant._deleted:
        result = "already deleted"
    elif hasattr(defendant, "promoted") and defendant.promoted:
        result = "it's promoted"
    elif hasattr(defendant, "verdict") and defendant.verdict is not None:
        result = "it already has a verdict"
    elif g.hardcache.get(tk):
        result = "it's already on trial"
    else:
        # The regular hardcache reaper should never run on one of these,
        # since a mistrial should be declared if the trial is still open
        # after 24 hours. So the "3 days" expiration isn't really real.
        g.hardcache.set(tk, True, 3 * 86400)
        all_defendants(_update=True)
        result = "it's now indicted: %s" % tk

    log_text("indict_result", "%r: %s" % (defendant, result), level="info")

def assign_trial(account):
    from r2.models import Jury, Subreddit

    defendants_voted_upon = []
    defendants_assigned_to = []

    for jury in Jury.by_account(account):
        defendants_assigned_to.append(jury._thing2_id)
        if jury._name != '0':
            defendants_voted_upon.append(jury._thing2_id)

    all_defs = all_defendants()
    all_defs.sort(key=lambda x: x._date)
    #TODO: sorting should de-prioritize quorum juries and ones
    #      that have already been seen

    sr_ids = [ d.sr_id for d in all_defs ]
    srs = Subreddit._byID(sr_ids)
    cs = {}
    for sr_id, sr in srs.iteritems():
        cs[sr_id] = sr.can_submit(account) and not sr._spam

    for defendant in all_defs:
        if defendant._deleted:
            g.log.debug("%s is deleted" % defendant)
        elif defendant._id in defendants_voted_upon:
            g.log.debug("%s is already on the jury for %s" %
                        (account, defendant))
        elif not cs[defendant.sr_id]:
            g.log.debug("%s can't submit on /r/%s, where %s is" %
                        (account,
                         Subreddit._byID(defendant.sr_id).name,
                         defendant))
        elif not Jury.voir_dire(account, defendant):
            g.log.debug("%s failed voir dire for %s" %
                        (account, defendant))
        else:
            if defendant._id not in defendants_assigned_to:
                j = Jury._new(account, defendant)

            return defendant

    return None

def populate_spotlight():
    if not (c.user_is_loggedin and c.user.jury_betatester()):
        g.log.debug("not eligible")
        return None

    ip, slash16 = ip_and_slash16(request)

    anyone_key = "recent-juror-anyone"
    user_key = "recent-juror-user-" + c.user.name
    ip_key   = "recent-juror-ip-" + ip
    s16_key  = "recent-juror-slash16-" + slash16

    if (g.cache.get(anyone_key) or g.cache.get(user_key) or
        g.cache.get(ip_key)     or g.cache.get(s16_key)):
        g.log.debug("recent juror")
        return None

    trial = assign_trial(c.user)

    if trial is None:
        g.log.debug("nothing available")
        return None

    # Only stick a trial in the spotlight box once every 15 mins for a
    # given user or IP, and only once every five minutes for his /16.
    # Only show it to *anyone*, site-wide, once every five seconds.
    g.cache.set(user_key, True, 15 * 60)
    g.cache.set(ip_key,   True, 15 * 60)
    g.cache.set(s16_key,  True,  5 * 60)
    g.cache.set(anyone_key, True,     5)

    return trial

def look_for_verdicts():
    from r2.models import Trial

    print "checking all trials for verdicts..."
    for defendant in all_defendants():
        print "Looking at %r" % defendant
        v = Trial(defendant).check_verdict()
        print "Verdict: %r" % v
