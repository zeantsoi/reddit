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

import re
import json
from pylons import tmpl_context as c
from pylons import app_globals as g

from r2.lib import amqp, hooks
from r2.models.link import Link

alphanum_split = re.compile(r"[^a-zA-Z0-9]")
MAX_PHRASE_LENGTH = 4


def get_phrases(text, max_length=MAX_PHRASE_LENGTH):
    phrases = []
    words = re.split(alphanum_split, text)
    words = [word.strip() for word in words if word != '']

    # Generate phrases from length 1 to MAX_PHRASE_LENGTH
    for i in range(0, max_length):
        phrase_iter = range(0, i + 1)
        phrases += [
            " ".join([words[h + j] for j in phrase_iter])
            for h in range(len(words) - i)
        ]
    return phrases

def extract_keywords(link):
    if link._spam or link._deleted:
        return

    # This logic is very simple for now. In the future it can be extended
    # to support stemming, word senses, variations, sentiment, etc.
    kwset = set()
    for keyword in kwl:
        if keyword.startswith("k."):
            kwset.add(keyword[2:])
        elif keyword.startswith("!k."):
            kwset.add(keyword[3:])

    # Split words in the title
    matches = set()
    phrases = get_phrases(link.title.lower())

    for word in phrases:
        if word in kwset:
            matches.add(word)
            # Limit to ten keywords
            if len(matches)>10: break

    if matches:
        # Save to the link
        link.keyword_targets = ','.join(matches)
        link._commit()

def run():
    # Add watch to only update kwl when the keyword list changes
    @g.zookeeper.DataWatch("/keyword-targets")
    def watch_keywords(data, stats):
        global kwl
        kwl = json.loads(data)
        
    @g.stats.amqp_processor("keyword_target_q")
    def process_message(msg):
        fname = msg.body
        link = Link._by_fullname(fname, data=True)
        extract_keywords(link)

    amqp.consume_items("keyword_target_q",
                       process_message,
                       verbose=True)
