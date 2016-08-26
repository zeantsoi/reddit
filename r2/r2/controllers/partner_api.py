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
from pylons import app_globals as g
from pylons import tmpl_context as c

from r2.config.extensions import RSS_TYPES
from r2.controllers.reddit_base import RedditController
from r2.lib import all_sr
from r2.lib.base import abort
from r2.lib.pages import MinimalRss
from r2.lib.pages.things import wrap_links


class PartnerApiController(RedditController):
    """
    Controller for partner-related APIs.

    Identifying and authenticating partners happens in HAProxy, and partner
    specific feature flags are enabled on a based on pools.
    """

    def GET_trending(self):
        """
        Return a list of trending items.
        """
        if not g.partner_api_enable_rss:
            abort(403)

        if not c.extension or c.extension.lower() not in RSS_TYPES:
            abort(400, 'Only supports RSS and XML.')

        # TODO(wting#CHAN-158|2016-08-26): The number 5000 was chosen based on
        # emperical testing to increase link diversity timing out.
        num_of_links = 5000

        listing = wrap_links(all_sr.get_all_hot_ids(), num=num_of_links)
        return MinimalRss(_content=listing).render(style='xmllite')
