from xml.dom.minidom import Document
from httplib import HTTPSConnection
from urlparse import urlparse
import base64

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

def _google_ordernum_request(ordernums):
    d = Document()
    n = d.createElement("notification-history-request")
    n.setAttribute("xmlns", "http://checkout.google.com/schema/2")
    d.appendChild(n)

    on = d.createElement("order-numbers")
    n.appendChild(on)

    for num in tup(ordernums):
        gon = d.createElement('google-order-number')
        gon.appendChild(d.createTextNode("%s" % num))
        on.appendChild(gon)

    return _google_checkout_post(g.GOOGLE_REPORT_URL, d.toxml("UTF-8"))

def _google_charge_and_ship(ordernum):
    d = Document()
    n = d.createElement("charge-and-ship-order")
    n.setAttribute("xmlns", "http://checkout.google.com/schema/2")
    n.setAttribute("google-order-number", ordernum)

    d.appendChild(n)

    return _google_checkout_post(g.GOOGLE_REQUEST_URL, d.toxml("UTF-8"))


def _google_checkout_post(url, params):
    u = urlparse("%s%s" % (url, g.GOOGLE_ID))
    conn = HTTPSConnection(u.hostname, u.port)
    auth = base64.encodestring('%s:%s' % (g.GOOGLE_ID, g.GOOGLE_KEY))[:-1]
    headers = {"Authorization": "Basic %s" % auth,
               "Content-type": "text/xml; charset=\"UTF-8\""}

    conn.request("POST", u.path, params, headers)
    response = conn.getresponse().read()
    conn.close()

    return BeautifulStoneSoup(response)

class IpnController(RedditController):
    @textresponse(sn = VLength('serial-number', 100))
    def POST_gcheckout(self, sn):
        if sn:
            sn = sn.split('-')[0]
            g.log.error( "GOOGLE CHECKOUT: %s" % sn)
            trans = _google_ordernum_request(sn)

            # get the financial details
            auth = trans.find("authorization-amount-notification")

            if not auth:
                # see if the payment was declinded
                status = trans.findAll('financial-order-state')
                if 'PAYMENT_DECLINED' in [x.contents[0] for x in status]:
                    g.log.error("google declined transaction found: '%s'" %
                                sn)
                elif 'REVIEWING' not in [x.contents[0] for x in status]:
                    g.log.error(("google transaction not found: " +
                                 "'%s', status: %s")
                                % (sn, [x.contents[0] for x in status]))
                else:
                    g.log.error(("google transaction status: " +
                                 "'%s', status: %s")
                                % (sn, [x.contents[0] for x in status]))
            elif auth.find("financial-order-state"
                           ).contents[0] == "CHARGEABLE":
                email = str(auth.find("email").contents[0])
                payer_id = str(auth.find('buyer-id').contents[0])
                # get the "secret"
                custom = None
                cart = trans.find("shopping-cart")
                if cart:
                    for item in cart.findAll("merchant-private-item-data"):
                        custom = str(item.contents[0])
                        break
                if custom:
                    days = None
                    try:
                        pennies = int(float(trans.find("order-total"
                                                      ).contents[0])*100)
                        if pennies >= 2999:
                            days = 366 * (pennies / 2999)
                        else:
                            days = 31 * (pennies / 399)
                        charged = trans.find("charge-amount-notification")
                        if not charged:
                            _google_charge_and_ship(sn)

                        parameters = request.POST.copy()
                        self.finish(parameters, "g%s" % sn,
                                    email, payer_id, None,
                                    custom, pennies, days)
                    except ValueError, e:
                        g.log.error(e)
                else:
                    raise ValueError("Got no custom blob for %s" % sn)

            return (('<notification-acknowledgment ' +
                     'xmlns="http://checkout.google.com/schema/2" ' +
                     'serial-number="%s" />') % sn)
        else:
            g.log.error("GOOGLE CHCEKOUT: didn't work")
            g.log.error(repr(list(request.POST.iteritems())))

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

        self.finish(parameters, "P" + txn_id,
                    payer_email, paying_id, subscr_id,
                    custom, pennies, days)

    def finish(self, parameters, txn_id,
               payer_email, paying_id, subscr_id,
               custom, pennies, days):
#        g.log.error("Looking up: %s" % ("payment_blob-%s" % custom))
        payment_blob = g.hardcache.get("payment_blob-%s" % custom)
#        g.log.error("Got back: %s" % payment_blob)
        if not payment_blob:
            dump_parameters(parameters)
            raise ValueError("Got invalid custom '%s' in IPN/GC" % custom)
        account_id = payment_blob.get('account_id', None)
        if not account_id:
            dump_parameters(parameters)
            raise ValueError("No account_id in IPN/GC with custom='%s'" % custom)
        try:
            recipient = Account._byID(account_id)
        except NotFound:
            dump_parameters(parameters)
            raise ValueError("Invalid account_id %d in IPN/GC with custom='%s'"
                             % (account_id, custom))
        if payment_blob['status'] == 'initialized':
            pass
        elif payment_blob['status'] == 'processed':
            dump_parameters(parameters)
            raise ValueError("Got IPN/GC for an already-processed payment")
        else:
            dump_parameters(parameters)
            raise ValueError("Got status '%s' in IPN/GC" % payment_blob['status'])

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
