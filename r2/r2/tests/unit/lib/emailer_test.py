from pylons import app_globals as g
from r2.tests import RedditTestCase
from r2.lib.emailer import make_message_dict_unique
from r2.lib.providers.email.null import NullEmailProvider


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
