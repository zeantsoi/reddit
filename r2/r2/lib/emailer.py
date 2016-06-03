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

from email import encoders
from email.MIMEBase import MIMEBase
from email.MIMEText import MIMEText
from email.MIMEMultipart import MIMEMultipart
from email.errors import HeaderParseError
import datetime
import traceback, sys, smtplib
import hashlib

from pylons import tmpl_context as c
from pylons import app_globals as g
from pylons import request
from pylons.i18n import N_
import simplejson as json

from r2.config import feature
from r2.lib import hooks
from r2.lib.ratelimit import SimpleRateLimit
from r2.lib.utils import timeago, long_datetime
from r2.models import (
    Account,
    Award,
    Comment,
    DefaultSR,
    Email,
    Inbox,
    Link,
    Subreddit,
)
from r2.models.link import (
    NOTIFICATION_EMAIL_COOLING_PERIOD,
    NOTIFICATION_EMAIL_MAX_DELAY,
)
from r2.models.token import EmailVerificationToken, PasswordResetToken


trylater_hooks = hooks.HookRegistrar()

def _system_email(email, plaintext_body, kind, reply_to="",
        thing=None, from_address=g.feedback_email,
        html_body="", list_unsubscribe_header="", user=None,
        suppress_username=False):
    """
    For sending email from the system to a user (reply address will be
    feedback and the name will be reddit.com)
    """
    if suppress_username:
        user = None
    elif user is None and c.user_is_loggedin:
        user = c.user

    Email.handler.add_to_queue(user,
        email, g.domain, from_address, kind,
        body=plaintext_body, reply_to=reply_to, thing=thing,
        html_body=html_body, list_unsubscribe_header=list_unsubscribe_header,
    )

def _nerds_email(body, from_name, kind):
    """
    For sending email to the nerds who run this joint
    """
    Email.handler.add_to_queue(None, g.nerds_email, from_name, g.nerds_email,
                               kind, body = body)

def _ads_email(body, from_name, kind):
    """
    For sending email to ads
    """
    Email.handler.add_to_queue(None, g.ads_email, from_name, g.ads_email,
                               kind, body=body)

def _fraud_email(body, kind):
    """
    For sending email to the fraud mailbox
    """
    Email.handler.add_to_queue(None, g.fraud_email, g.domain, g.fraud_email,
                               kind, body=body)

def _community_email(body, kind):
    """
    For sending email to the community mailbox
    """
    Email.handler.add_to_queue(c.user, g.community_email, g.domain, g.community_email,
                               kind, body=body)

def verify_email(user, dest=None):
    """
    For verifying an email address
    """
    from r2.lib.pages import VerifyEmail
    user.email_verified = False
    user._commit()
    Award.take_away("verified_email", user)

    token = EmailVerificationToken._new(user)
    base = g.https_endpoint or g.origin
    emaillink = base + '/verification/' + token._id
    if dest:
        emaillink += '?dest=%s' % dest
    g.log.debug("Generated email verification link: " + emaillink)

    _system_email(user.email,
                  VerifyEmail(user=user,
                              emaillink = emaillink).render(style='email'),
                  Email.Kind.VERIFY_EMAIL)

def password_email(user):
    """
    For resetting a user's password.
    """
    from r2.lib.pages import PasswordReset

    user_reset_ratelimit = SimpleRateLimit(
        name="email_reset_count_%s" % user._id36,
        seconds=int(datetime.timedelta(hours=12).total_seconds()),
        limit=3,
    )
    if not user_reset_ratelimit.record_and_check():
        return False

    global_reset_ratelimit = SimpleRateLimit(
        name="email_reset_count_global",
        seconds=int(datetime.timedelta(hours=1).total_seconds()),
        limit=1000,
    )
    if not global_reset_ratelimit.record_and_check():
        raise ValueError("password reset ratelimit exceeded")

    token = PasswordResetToken._new(user)
    base = g.https_endpoint or g.origin
    passlink = base + '/resetpassword/' + token._id
    g.log.info("Generated password reset link: " + passlink)
    _system_email(user.email,
                  PasswordReset(user=user,
                                passlink=passlink).render(style='email'),
                  Email.Kind.RESET_PASSWORD,
                  reply_to=g.support_email,
                  user=user,
                  )
    return True

