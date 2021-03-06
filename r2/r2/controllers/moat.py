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
from pylons import request

from r2.controllers.reddit_base import MinimalController
from r2.lib.pages import (
    MoatProxy,
)


class MoatController(MinimalController):
    def pre(self):
        if request.host != g.media_domain:
            # don't serve up untrusted content except on our
            # specifically untrusted domain
            self.abort404()

        super(MoatController, self).pre()

        c.allow_framing = True

    def GET_proxy(self):
        moat_script_url = g.live_config.get("moat_script_url", None)

        # No point in loading this page if it's not
        # configured properly.
        if moat_script_url is None:
            self.abort404()

        return MoatProxy(moat_script_url=moat_script_url).render()
