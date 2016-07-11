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


from contextlib import contextmanager
import datetime
import dateutil
import json
import pytz
import re
import time

from boto.s3.connection import S3Connection
from boto.sqs.connection import SQSConnection
from pylons import app_globals as g

from r2.lib.s3_helpers import parse_s3_path
from r2.lib.sitemaps import store
from r2.lib.sitemaps.data import find_all_subreddits, find_comment_page_data

"""Watch for SQS messages informing us to read, generate, and store sitemaps.

There is only function that should be used outside this module

watcher()

It is designed to be used in a daemon process.
"""

SUBREDDIT_SITEMAP_JOB_NAME = 'daily_sr_sitemap_reporting'
COMMENT_PAGE_SITEMAP_JOB_NAME = 'daily_sitemap_reporting'


def watcher():
    """Poll for new sitemap data and process it as necessary."""
    while True:
        _process_message()


def _subreddit_sitemap_key():
    conn = S3Connection()
    bucket = conn.get_bucket(g.sitemap_upload_s3_bucket, validate=False)
    return bucket.get_key(g.sitemap_subreddit_keyname)


def _datetime_from_timestamp(timestamp):
    return datetime.datetime.fromtimestamp(timestamp / 1000, pytz.utc)


def _before_last_sitemap(timestamp):
    sitemap_key = _subreddit_sitemap_key()
    if sitemap_key is None:
        return False

    sitemap_datetime = dateutil.parser.parse(sitemap_key.last_modified)
    compare_datetime = _datetime_from_timestamp(timestamp)
    return compare_datetime < sitemap_datetime


@contextmanager
def _recieve_sqs_message():
    sqs = SQSConnection()
    sqs_q = sqs.get_queue(g.sitemap_sqs_queue)

    messages = sqs.receive_message(sqs_q, number_messages=1)

    if not messages:
        yield
        return

    message, = messages
    js = json.loads(message.get_body())
    s3path = parse_s3_path(js['location'])

    g.log.info('Received import job %r', js)

    yield dict(s3path=s3path, **js)

    sqs_q.delete_message(message)


def _process_message():
    with _recieve_sqs_message() as message:
        if not message:
            return

        if message['job_name'] == SUBREDDIT_SITEMAP_JOB_NAME:
            _process_subreddit_sitemaps(**message)
        elif message['job_name'] == COMMENT_PAGE_SITEMAP_JOB_NAME:
            _process_comment_page_sitemaps(**message)
        else:
            raise ValueError(
                'Invalid job_name: {0}'.format(message['job_name']))


def _process_subreddit_sitemaps(s3path, timestamp, **kw):
    # There are some error cases that allow us to get messages
    # for sitemap creation that are now out of date.
    if timestamp is not None and _before_last_sitemap(timestamp):
        return

    subreddits = find_all_subreddits(s3path)
    store.generate_and_upload_subreddit_sitemaps(subreddits)


def _dt_key_from_s3path(s3path):
    """The dt key is the part of the key that describes the current date."""
    return re.match(r'^.*/([A-Za-z0-9_=-]+)$', s3path).group(1)


def _process_comment_page_sitemaps(s3path, **kw):
    comment_page_data = find_comment_page_data(s3path)
    dt_key = _dt_key_from_s3path(s3path.key)
    store.generate_and_upload_comment_page_sitemaps(comment_page_data, dt_key)


def _current_timestamp():
    return int(time.time() * 1000)


def _create_sqs_message(message):
    """A dev only function that drops a new message on the sqs queue."""
    sqs = SQSConnection()
    sqs_q = sqs.get_queue(g.sitemap_sqs_queue)

    # it returns None on failure
    assert sqs_q, "failed to connect to queue"

    message = sqs_q.new_message(body=json.dumps(message))
    sqs_q.write(message)


def _create_subreddit_test_message():
    message = {
        'job_name': SUBREDDIT_SITEMAP_JOB_NAME,
        'location': ('s3://reddit-data-analysis/big-data/r2/prod/' +
                     'daily_sr_sitemap_reporting/dt=2016-06-29'),
        'timestamp': _current_timestamp(),
    }
    _create_sqs_message(message)


def _create_comment_page_test_message():
    message = {
        'job_name': COMMENT_PAGE_SITEMAP_JOB_NAME,
        'location': ('s3://reddit-data-analysis/big-data/r2/prod/' +
                     'daily_sitemap_reporting/dt=2016-07-10'),
    }
    _create_sqs_message(message)


def _create_bad_test_message():
    # Make sure you manually purge the SQS queue after using this.
    message = {
        'job_name': 'some-terrible-job-name',
        'location': ('s3://reddit-data-analysis/big-data/r2/prod/' +
                     'daily_sitemap_reporting/dt=2016-06-29'),
    }
    _create_sqs_message(message)
