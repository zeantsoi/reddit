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
# All portions of the code written by reddit are Copyright (c) 2006-2014 reddit
# Inc. All Rights Reserved.
###############################################################################
from pylons import c, g

from r2.controllers.api_docs import api_doc, api_section
from r2.controllers.oauth2 import require_oauth2_scope
from r2.controllers.reddit_base import (
    abort_with_error,
    OAuth2ResourceController,
)
from r2.controllers.ipn import send_gift
from r2.lib.errors import RedditError
from r2.lib.validator import (
    validate,
    VAccountByName,
    VByName,
    VInt,
)
from r2.models import Comment, Link
from r2.models.gold import creddits_lock


class APIv1GoldController(OAuth2ResourceController):
    def pre(self):
        OAuth2ResourceController.pre(self)
        self.authenticate_with_token()
        self.run_sitewide_ratelimits()

    def try_pagecache(self):
        pass

    @staticmethod
    def on_validation_error(error):
        abort_with_error(error, error.code or 400)

    def _gift_using_creddits(self, recipient, months=1, thing_fullname=None):
        with creddits_lock(c.user):
            if not c.user.employee and c.user.gold_creddits < months:
                err = RedditError("INSUFFICIENT_CREDDITS")
                self.on_validation_error(err)

            send_gift(
                buyer=c.user,
                recipient=recipient,
                months=months,
                days=months * 31,
                signed=False,
                giftmessage=None,
                thing_fullname=thing_fullname,
            )

            if not c.user.employee:
                c.user.gold_creddits -= months
                c.user._commit()

    @require_oauth2_scope("creddits")
    @validate(
        target=VByName("fullname"),
    )
    @api_doc(
        api_section.gold,
        uri="/api/v1/gold/gild/{fullname}",
    )
    def POST_gild(self, target):
        if not isinstance(target, (Comment, Link)):
            err = RedditError("NO_THING_ID")
            self.on_validation_error(err)

        self._gift_using_creddits(
            recipient=target.author_slow,
            thing_fullname=target._fullname,
        )

    @require_oauth2_scope("creddits")
    @validate(
        user=VAccountByName("username"),
        months=VInt("months", min=1, max=36),
    )
    @api_doc(
        api_section.gold,
        uri="/api/v1/gold/give/{username}",
    )
    def POST_give(self, user, months):
        self._gift_using_creddits(
            recipient=user,
            months=months,
        )
