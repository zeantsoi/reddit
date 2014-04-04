"""
Code for recording engagement events in cassandra stats cluster.

Write frequency can be controlled by setting sample rates in memcached,
which can be done from reddit-shell on staging without a push.

"""
from datetime import datetime

import random

from pycassa.columnfamily import ColumnFamily
from pylons import g, request


STATS_POOL = g.cassandra_pools['stats']
CF = ColumnFamily(STATS_POOL, 'Engagement')
CACHE_SAMPLE_PREFIX = 'event_sample.'
KEYSEP = '|'

# engagement actions
COMMENT = 'c'
COMMENT_VOTE = 'cv'
LINK_VOTE = 'lv'
SUBMIT = 's'
VALID_ACTIONS = set([COMMENT, COMMENT_VOTE, LINK_VOTE, SUBMIT])


def record_engagement(user, action, thing_id, sr_id=None):
    """Records user interaction in cassandra."""
    if random.random() > get_sample_rate(action):
        return
    now = datetime.utcnow()
    timekey = now.strftime('%Y%m%d%H%M')
    # note that ua and ip need to be deleted within 90 days
    cols = {
        'act': action,
        'id36': thing_id,
        'sr': sr_id if sr_id else '',
        'gold': 't' if user.gold else 'f',
        'ua': request.user_agent if request.user_agent else '',
        'ip': request.ip if hasattr(request, 'ip') else '',
    }
    # unique rowkey that can be sorted by time
    rowkey = KEYSEP.join([timekey, user._id36, action, thing_id])
    CF.insert(rowkey, cols)


def get_sample_rate(action):
    """Fetch sample rate from live_config."""
    if action not in VALID_ACTIONS:
        g.log.error('invalid event log action: %s' % action)
        return 0
    live_config_key = {
        COMMENT: 'sample_rate_comment',
        COMMENT_VOTE: 'sample_rate_comment_vote',
        LINK_VOTE: 'sample_rate_link_vote',
        SUBMIT: 'sample_rate_submit',
    }.get(action)
    return g.live_config.get(live_config_key, 0)
