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

"""Utilities for working with paths with embedded dates."""

from datetime import date, timedelta
import re

from pylons import app_globals as g

from r2.lib.s3_helpers import to_s3_path

# how many days back is still considered "recent"
RECENCY_COUNT = 3


def _date_from_dt_key(dt_key):
    year, month, day = re.match(r'dt=(\d{4})-(\d{2})-(\d{2})', dt_key).groups()
    return date(int(year), int(month), int(day))


def _recent_dates(date):
    dates = []
    for i in xrange(RECENCY_COUNT):
        dates.append(date - timedelta(days=(i + 1)))
    return dates


def dt_key_is_recent(dt_key):
    dt_date = _date_from_dt_key(dt_key)
    return (date.today() - dt_date).days <= 3


def recent_sitemap_s3paths(dt_key):
    recent_dates = _recent_dates(_date_from_dt_key(dt_key))
    s3paths = []
    for date in recent_dates:
        key = 'comment_page_sitemap/dt-{0}/'.format(date.strftime('%Y-%m-%d'))
        s3paths.append(to_s3_path(g.sitemap_upload_s3_bucket, key))
    return s3paths
