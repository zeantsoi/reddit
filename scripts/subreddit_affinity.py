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
# All portions of the code written by reddit are Copyright (c) 2006-2015 reddit
# Inc. All Rights Reserved.
###############################################################################

from r2.models import (
    Subreddit,
    SubredditAffinity,
)


# Example file structure (subreddit, related subreddit, similarity score):
#
# pics AskHistorians 0.53355056
# pics videos 0.3279929
# pics earthporn 0.60225644
# earthporn food 0.58814077
# earthporn askhistorians 0.2811133
# earthporn pics 0.2681125
# beta frontpage 0.24762452


def add_affinity_variant(variant, filename, debug=True):
    """Store related subreddits and similarity scores"""

    # Load file and split out affinity data
    with open(filename, 'rb') as f:
        sr_affinity_data = []
        for line in f:
            sr_affinity_data.append(line.strip().split('\x01'))

    # Group similar subreddits (and scores) under the original subreddit
    subreddit_similarity = {}
    for sr_name, similar_subreddit, similarity in sr_affinity_data:
        if subreddit_similarity.get(sr_name):
            subreddit_similarity[sr_name][similar_subreddit] = similarity
        else:
            similar_subreddit_dict = {similar_subreddit: similarity}
            subreddit_similarity[sr_name] = similar_subreddit_dict

    # Add subreddit and their similar subreddits/scores to SubredditAffinity
    for sr_name, similar_subreddits in subreddit_similarity.iteritems():
        try:
            subreddit = Subreddit._by_name(sr_name)
        except NotFound:
            print 'skipping: not found %s' % sr_name

        if debug:
            print "%s adding: %s" % (subreddit.name, similar_subreddits)
        else:
            SubredditAffinity.create(subreddit, variant, similar_subreddits)
