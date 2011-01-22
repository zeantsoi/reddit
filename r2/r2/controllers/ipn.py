from pylons.controllers.util import abort
from pylons import c, g, response
from pylons.i18n import _

from validator import *
from r2.models import *

from reddit_base import RedditController

def dump_parameters(parameters):
    for k, v in parameters.iteritems():
        g.log.info("IPN: %r = %r" % (k, v))

def check_payment_status(payment_status):
    if payment_status is None:
        payment_status = ''

    psl = payment_status.lower()

    if psl == 'completed':
        return (None, psl)
    elif psl == 'refunded':
        log_text("refund", "Just got notice of a refund.", "info")
        # TODO: something useful when this happens -- and don't
        # forget to verify first
        return ("Ok", psl)
    elif psl == 'pending':
        log_text("pending",
                 "Just got notice of a Pending, whatever that is.", "info")
        # TODO: something useful when this happens -- and don't
        # forget to verify first
        return ("Ok", psl)
    elif psl == 'reversed':
        log_text("reversal",
                 "Just got notice of a PayPal reversal.", "info")
        # TODO: something useful when this happens -- and don't
        # forget to verify first
        return ("Ok", psl)
    elif psl == 'canceled_reversal':
        log_text("canceled_reversal",
                 "Just got notice of a PayPal 'canceled reversal'.", "info")
        return ("Ok", psl)
    elif psl == '':
        return (None, psl)
    else:
        dump_parameters(parameters)
        raise ValueError("Unknown IPN status: %r" % payment_status)

def check_txn_type(txn_type, psl):
    if txn_type == 'subscr_signup':
        return ("Ok", None)
    elif txn_type == 'subscr_cancel':
        return ("Ok", "cancel")
    elif txn_type == 'subscr_eot':
        return ("Ok", None)
    elif txn_type == 'subscr_failed':
        log_text("failed_subscription",
                 "Just got notice of a failed PayPal resub.", "info")
        return ("Ok", None)
    elif txn_type == 'subscr_modify':
        log_text("modified_subscription",
                 "Just got notice of a modified PayPal sub.", "info")
        return ("Ok", None)
    elif txn_type in ('new_case',
        'recurring_payment_suspended_due_to_max_failed_payment'):
        return ("Ok", None)
    elif txn_type == 'subscr_payment' and psl == 'completed':
        return (None, "new")
    elif txn_type == 'web_accept' and psl == 'completed':
        return (None, None)
    else:
        raise ValueError("Unknown IPN txn_type / psl %r" %
                         ((txn_type, psl),))


def verify_ipn(parameters):
    paraemeters['cmd'] = '_notify-validate'
    try:
        safer = dict([k, v.encode('utf-8')] for k, v in parameters.items())
        params = urllib.urlencode(safer)
    except UnicodeEncodeError:
        g.log.error("problem urlencoding %r" % (parameters,))
        raise
    req = urllib2.Request(g.PAYPAL_URL, params)
    req.add_header("Content-type", "application/x-www-form-urlencoded")

    response = urllib2.urlopen(req)
    status = response.read()

    if status != "VERIFIED":
        raise ValueError("Invalid IPN response: %r" % status)


def existing_subscription(subscr_id):
    account_id = accountid_from_paypalsubscription(subscr_id)

    if account_id is None:
        return None

    try:
        account = Account._byID(account_id)
    except NotFound:
        g.log.info("Just got IPN renewal for deleted account #%d"
                   % account_id)
        return "deleted account"

    return account


