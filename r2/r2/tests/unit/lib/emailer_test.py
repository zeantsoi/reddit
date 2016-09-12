from mock import MagicMock, patch

from pylons import app_globals as g
from r2.tests import RedditTestCase
from r2.lib.emailer import make_message_dict_unique
from r2.lib.providers.email import EmailProvider
from r2.lib.providers.email.null import NullEmailProvider
from r2.models import Email
from r2.lib import emailer


DUMMY_EMAIL_ERROR = Exception("the world is coming down!")


class FakeEmailProvider(EmailProvider):

    def send_email(self, to_address, from_address, subject,
                   text=None, html=None,
                   reply_to=None, custom_headers=None,
                   parent_email_id=None,
                   other_email_ids=None, email_type=None):
        raise DUMMY_EMAIL_ERROR


DUMMY_EMAILS_CONTAINER = []


class FakeEmail(object):
    @classmethod
    def get_unsent(cls, max_date, batch_limit=50, kind=None):
        for i in DUMMY_EMAILS_CONTAINER:
            yield i


class FakeEmailHandler(object):
    def clear_queue_by_uids(self, uids):
        self.uids = uids

    def get_cleared(self):
        return self.uids


class FakeMIMEText(object):
    def __init__(self, text):
        self.text = text

    def as_string(self):
        return self.text


def bit(x, i):
    """Return true if i'th bit is set in integer x"""
    return x & (1 << i) != 0


def generate_dummy_email(kind, to_addr, body, uid):
    email = MagicMock()
    email.kind = kind
    email.body = body
    email.uid = uid
    email.to_MIMEText = lambda: FakeMIMEText(body)
    email.fr_addr = "reddit@reddit.com"
    email.to_addr = to_addr

    return email


def generate_dummy_emails(kinds):
    ret = []
    i = 0
    for kind in kinds:
        ret.append(generate_dummy_email(
            kind,
            "lev@reddit.com",
            "foo and bar and baz",
            i,
        ))
        i += 1
    return ret


