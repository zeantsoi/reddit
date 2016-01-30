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

import hashlib
import hmac
import time

from pylons import app_globals as g
from pylons import request

from r2.config import feature
from r2.controllers.reddit_base import RedditController
from r2.lib.base import abort
from r2.lib.csrf import csrf_exempt
from r2.lib.db import queries
from r2.lib.filters import markdown_souptest
from r2.lib.message_to_email import (
    parse_and_validate_reply_to_address,
    queue_blocked_muted_email,
)
from r2.lib.souptest import SoupError
from r2.lib.utils import constant_time_compare
from r2.models import (
    Account,
    Message,
    Subreddit,
)


MAX_TIMESTAMP_DEVIATION = 600
ZENDESK_PREFIX = "##- Please type your reply above this line -##"


def validate_mailgun_webhook(timestamp, token, signature):
    """Check whether this is a valid webhook sent by Mailgun.

    See https://documentation.mailgun.com/user_manual.html#securing-webhooks

    NOTE:
    A single Mailgun account is used for both outbound email (Mailgun HTTP API)
    and inbound email (Mailgun Routes + MailgunWebhookController). As a result
    the `mailgun_api_key` is used by both.

    """

    message = ''.join((timestamp, token))
    expected_mac = hmac.new(
        g.secrets['mailgun_api_key'], message, hashlib.sha256).hexdigest()
    if not constant_time_compare(expected_mac, signature):
        g.stats.simple_event("mailgun.incoming.bad_signature")
        return False

    if abs(int(timestamp) - time.time()) > MAX_TIMESTAMP_DEVIATION:
        g.stats.simple_event("mailgun.incoming.bad_timestamp")
        return False

    return True


class MailgunWebhookController(RedditController):
    """Handle POST requests from Mailgun generated by inbound emails."""

    @csrf_exempt
    def POST_zendeskreply(self):
        request_body = request.POST
        recipient = request_body["recipient"]
        sender_email = request_body["sender"]
        from_ = request_body["from"]
        subject = request_body["subject"]
        body_plain = request_body["body-plain"]
        stripped_text = request_body["stripped-text"]
        timestamp = request_body["timestamp"]
        token = request_body["token"]
        signature = request_body["signature"]
        email_id = request_body["Message-Id"]

        if not validate_mailgun_webhook(timestamp, token, signature):
            # per Mailgun docs send a 406 so the message won't be retried
            abort(406, "invalid signature")

        message_id36 = parse_and_validate_reply_to_address(recipient)

        if not message_id36:
            # per Mailgun docs send a 406 so the message won't be retried
            abort(406, "invalid message")

        parent = Message._byID36(message_id36, data=True)
        to = Account._byID(parent.author_id, data=True)
        sr = Subreddit._byID(parent.sr_id, data=True)

        if stripped_text.startswith(ZENDESK_PREFIX):
            stripped_text = stripped_text[len(ZENDESK_PREFIX):].lstrip()

        if len(stripped_text) > 10000:
            body = stripped_text[:10000] + "\n\n--snipped--"
        else:
            body = stripped_text

        try:
            markdown_souptest(body)
        except SoupError:
            g.log.warning("bad markdown in modmail email: %s", body)
            abort(406, "invalid body")

        if parent.get_muted_user_in_conversation():
            queue_blocked_muted_email(sr, parent, sender_email, email_id)
            return

        # keep the subject consistent
        message_subject = parent.subject
        if not message_subject.startswith("re: "):
            message_subject = "re: " + message_subject

        system_user = Account.system_user()

        message, inbox_rel = Message._new(
            author=system_user,
            to=to,
            subject=message_subject,
            body=body,
            ip='0.0.0.0',
            parent=parent,
            sr=sr,
            from_sr=True,
            can_send_email=False,
            sent_via_email=True,
            email_id=email_id,
        )
        message._commit()
        queries.new_message(message, inbox_rel)
        g.stats.simple_event("mailgun.incoming.success")
        g.stats.simple_event("modmail_email.incoming_email")