@trylater_hooks.on('trylater.message_notification_email')
def message_notification_email(data):
    """Queues a system email for a new message notification."""
    from r2.lib.pages import MessageNotificationEmail

    MAX_EMAILS_PER_USER = 30
    MAX_MESSAGES_PER_BATCH = 5

    for datum in data.itervalues():
        datum = json.loads(datum)
        user = Account._byID36(datum['to'], data=True)

        # In case a user has enabled the preference while it was enabled for
        # them, but we've since turned it off.  We need to explicitly state the
        # user because we're not in the context of an HTTP request from them.
        if not feature.is_enabled('orangereds_as_emails', user=user):
            continue

        # Don't send more than MAX_EMAILS_PER_USER per user per day
        USER_MESSAGE_THROTTLE_KEY = "email-message_notification_%s" % user._id
        g.cache.add(USER_MESSAGE_THROTTLE_KEY, 0, time=24*60*60)
        if g.cache.get(USER_MESSAGE_THROTTLE_KEY) > MAX_EMAILS_PER_USER:
            continue

        # Get all new messages that haven't been emailed
        inbox_items = Inbox.get_unread_and_unemailed(user._id)
        inbox_items = sorted(inbox_items, key=lambda x: x[1]._date)

        if not inbox_items:
            continue
        newest_inbox_rel = inbox_items[-1][0]
        oldest_inbox_rel = inbox_items[0][0]

        now = datetime.datetime.now(g.tz)
        start_date = datetime.datetime.strptime(datum['start_date'],
                     "%Y-%m-%d %H:%M:%S").replace(tzinfo=g.tz)

        # If messages are still being queued within the cooling period or
        # messages have been queued past the max delay, then keep waiting
        # a little longer to batch all of the messages up
        if (start_date != newest_inbox_rel._date and
                now < newest_inbox_rel._date + NOTIFICATION_EMAIL_COOLING_PERIOD and
                now < oldest_inbox_rel._date + NOTIFICATION_EMAIL_MAX_DELAY):
            continue

        messages = []
        message_count = 0
        more_unread_messages = False
        non_preview_usernames = set()

        # Batch messages to email starting with older messages
        for inbox_rel, message in inbox_items:
            # Get sender_name, replacing with display_author if it exists
            if getattr(message, 'from_sr', False):
                sender_name = ('/r/%s' %
                    Subreddit._byID(message.sr_id, data=True).name)
            else:
                if getattr(message, 'display_author', False):
                    sender_id = message.display_author
                else:
                    sender_id = message.author_id
                sender_name = '/u/%s' % Account._byID(sender_id, data=True).name

            if message_count >= MAX_MESSAGES_PER_BATCH:
                # prevent duplicate usernames for template display
                non_preview_usernames.add(sender_name)
                more_unread_messages = True
            else:
                if isinstance(message, Comment):
                    permalink = message.make_permalink_slow(context=1,
                        force_domain=True)
                    link = None
                    parent = None
                    if message.parent_id:
                        parent = Comment._byID(message.parent_id, data=True)
                    else:
                        link = Link._byID(message.link_id, data=True)
                    if parent and parent.author_id == user._id:
                        message_type = N_("comment reply")
                    elif not parent and link.author_id == user._id:
                        message_type = N_("post reply")
                    else:
                        message_type = N_("username notification")
                else:
                    permalink = message.make_permalink(force_domain=True)
                    message_type = N_("message")

                messages.append({
                    "author_name": sender_name,
                    "message_type": message_type,
                    "body": message.body,
                    "date": long_datetime(message._date),
                    "permalink": permalink,
                    "id": message._id,
                    "fullname": message._fullname,
                    "subject": getattr(message, 'subject', ''),
                })

            inbox_rel.emailed = True
            inbox_rel._commit()
            message_count += 1

        mac = generate_notification_email_unsubscribe_token(
                datum['to'], user_email=user.email,
                user_password_hash=user.password)
        base = g.https_endpoint or g.origin
        unsubscribe_link = base + '/mail/unsubscribe/%s/%s' % (datum['to'], mac)
        inbox_url = base + '/message/inbox'

        # unique email_hash for emails, to be used in utm tags
        id_str = ''.join(str(message['id'] for message in messages))
        email_hash = hashlib.sha1(id_str).hexdigest()
        
        base_utm_query = {
            'utm_name': email_hash, 
            'utm_source': 'email', 
            'utm_medium':'message_notification',
        }
        
        non_preview_usernames_str = generate_non_preview_usernames_str(
                                        non_preview_usernames)

        templateData = {
            'messages': messages,
            'unsubscribe_link': unsubscribe_link,
            'more_unread_messages': more_unread_messages,
            'message_count': message_count,
            'max_message_display_count': MAX_MESSAGES_PER_BATCH,
            'non_preview_usernames_str': non_preview_usernames_str,
            'base_url': base,
            'base_utm_query': base_utm_query,
            'inbox_url': inbox_url,
        }
        custom_headers = {
            'List-Unsubscribe': "<%s>" % unsubscribe_link
        }

        g.email_provider.send_email(
            to_address=user.email,
            from_address="Reddit <%s>" % g.notification_email,
            subject=Email.subjects[Email.Kind.MESSAGE_NOTIFICATION],
            text=MessageNotificationEmail(**templateData).render(style='email'),
            html=MessageNotificationEmail(**templateData).render(style='html'),
            custom_headers=custom_headers,
            email_type='message_notification_email',
        )

        # report the email event to data pipeline
        g.events.orangered_email_event(
            request=request,
            context=c,
            user=user,
            messages=messages,
            email_hash=email_hash,
            reply_count=message_count,
            newest_reply_age=newest_inbox_rel._date,
            oldest_reply_age=oldest_inbox_rel._date,
        )

        g.stats.simple_event('email.message_notification.queued')
        g.cache.incr(USER_MESSAGE_THROTTLE_KEY)

