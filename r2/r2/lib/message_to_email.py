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

from pylons import app_globals as g
import requests

from r2.lib import amqp
from r2.lib.utils import constant_time_compare
from r2.models import (
    Account,
    Message,
    Subreddit,
)


def get_reply_to_address(message):
    """Construct a reply-to address that encodes the message id.

    The address is of the form:
        modmailreply+{subreddit_id36}-{message_id36}-{email_mac}

    where the mac is generated from {subreddit_id36}-{message_id36} using
    the `modmail_email_secret`

    The reply address should be configured with the inbound email service so
    that replies to our messages are routed back to the app somehow. For mailgun
    this involves adding a Routes filter for messages sent to
    "modmailreply\+*@". to be forwarded to POST /api/modmailreply.

    """

    sr = Subreddit._byID(message.sr_id, data=True)

    email_id = "-".join([sr._id36, message._id36])
    email_mac = hmac.new(
        g.secrets['modmail_email_secret'], email_id, hashlib.sha256).hexdigest()
    reply_id = "modmailreply+{email_id}-{email_mac}".format(
        email_id=email_id, email_mac=email_mac)

    return "r/{subreddit} mail <{reply_id}@{domain}>".format(
        subreddit=sr.name, reply_id=reply_id, domain=g.modmail_email_domain)


def parse_and_validate_reply_to_address(address):
    """Validate the address and parse out and return the message id.
    
    This is the reverse operation of `get_reply_to_address`.
    
    """

    recipient, sep, domain = address.partition("@")
    if not sep or not recipient or domain != g.modmail_email_domain:
        return

    main, sep, remainder = recipient.partition("+")
    if not sep or not main or main != "modmailreply":
        return

    try:
        subreddit_id36, message_id36, mac = remainder.split("-")
    except ValueError:
        return

    email_id = "-".join((subreddit_id36, message_id36))
    expected_mac = hmac.new(
        g.secrets['modmail_email_secret'], email_id, hashlib.sha256).hexdigest()

    if not constant_time_compare(expected_mac, mac):
        return

    return message_id36


def send_modmail_email(message):
    if not message.sr_id:
        return

    sr = Subreddit._byID(message.sr_id, data=True)

    if not sr.modmail_email_address:
        return

    sender = Account._byID(message.author_id, data=True)

    from_address = "u/{username} <{sender_email}>".format(
        username=sender.name, sender_email=g.modmail_sender_email)

    reply_to = get_reply_to_address(message)

    parent_email_id = None
    other_email_ids = []
    if message.parent_id:
        parent = Message._byID(message.parent_id, data=True)
        if parent.email_id:
            other_email_ids.append(parent.email_id)
            parent_email_id = parent.email_id

    if message.first_message:
        first_message = Message._byID(message.first_message, data=True)
        if first_message.email_id:
            other_email_ids.append(first_message.email_id)
        conversation_subject = first_message.subject
    else:
        conversation_subject = message.subject

    subject = "[r/{subreddit} mail]: {subject}".format(
        subreddit=sr.name, subject=conversation_subject)

    reply_footer = ("\n\n-\n"
        "Reply to this email directly or view it on reddit: {link}").format(
            link=message.make_permalink(force_domain=True))
    message_text = message.body + reply_footer

    email_id = g.email_provider.send_email(
        to_address=sr.modmail_email_address,
        from_address=from_address,
        subject=subject,
        text=message_text,
        reply_to=reply_to,
        parent_email_id=parent_email_id,
        other_email_ids=other_email_ids,
    )
    if email_id:
        g.log.info("sent %s as %s", message._id36, email_id)
        message.email_id = email_id
        message._commit()


def queue_modmail_email(message):
    amqp.add_item("modmail_email_q", message._id36)


def process_modmail_email():
    @g.stats.amqp_processor("modmail_email_q")
    def process_message(msg):
        message_id36 = msg.body
        message = Message._byID36(message_id36, data=True)
        send_modmail_email(message)

    amqp.consume_items("modmail_email_q", process_message)
