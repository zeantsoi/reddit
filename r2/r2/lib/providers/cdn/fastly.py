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

import requests
from pylons import app_globals as g

from r2.lib.providers.cdn import CdnProvider


class FastlyCdnProvider(CdnProvider):
    """A provider for reddit's configuration of Fastly."""

    def _do_content_purge(self, url):  
        """Does the purge of the content from Fastly."""
        response = requests.request('PURGE', url)

    def purge_content(self, url):
        """Purges the content specified by url from the cache.

        https://docs.fastly.com/api/purge#purge
        The full URL of the file that needs to be purged from 
        Fastly's cache.
        """
        if 'https://' in url:
            url_altered = url.replace('https://', 'http://')
        else:
            url_altered = url.replace('http://', 'https://')

        with g.stats.get_timer('providers.fastly.content_purge'):
            self._do_content_purge(url)
            self._do_content_purge(url_altered)