def generate_non_preview_usernames_str(usernames):
    """ produces string of usernames for whom a message preview is not 
    displayed, for easy use in template
    """
    usernames = list(usernames)

    if len(usernames) == 0:
        return

    if len(usernames) == 1:
        return usernames[0]

    if len(usernames) > 5:
        # returns "username1, username2, and more"
        usernames = usernames[:5]
        usernames.append("and more")
    else:
        # returns "username1, username2, and username3"
        usernames.append("and %s" % usernames.pop())

    return ', '.join(usernames)

def generate_notification_email_unsubscribe_token(user_id36, user_email=None,
                                                  user_password_hash=None):
    """Generate a token used for one-click unsubscribe links for notification
    emails.

    user_id36: A base36-encoded user id.
    user_email: The user's email.  Looked up if not provided.
    user_password_hash: The hash of the user's password.  Looked up if not
                        provided.
    """
    import hashlib
    import hmac

    if (not user_email) or (not user_password_hash):
        user = Account._byID36(user_id36, data=True)
        if not user_email:
            user_email = user.email
        if not user_password_hash:
            user_password_hash = user.password

    return hmac.new(
        g.secrets['email_notifications'],
        user_id36 + user_email + user_password_hash,
        hashlib.sha256).hexdigest()

def password_change_email(user):
    """Queues a system email for a password change notification."""
    from r2.lib.pages import PasswordChangeEmail

    return _system_email(user.email,
                         PasswordChangeEmail(user=user).render(style='email'),
                         Email.Kind.PASSWORD_CHANGE,
                         reply_to=g.support_email,
                         user=user,
                         )

def email_change_email(user):
    """Queues a system email for a email change notification."""
    from r2.lib.pages import EmailChangeEmail

    return _system_email(user.email,
                         EmailChangeEmail(user=user).render(style='email'),
                         Email.Kind.EMAIL_CHANGE,
                         reply_to=g.support_email,
                         )

def community_email(body, kind):
    return _community_email(body, kind)


def nerds_email(body, from_name=g.domain):
    """Queues a feedback email to the nerds running this site."""
    return _nerds_email(body, from_name, Email.Kind.NERDMAIL)

def ads_email(body, from_name=g.domain):
    """Queues an email to the Sales team."""
    return _ads_email(body, from_name, Email.Kind.ADS_ALERT)

def share(link, emails, from_name = "", reply_to = "", body = ""):
    """Queues a 'share link' email."""
    now = datetime.datetime.now(g.tz)
    ival = now - timeago(g.new_link_share_delay)
    date = max(now,link._date + ival)
    Email.handler.add_to_queue(c.user, emails, from_name, g.share_reply,
                               Email.Kind.SHARE, date = date,
                               body = body, reply_to = reply_to,
                               thing = link)

def send_queued_mail(test = False):
    """sends mail from the mail queue to smtplib for delivery.  Also,
    on successes, empties the mail queue and adds all emails to the
    sent_mail list."""
    from r2.lib.pages import Share, Mail_Opt
    now = datetime.datetime.now(g.tz)
    if not c.site:
        c.site = DefaultSR()

    clear = False
    if not test:
        session = smtplib.SMTP(g.smtp_server)
    def sendmail(email):
        try:
            mimetext = email.to_MIMEText()
            if mimetext is None:
                print ("Got None mimetext for email from %r and to %r"
                       % (email.fr_addr, email.to_addr))
            if test:
                print mimetext.as_string()
            else:
                session.sendmail(email.fr_addr, email.to_addr,
                                 mimetext.as_string())
                email.set_sent(rejected = False)
        # exception happens only for local recipient that doesn't exist
        except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused,
                UnicodeDecodeError, AttributeError, HeaderParseError):
            # handle error and print, but don't stall the rest of the queue
            print "Handled error sending mail (traceback to follow)"
            traceback.print_exc(file = sys.stdout)
            email.set_sent(rejected = True)


    try:
        for email in Email.get_unsent(now):
            clear = True

            should_queue = email.should_queue()
            # check only on sharing that the mail is invalid
            if email.kind == Email.Kind.SHARE:
                if should_queue:
                    email.body = Share(username = email.from_name(),
                                       msg_hash = email.msg_hash,
                                       link = email.thing,
                                       body =email.body).render(style = "email")
                else:
                    email.set_sent(rejected = True)
                    continue
            elif email.kind == Email.Kind.OPTOUT:
                email.body = Mail_Opt(msg_hash = email.msg_hash,
                                      leave = True).render(style = "email")
            elif email.kind == Email.Kind.OPTIN:
                email.body = Mail_Opt(msg_hash = email.msg_hash,
                                      leave = False).render(style = "email")
            # handle unknown types here
            elif not email.body:
                print ("Rejecting email with an empty body from %r and to %r"
                       % (email.fr_addr, email.to_addr))
                email.set_sent(rejected = True)
                continue
            sendmail(email)

    finally:
        if not test:
            session.quit()

    # clear is true if anything was found and processed above
    if clear:
        Email.handler.clear_queue(now)



