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
# The Original Code is reddit.
#
# The Original Developer is the Initial Developer.  The Initial Developer of
# the Original Code is reddit Inc.
#
# All portions of the code written by reddit are Copyright (c) 2006-2016 reddit
# Inc. All Rights Reserved.
###############################################################################

from collections import Counter

from pylons import app_globals as g

from r2.lib.db.operators import not_

CACHE_KEY = "ALL_HOT"


def get_all_query(sort, time):
    """ Return a Query for r/all links sorted by anything other than Hot, which
    has special treatment."""
    from r2.models import Link
    from r2.lib.db import queries

    q = Link._query(
        sort=queries.db_sort(sort),
        read_cache=True,
        write_cache=True,
        cache_time=60,
        data=True,
        filter_primary_sort_only=True,
    )

    if time != 'all':
        q._filter(queries.db_times[time])

    return q


def get_all_hot_ids():
    """ Return a list of Link fullnames sorted by Hot and reshuffled for
    diversity."""
    # this is populated by write_all_hot_cache below from a separate job
    link_ids = g.cache.get(CACHE_KEY, [], stale=True)
    return link_ids


def write_all_hot_cache():
    from r2.models.link import Link
    from r2.lib.db import queries

    q = Link._query(
        sort=queries.db_sort('hot'),
        limit=1000
    )

    top_links = resort_links(list(q))
    link_ids = [link._fullname for link in top_links]

    g.cache.set(CACHE_KEY, link_ids)

    return link_ids


def resort_links(top_links):
    """ Reshuffle links based on the number of appearances of each community.
    Each time a post from a community appears, the hotness of the next post
    will be lowered slightly. target_penalty is the approximate number of
    places to push a following post down the list. """

    sr_counts = Counter()
    new_hotness = {}

    target_penalty = g.live_config['r_all_penalty']

    # just in case. a target_penalty of 0 will disable it.
    if target_penalty > len(top_links):
        target_penalty = 0

    # target_penalty of 0 means we're not going to do any work
    if target_penalty == 0:
        return top_links

    # take the hotness between the first post, called base, and a post
    # target_penalty places later, called target
    base = top_links[0]._hot
    target = top_links[target_penalty]._hot

    for link in top_links:
        count = sr_counts[link.sr_id]
        sr_counts[link.sr_id] += 1

        # m: the algebra that led to the final line
        # m: pf = (target / base) / (target / base - 1)
        # m: pf = -target / (target - base)

        # m: penalty = pf / (count + pf)
        # m: = -target / (target - base) / (count - target / (target - base))
        # m: = -target / ((target - base) * (count - target / (target - base)))
        # m: = target / (target - (target - base) * count)
        # m: penalty = target / (target - (target - base) * count)
        penalty = target / (target - (target - base) * count)

        # apply the penalty
        new_hotness[link._id] = link._hot * penalty

    new_links = sorted(top_links,
                       key=lambda link: new_hotness[link._id],
                       reverse=True)
    return list(new_links)
