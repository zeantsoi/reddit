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
# The Original Code is Reddit.
#
# The Original Developer is the Initial Developer.  The Initial Developer of the
# Original Code is CondeNet, Inc.
#
# All portions of the code written by CondeNet are Copyright (c) 2006-2010
# CondeNet, Inc. All Rights Reserved.
################################################################################

from r2.lib.db.tdb_sql import make_metadata, index_str, create_table

from pylons import g, c
from datetime import datetime
import sqlalchemy as sa
from sqlalchemy.exceptions import IntegrityError

from xml.dom.minidom import Document
from r2.lib.utils import tup, randstr
from httplib import HTTPSConnection
from urlparse import urlparse
import socket, base64
from BeautifulSoup import BeautifulStoneSoup

gold_bonus_cutoff = datetime(2010,7,27,0,0,0,0,g.tz)

ENGINE_NAME = 'authorize'

ENGINE = g.dbm.get_engine(ENGINE_NAME)
METADATA = make_metadata(ENGINE)

gold_table = sa.Table('reddit_gold', METADATA,
                      sa.Column('trans_id', sa.String, nullable = False,
                                primary_key = True),
                      # status can be: invalid, unclaimed, claimed
                      sa.Column('status', sa.String, nullable = False),
                      sa.Column('date', sa.DateTime(timezone=True),
                                nullable = False, 
                                default = sa.func.now()),
                      sa.Column('payer_email', sa.String, nullable = False),
                      sa.Column('paying_id', sa.String, nullable = False),
                      sa.Column('pennies', sa.Integer, nullable = False),
                      sa.Column('secret', sa.String, nullable = True),
                      sa.Column('account_id', sa.String, nullable = True),
                      sa.Column('days', sa.Integer, nullable = True),
                      sa.Column('subscr_id', sa.String, nullable = True))

indices = [index_str(gold_table, 'status', 'status'),
           index_str(gold_table, 'date', 'date'),
           index_str(gold_table, 'account_id', 'account_id'),
           index_str(gold_table, 'secret', 'secret', unique = True),
           index_str(gold_table, 'payer_email', 'payer_email'),
           index_str(gold_table, 'subscr_id', 'subscr_id')]
create_table(gold_table, indices)

def create_unclaimed_gold (trans_id, payer_email, paying_id,
                           pennies, days, secret, date,
                           subscr_id = None):
    
    try:
        gold_table.insert().execute(trans_id=str(trans_id),
                                    subscr_id=subscr_id,
                                    status="unclaimed",
                                    payer_email=payer_email,
                                    paying_id=paying_id,
                                    pennies=pennies,
                                    days=days,
                                    secret=str(secret),
                                    date=date
                                    )
    except IntegrityError:
        rp = gold_table.update(
            sa.and_(gold_table.c.status == 'uncharged',
                    gold_table.c.trans_id == str(trans_id)),
            values = {
                gold_table.c.status: "unclaimed",
                gold_table.c.payer_email: payer_email,
                gold_table.c.paying_id: paying_id,
                gold_table.c.pennies: pennies,
                gold_table.c.days: days,
                gold_table.c.secret:secret,
                gold_table.c.subscr_id : subscr_id
                },
            ).execute()

# TODO: this should really live in emailer.py
def notify_unclaimed_gold(txn_id, gold_secret, payer_email, source):
    from r2.lib import emailer
    url = "http://www.reddit.com/thanks/" + gold_secret

    # No point in i18n, since we don't have access to the user's
    # language info (or name) at this point
    body = """
Thanks for subscribing to reddit gold! We have received your %s
transaction, number %s.

Your secret subscription code is %s. You can use it to associate this
subscription with your reddit account -- just visit
%s
""" % (source, txn_id, gold_secret, url)

    emailer.gold_email(body, payer_email, "reddit gold subscriptions")


def create_claimed_gold (trans_id, payer_email, paying_id,
                         pennies, days, secret, account_id, date,
                         subscr_id = None):
    gold_table.insert().execute(trans_id=trans_id,
                                subscr_id=subscr_id,
                                status="claimed",
                                payer_email=payer_email,
                                paying_id=paying_id,
                                pennies=pennies,
                                days=days,
                                secret=secret,
                                account_id=account_id,
                                date=date)