def opt_out(msg_hash):
    """Queues an opt-out email (i.e., a confirmation that the email
    address has been opted out of receiving any future mail)"""
    email, added =  Email.handler.opt_out(msg_hash)
    if email and added:
        _system_email(email, "", Email.Kind.OPTOUT)
    return email, added

def opt_in(msg_hash):
    """Queues an opt-in email (i.e., that the email has been removed
    from our opt out list)"""
    email, removed =  Email.handler.opt_in(msg_hash)
    if email and removed:
        _system_email(email, "", Email.Kind.OPTIN)
    return email, removed


def _promo_email(thing, kind, body = "", **kw):
    from r2.lib.pages import Promo_Email
    a = Account._byID(thing.author_id, True)

    if not a.email:
        return

    body = Promo_Email(link = thing, kind = kind,
                       body = body, **kw).render(style = "email")
    return _system_email(a.email, body, kind, thing = thing,
                         reply_to = g.selfserve_support_email,
                         suppress_username=True)


def new_promo(thing):
    return _promo_email(thing, Email.Kind.NEW_PROMO)

def promo_total_budget(thing, total_budget_dollars, start_date):
    return _promo_email(thing, Email.Kind.BID_PROMO,
        total_budget_dollars = total_budget_dollars, start_date = start_date)

def accept_promo(thing):
    return _promo_email(thing, Email.Kind.ACCEPT_PROMO)

def reject_promo(thing, reason = ""):
    return _promo_email(thing, Email.Kind.REJECT_PROMO, reason)

def edited_live_promo(thing):
    return _promo_email(thing, Email.Kind.EDITED_LIVE_PROMO)

def queue_promo(thing, total_budget_dollars, trans_id):
    return _promo_email(thing, Email.Kind.QUEUED_PROMO,
        total_budget_dollars=total_budget_dollars, trans_id = trans_id)

def live_promo(thing):
    return _promo_email(thing, Email.Kind.LIVE_PROMO)

def finished_promo(thing):
    return _promo_email(thing, Email.Kind.FINISHED_PROMO)


def auto_extend_promo(thing, campaign):
    return _promo_email(thing, Email.Kind.AUTO_EXTEND_PROMO, campaign=campaign)


def refunded_promo(thing):
    return _promo_email(thing, Email.Kind.REFUNDED_PROMO)


def void_payment(thing, campaign, total_budget_dollars, reason):
    return _promo_email(thing, Email.Kind.VOID_PAYMENT, campaign=campaign,
                        total_budget_dollars=total_budget_dollars,
                        reason=reason)

def changed_promo_author(thing, author):
    return _promo_email(thing, Email.Kind.CHANGED_AUTHOR, author=author)


def fraud_alert(body):
    return _fraud_email(body, Email.Kind.FRAUD_ALERT)

def suspicious_payment(user, link):
    from r2.lib.pages import SuspiciousPaymentEmail

    body = SuspiciousPaymentEmail(user, link).render(style="email")
    kind = Email.Kind.SUSPICIOUS_PAYMENT

    return _fraud_email(body, kind)


def send_html_email(to_addr, from_addr, subject, html,
        subtype="html", attachments=None):
    from r2.lib.filters import _force_utf8
    if not attachments:
        attachments = []

    msg = MIMEMultipart()
    msg.attach(MIMEText(_force_utf8(html), subtype))
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr

    for attachment in attachments:
        part = MIMEBase('application', "octet-stream")
        part.set_payload(attachment['contents'])
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', 'attachment',
            filename=attachment['name'])
        msg.attach(part)

    session = smtplib.SMTP(g.smtp_server)
    session.sendmail(from_addr, to_addr, msg.as_string())
    session.quit()

trylater_hooks.register_all()