class TestEmailer(RedditTestCase):
    def setUp(self):
        g.email_provider = NullEmailProvider()

    def test_make_message_dict_unique(self):
        data = {
            1: '{"to": "1", "start_date": "2016-03-18 22:56:41"}',
            2: '{"to": "1", "start_date": "2016-03-19 22:56:41"}',
            3: '{"to": "2", "start_date": "2016-03-18 22:56:41"}',
        }

        correct_data = {
            '1': {"to": "1", "start_date": "2016-03-19 22:56:41"},
            '2': {"to": "2", "start_date": "2016-03-18 22:56:41"},
        }

        json_data = make_message_dict_unique(data)
        self.assertEquals(json_data, correct_data)

    def test_sendmail_using_mailgun(self):
        # test that  we set email to sent with rejected equal to False
        email = MagicMock()
        emailer._sendmail_using_mailgun(email)
        email.set_sent.assert_called_once_with(rejected=False)

        # test that we set email to rejected if mailgun throws an error
        g.log = MagicMock()
        email = MagicMock()
        g.email_provider = FakeEmailProvider()
        with self.assertRaises(Exception) as error_context:
            emailer._sendmail_using_mailgun(email)
        self.assertEquals(DUMMY_EMAIL_ERROR, error_context.exception)

        email.set_sent.assert_called_once_with(rejected=True)
        g.log.exception.assert_called_once_with(DUMMY_EMAIL_ERROR)

    def test_sendmail(self):

        session = MagicMock()
        session.sendmail = lambda *a, **kw: True

        # test that  we set email to sent with rejected equal to False
        email = MagicMock()
        emailer._sendmail(email, session)
        email.set_sent.assert_called_once_with(rejected=False)

        # test that we propogate exception
        def bad_send_mail(*k, **kw):
            raise DUMMY_EMAIL_ERROR
        session.sendmail = bad_send_mail
        email = MagicMock()
        error = None
        try:
            emailer._sendmail(email, session)
        except Exception as e:
            error = e

        self.assertIsNotNone(error)
        self.assertEquals(error, DUMMY_EMAIL_ERROR)

        # test that we set email to rejected if we catch one of
        # the exceptions we are catching
        def raise_AttributeError(*k, **kw):
            raise AttributeError("foo")

        error = None
        session.sendmail = raise_AttributeError
        email = MagicMock()
        try:
            emailer._sendmail(email, session)
        except Exception as e:
            error = e

        self.assertIsNone(error)
        email.set_sent.assert_called_once_with(rejected=True)

    def check_send_queued_mail(self, emails, fails):
        DUMMY_EMAILS_CONTAINER[:] = []
        DUMMY_EMAILS_CONTAINER.extend(emails)
        big_email = FakeEmail()
        big_email_handler = FakeEmailHandler()

        index_val = [0]

        sent_by_mailgun = []
        sent_by_smtp = []
        errors = []

        real_send_mail_using_mailgun = emailer._sendmail_using_mailgun
        real_sendmail = emailer._sendmail

        def mailgun_send(email, test):
            i = index_val[0]
            index_val[0] += 1
            if fails[i]:
                g.email_provider = FakeEmailProvider()
            else:
                g.email_provider = NullEmailProvider()

            real_send_mail_using_mailgun(email, test)
            sent_by_mailgun.append(email)

        def raise_exception(*k, **kw):
            raise DUMMY_EMAIL_ERROR

        def smtp_send(email, session, test):
            i = index_val[0]
            index_val[0] += 1
            if fails[i]:
                session.sendmail = raise_exception
            else:
                session.sendmail = lambda *k, **kw: True

            real_sendmail(email, session, test)
            sent_by_smtp.append(email)

        smtp = MagicMock()

        with patch('r2.lib.emailer._sendmail_using_mailgun',
                   new=mailgun_send), \
            patch('r2.lib.emailer._sendmail', new=smtp_send), \
            patch('smtplib.SMTP', new=smtp), \
            patch.object(Email, 'handler', big_email_handler), \
            patch.object(Email, 'get_unsent',
                         new=big_email.get_unsent):
            try:
                emailer._send_queued_mail()
            except Exception as e:
                errors.append(e)

        uids_sent = set([email.uid for email in sent_by_mailgun] +
                        [email.uid for email in sent_by_smtp])
        uids_cleared = set(big_email_handler.get_cleared())
        # check that sent emails have been cleared
        for uid in uids_sent:
            self.assertTrue(uid in uids_cleared)

        already_failed = False
        for i in xrange(0, len(fails)):
            if not fails[i] and not already_failed:
                # if we never failed already then we should have
                # cleared this uid
                self.assertTrue(emails[i].uid in uids_cleared)
                emails[i].set_sent.assert_called_once_with(rejected=False)
            elif fails[i] and not already_failed:
                # if we are failing for the first time, we should
                # still clear this uid
                already_failed = True
                self.assertTrue(emails[i].uid in uids_cleared)
                # for mail gun we always set rejected ot true.
                # for older SMTP an Exception is propogated
                if emails[i].kind == Email.Kind.RESET_PASSWORD:
                    emails[i].set_sent.assert_called_once_with(rejected=True)
            elif already_failed:
                # if we have previously failed,
                # we should not have cleared this uid
                self.assertFalse(emails[i].uid in uids_cleared)
                emails[i].set_sent.assert_not_called()

        if already_failed:
            self.assertEquals(1, len(errors))

    def test_send_queued_mail_multiplexer(self):
        self.check_send_queued_mail(
            generate_dummy_emails(
                [Email.Kind.FEEDBACK, Email.Kind.RESET_PASSWORD]),
            [False for i in xrange(0, 2)]
        )

    def test_send_queued_mail_failures(self):
        def generate_kinds_from_bit(x, n):
            return [Email.Kind.FEEDBACK if bit(x, i)
                    else Email.Kind.RESET_PASSWORD for i in xrange(0, n)]

        def generate_fails_from_bit(x, n):
            return [bit(x, i) for i in xrange(0, n)]

        N = 4
        # try all combinations of different kinds of emails
        # and orders of failure.
        for i in xrange(0, 1 << N):
            for j in xrange(0, 1 << N):
                kinds = generate_kinds_from_bit(i, N)
                fails = generate_fails_from_bit(j, N)
                self.check_send_queued_mail(
                    generate_dummy_emails(kinds),
                    fails)