class IpnController(RedditController):
    @textresponse(paypal_secret = VPrintable('secret', 50),
                  payment_status = VPrintable('payment_status', 20),
                  txn_id = VPrintable('txn_id', 20),
                  paying_id = VPrintable('payer_id', 50),
                  payer_email = VPrintable('payer_email', 250),
                  mc_currency = VPrintable('mc_currency', 20),
                  mc_gross = VFloat('mc_gross'),
                  custom = VPrintable('custom', 50))
    def POST_ipn(self, paypal_secret, payment_status, txn_id, paying_id,
                 payer_email, mc_currency, mc_gross, custom):

        parameters = request.POST.copy()

        # Make sure it's really PayPal
        if paypal_secret != g.PAYPAL_SECRET:
            log_text("invalid IPN secret",
                     "%s guessed the wrong IPN secret" % request.ip,
                     "warning")
            raise ValueError

        # Return early if it's an IPN class we don't care about
        response, psl = check_payment_status(payment_status)
        if response:
            return response

        # Return early if it's a txn_type we don't care about
        response, subscription = check_txn_type(parameters['txn_type'], psl)
        if subscription is None:
            subscr_id = None
        elif subscription == "new":
            subscr_id = parameters['subscr_id']
        elif subscription == "cancel":
            cancel_subscription(parameters['subscr_id'])
        else:
            raise ValueError("Weird subscription: %r" % subscription)

        if response:
            return response

        # Check for the debug flag, and if so, dump the IPN dict
        if g.cache.get("ipn-debug"):
            g.cache.delete("ipn-debug")
            dump_parameters(parameters)

        # More sanity checks...
        if False: # TODO: remove this line
            verify_ipn(parameters)

        if mc_currency != 'USD':
            raise ValueError("Somehow got non-USD IPN %r" % mc_currency)

        if not (txn_id and paying_id and payer_email and mc_gross):
            dump_parameters(parameters)
            raise ValueError("Got incomplete IPN")

        # Calculate pennies and days
        pennies = int(mc_gross * 100)
        if pennies >= 2999:
            days = 366 * (pennies / 2999)
        else:
            days = 31 * (pennies / 399)

        # Special case: autorenewal payment
        existing = existing_subscription(subscr_id)
        if existing:
            if existing != "deleted account":
                create_claimed_gold ("P" + txn_id, payer_email, paying_id,
                                     pennies, days, None, existing._id,
                                     c.start_time, subscr_id)
                admintools.engolden(existing, days)

                g.log.info("Just applied IPN renewal for %s, %d days" %
                           (existing.name, days))
            return "Ok"

        # More sanity checks that all non-autorenewals should pass:

        # Temporary hack for payments that come in as code is rolling
        if not custom:
            custom = g.hardcache.get("custom_override-" + txn_id)

        if not custom:
            dump_parameters(parameters)
            raise ValueError("Got IPN with txn_id=%s and no custom"
                             % txn_id)
        payment_blob = g.hardcache.get("payment_blob-%s" % custom)
        if not payment_blob:
            dump_parameters(parameters)
            raise ValueError("Got invalid custom '%s' in IPN" % custom)
        account_id = payment_blob.get('account_id', None)
        if not account_id:
            dump_parameters(parameters)
            raise ValueError("No account_id in IPN with custom='%s'" % custom)
        try:
            recipient = Account._byID(account_id)
        except NotFound:
            dump_parameters(parameters)
            raise ValueError("Invalid account_id %d in IPN with custom='%s'"
                             % (account_id, custom))
        if payment_blob['status'] == 'initialized':
            pass
        elif payment_blob['status'] == 'processed':
            dump_parameters(parameters)
            raise ValueError("Got IPN for an already-processed payment")
        else:
            dump_parameters(parameters)
            raise ValueError("Got status '%s' in IPN" % payment_blob['status'])

        # Begin critical section
        payment_blob['status'] = 'processing'
        g.hardcache.set("payment_blob-%s" % custom, payment_blob, 86400 * 30)

        if subscr_id:
            recipient.gold_subscr_id = subscr_id

        if payment_blob['goldtype'] in ('autorenew', 'onetime'):
            admintools.engolden(recipient, days)

            subject = _("thanks for buying reddit gold!")

            if g.lounge_reddit:
                lounge_url = "/r/" + g.lounge_reddit
                message = strings.lounge_msg % dict(link=lounge_url)
            else:
                message = ":)"

        elif payment_blob['goldtype'] == 'creddits':
            if pennies >= 2999:
                recipient._incr("gold_creddits", 12 * int(pennies / 2999))
            else:
                recipient._incr("gold_creddits", int(pennies / 399))
            recipient._commit()
            subject = _("thanks for buying creddits!")
            message = _("now go to someone's userpage and give them a present")

        # Reuse the old "secret" column as a place to record the goldtype
        # and "custom", just in case we need to debug it later or something
        secret = payment_blob['goldtype'] + "-" + custom

        create_claimed_gold(txn_id, payer_email, paying_id, pennies, days,
                            secret, account_id, c.start_time,
                            subscr_id, status="autoclaimed")

        send_system_message(recipient, subject, message)

        payment_blob['status'] = 'processed'
        g.hardcache.set("payment_blob-%s" % custom, payment_blob, 86400 * 30)
