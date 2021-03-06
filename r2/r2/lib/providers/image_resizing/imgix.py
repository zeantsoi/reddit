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

from pylons import app_globals as g
import requests

from r2.lib.configparse import ConfigValue
from r2.lib.providers.image_resizing import (
    ImageResizingProvider,
    NotLargeEnough,
)
from r2.lib.utils import UrlParser, query_string

class ImgixImageResizingProvider(ImageResizingProvider):
    """A provider that uses imgix to create on-the-fly resizings."""
    config = {
        ConfigValue.bool: [
            'imgix_signing',
        ],

        ConfigValue.str: [
            'imgix_domain',
            'imgix_purge_domain',
            'imgix_gif_domain',
            'imgix_gif_purge_domain',
        ],
    }

    def resize_image(self, image, width=None, file_type=None, censor_nsfw=False,
                     max_ratio=None):
        url = UrlParser(image['url'])
        is_gif = url.path.endswith('.gif') and (file_type == 'mp4' or not file_type)

        if is_gif:
            url.hostname = g.imgix_gif_domain
        else:
            url.hostname = g.imgix_domain

        # Let's encourage HTTPS; it's cool, works just fine on HTTP pages, and
        # will prevent insecure content warnings on HTTPS pages.
        url.scheme = 'https'

        # g.s3_media_direct affects how preview image urls are stored
        # True: http://{s3_media_domain}/mybucket/helloworld.jpg
        # False: http://mybucket/helloworld.jpg
        # If it's True, we'll need to strip the bucket out of the path
        if g.s3_media_direct:
            path_parts = url.path.split('/')
            path_parts.pop(1)
            url.path = '/'.join(path_parts)

        if max_ratio:
            url.update_query(fit='crop')
            # http://www.imgix.com/docs/reference/size#param-crop
            url.update_query(crop='faces,entropy')
            url.update_query(arh=max_ratio)

        if width:
            if width > image['width']:
                raise NotLargeEnough()
            # http://www.imgix.com/docs/reference/size#param-w
            url.update_query(w=width)

        if file_type and file_type in ('gif', 'jpg', 'png', 'mp4'):
            url.update_query(fm=file_type)

        # We need to disable fragmented mp4s for proper playback in Firefox
        if file_type == 'mp4':
            url.update_query(**{'mp4-fragmented': 'false'})

        if censor_nsfw:
            # Do an initial blur to make sure we're getting rid of icky
            # details.
            #
            # http://www.imgix.com/docs/reference/stylize#param-blur
            url.update_query(blur=600)
            # And then add pixellation to help the image compress well.
            #
            # http://www.imgix.com/docs/reference/stylize#param-px
            url.update_query(px=32)
        if g.imgix_signing:
            if is_gif:
                url = self._sign_url(url, g.secrets['imgix_gif_signing_token'])
            else:
                url = self._sign_url(url, g.secrets['imgix_signing_token'])
        return url.unparse()

    def _sign_url(self, url, token):
        """Sign a url for imgix's secured sources.

        Based very heavily on the example code in the docs:
            http://www.imgix.com/docs/tutorials/securing-images

        Arguments:

        * url -- a UrlParser instance of the url to sign.  This object may be
                 modified by the function, so make a copy beforehand if that is
                 a concern.
        * token -- a string token provided by imgix for request signing

        Returns a UrlParser instance with signing parameters.
        """
        # Build the signing value
        signvalue = token + url.path
        if url.query_dict:
          signvalue += query_string(url.query_dict)

        # Calculate MD5 of the signing value.
        signature = hashlib.md5(signvalue).hexdigest()

        url.update_query(s=signature)
        return url

    def purge_url(self, url):
        """Purge an image (by url) from imgix.

        Reference: http://www.imgix.com/docs/tutorials/purging-images

        Note that as mentioned in the imgix docs, in order to remove
        an image, this function should be used *after* already
        removing the image from our source, or imgix will just re-fetch
        and replace the image with a new copy even after purging.
        """

        p = UrlParser(url)

        if p.hostname == g.imgix_domain:
            p.hostname = g.imgix_purge_domain
        elif p.hostname == g.imgix_gif_domain:
            p.hostname = g.imgix_gif_purge_domain

        url = p.unparse()

        requests.post(
            "https://api.imgix.com/v2/image/purger",
            auth=(g.secrets["imgix_api_key"], ""),
            data={"url": url},
        )