# returns None if the ID was never valid
# returns "already claimed" if it's already been claimed
# Otherwise, it's valid and the function claims it, returning a tuple with:
#   * the number of days
#   * the subscr_id, if any
def claim_gold(secret, account_id):
    if not secret:
        return None

    # The donation email has the code at the end of the sentence,
    # so they might get sloppy and catch the period or some whitespace.
    secret = secret.strip(". ")

    rp = gold_table.update(sa.and_(gold_table.c.status == 'unclaimed',
                                   gold_table.c.secret == secret),
                           values = {
                                      gold_table.c.status: 'claimed',
                                      gold_table.c.account_id: account_id,
                                    },
                           ).execute()
    if rp.rowcount == 0:
        just_claimed = False
    elif rp.rowcount == 1:
        just_claimed = True
    else:
        raise ValueError("rowcount == %d?" % rp.rowcount)

    s = sa.select([gold_table.c.days, gold_table.c.subscr_id],
                  gold_table.c.secret == secret,
                  limit = 1)
    rows = s.execute().fetchall()

    if not rows:
        return None
    elif just_claimed:
        return (rows[0].days, rows[0].subscr_id)
    else:
        return "already claimed"

def check_by_email(email):
    s = sa.select([gold_table.c.status,
                           gold_table.c.secret,
                           gold_table.c.days,
                           gold_table.c.account_id],
                          gold_table.c.payer_email == email)
    return s.execute().fetchall()

# google checkout specific code:
def new_google_transaction(trans_id):
    # transid is in three parts: the actual ID, an identifier, and the status
    key = trans_id.split('-')[0]
    g.log.error("inserting %s" % key)
    try:
        gold_table.insert().execute(trans_id="g" + str(key),
                                    subscr_id="",
                                    status="uncharged",
                                    payer_email="",
                                    paying_id="",
                                    pennies=0,
                                    days=0,
                                    secret=None,
                                    date=datetime.now(g.tz))
    except IntegrityError:
        # google guarantees that they will send us a bunch of these.  we only
        # need to store one to process the transaction
        g.log.error("transaction id already exists in table: %s" % key)


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


def process_google_transaction(trans_id):
    trans = _google_ordernum_request(trans_id)

    # get the financial details
    auth = trans.find("authorization-amount-notification")

    if not auth:
        # see if the payment was declinded
        status = trans.find('financial-order-state')
        if 'PAYMENT_DECLINED' in [x.contents[0] for x in status]:
            rp = gold_table.update(
                sa.and_(gold_table.c.status == 'uncharged',
                        gold_table.c.trans_id == str(trans_id)),
                values = { gold_table.c.status : "declined" }).execute()
        else:
            g.log.error("google transaction not found: '%s'" % trans_id)
    elif auth.find("financial-order-state").contents[0] == "CHARGEABLE":
        email = str(auth.find("email").contents[0])
        payer_id = str(auth.find('buyer-id').contents[0])
        days = None
        try:
            pennies = int(float(auth.find("order-total").contents[0])*100)
            if pennies == 2999:
                secret = "ys_"
                days = 366
            elif pennies == 399:
                secret = "m_"
                days = 31
            else:
                g.log.error("Got %d pennies via Google?" % pennies)
                return
        except ValueError:
            g.log.error("no amount in google checkout for transid %s"
                     % trans_id)
            return

        secret += randstr(10)

        # no point charging twice.  If we are in this func, the db doesn't
        # know it was already charged so we still have to update and email
        charged = trans.find("charge-amount-notification")
        if not charged:
            _google_charge_and_ship(trans_id)

        create_unclaimed_gold("g" + str(trans_id),
                              email, payer_id, pennies, days, str(secret),
                              datetime.now(g.tz))

        notify_unclaimed_gold(trans_id, secret, email, "Google")


def process_uncharged():
    s = sa.select([gold_table.c.trans_id],
                 gold_table.c.status == 'uncharged')
    res = s.execute().fetchall()

    for trans_id, in res:
        if trans_id.startswith('g'):
            trans_id = trans_id[1:]
            process_google_transaction(trans_id)
