#!/usr/bin/env python
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

from r2.tests import stage_for_paste
stage_for_paste()

import unittest

from pylons import g

from r2.lib.providers.image_resizing import NotLargeEnough
from r2.lib.providers.image_resizing.imgix import ImgixImageResizingProvider
from r2.models.link import Image


class TestImgixResizer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.provider = ImgixImageResizingProvider()
        cls.old_imgix_domain = g.imgix_domain
        g.imgix_domain = 'example.com'

    @classmethod
    def tearDownClass(cls):
        g.imgix_domain = cls.old_imgix_domain

    def test_no_resize(self):
        image = Image(url='http://s3.amazonaws.com/a.jpg', width=1200,
                      height=800)
        url = self.provider.resize_image(image)
        self.assertEqual(url, 'http://example.com/a.jpg')

    def test_too_small(self):
        image = Image(url='http://s3.amazonaws.com/a.jpg', width=12,
                      height=8)
        with self.assertRaises(NotLargeEnough):
            self.provider.resize_image(image, 108)

    def test_resize(self):
        image = Image(url='http://s3.amazonaws.com/a.jpg', width=1200,
                      height=800)
        for width in (108, 216, 320, 640, 960, 1080):
            url = self.provider.resize_image(image, width)
            self.assertEqual(url, 'http://example.com/a.jpg?w=%d' % width)

        # TODO: test acceptable aspect ratios per spec!
