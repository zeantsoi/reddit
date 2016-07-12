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

"""Store sitemaps in s3.

This module is uploads all subreddit sitemaps as well as the sitemap index
to s3. The basic idea is that amazon will be serving the static sitemaps for
us.

The binary data we send to s3 is a gzipped xml file. In addition we also
send the appropriate type and encoding headers so this is understood
correctly by the browser.

We store sitemaps for two classes of pages: subreddits and comment pages.
We store both the sitemaps for those pages as well as 2 sitemap indices.
One for each class of sitemap.

The directory structure we create on s3 should look something like this:

/subreddit-sitemaps.xml
/comment-page-sitemaps.xml
/subreddit_sitemap/0.xml
/subreddit_sitemap/1.xml
/comment_page_sitemap/2016-05-23/0.xml
/comment_page_sitemap/2016-05-23/1.xml
/comment_page_sitemap/2016-05-24/0.xml
/comment_page_sitemap/2016-05-24/1.xml
/comment_page_sitemap/2016-05-24/2.xml

For subreddit sitemaps we get every single subreddit so we just dump them
into a single /subreddit_sitemap directory.

For comment page sitemaps, we get a daily update of links created that day.
We dump all the sitemaps for that day in a day specific directory.
"""

import gzip
from StringIO import StringIO

from boto.s3.connection import S3Connection
from boto.s3.key import Key
from pylons import app_globals as g

from r2.lib.sitemaps.generate import (
    generate_subreddit_sitemaps,
    generate_comment_page_sitemaps,
    generate_sitemap_index,
)


# We upload zipped sitemaps.
HEADERS = {
    'Content-Type': 'text/xml',
    'Content-Encoding': 'gzip',
}


def _zip_string(string):
    zipbuffer = StringIO()
    with gzip.GzipFile(mode='w', fileobj=zipbuffer) as f:
        f.write(string)
    return zipbuffer.getvalue()


def _upload_sitemap(key, sitemap):
    g.log.debug("Uploading %r", key)

    key.set_contents_from_string(_zip_string(sitemap), headers=HEADERS)


def _upload_subreddit_sitemap(bucket, index, sitemap):
    key = Key(bucket)
    key.key = 'subreddit_sitemap/{0}.xml'.format(index)

    _upload_sitemap(key, sitemap)


def _upload_comment_page_sitemap(bucket, index, dt_key, sitemap):
    key = Key(bucket)
    key.key = 'comment_page_sitemap/{0}/{1}.xml'.format(
        # S3 didn't like entity encoded key names, so we'll handle
        # the values that we'll see from the data team.
        dt_key.replace('=', '-'),
        index
    )

    _upload_sitemap(key, sitemap)


def _update_sitemap_index(path, prefix, bucket):
    key = Key(bucket)
    key.key = path

    _upload_sitemap(key, generate_sitemap_index(bucket.list(prefix)))


def generate_and_upload_subreddit_sitemaps(subreddits):
    s3conn = S3Connection()
    bucket = s3conn.get_bucket(g.sitemap_upload_s3_bucket, validate=False)

    for i, sitemap in enumerate(generate_subreddit_sitemaps(subreddits)):
        _upload_subreddit_sitemap(bucket, i, sitemap)

    _update_sitemap_index(
        'subreddit-sitemaps.xml', 'subreddit_sitemap', bucket)


def generate_and_upload_comment_page_sitemaps(comment_page_data, dt_key):
    s3conn = S3Connection()
    bucket = s3conn.get_bucket(g.sitemap_upload_s3_bucket, validate=False)

    sitemaps = generate_comment_page_sitemaps(comment_page_data)
    for i, sitemap in enumerate(sitemaps):
        _upload_comment_page_sitemap(bucket, i, dt_key, sitemap)

    _update_sitemap_index(
        'comment-page-sitemaps.xml', 'comment_page_sitemap', bucket)
