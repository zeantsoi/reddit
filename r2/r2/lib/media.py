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

import base64
import contextlib
import cStringIO
import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
import traceback
import urllib
import urlparse

import BeautifulSoup
from advocate import AddrValidator, RequestsAPIWrapper
from PIL import Image, ImageFile
from time import sleep
import lxml.html

from pylons import app_globals as g
from pylons import tmpl_context as c

from r2.config import feature
from r2.lib import (
    amqp,
    hooks,
    s3_helpers,
    websockets,
)
from r2.lib.db import queries
from r2.lib.db.thing import NotFound
from r2.lib.memoize import memoize
from r2.lib.nymph import optimize_png
from r2.lib.providers.cdn.cloudflare import CloudFlareCdnProvider
from r2.lib.template_helpers import add_sr, format_html
from r2.lib.utils import (
    TimeoutFunction,
    TimeoutFunctionException,
    UrlParser,
    coerce_url_to_protocol,
    domain,
    extract_urls_from_markdown,
    is_subdomain,
    get_requests_resp_json,
    url_is_image,
)
from r2.models.link import Link
from r2.models.media_cache import (
    ERROR_MEDIA,
    Media,
    MediaByURL,
)
from r2.models import Account, Subreddit
from urllib2 import (
    HTTPError,
    URLError,
)

_IMAGE_PREVIEW_TEMPLATE = """
<img class="%(css_class)s" src="%(url)s" width="%(width)s" height="%(height)s">
"""

_MP4_PREVIEW_TEMPLATE = """
<video class="%(css_class)s"
    preload="auto" autoplay="autoplay" muted="muted" loop="loop"
    webkit-playsinline="" style="width: %(width)spx; height: %(height)spx;">
    <source src="%(url)s" type="video/mp4">
</video>
"""

_EMBEDLY_CARD_TEMPLATE = """
<a class="embedly-card" href="%(url)s"></a>
<script async src="//cdn.embedly.com/widgets/platform.js" charset="UTF-8"></script>
"""

advocate = RequestsAPIWrapper(AddrValidator(
    ip_whitelist=g.scraper_ip_whitelist,
))
SESSION = advocate.Session()


def _image_to_str(image):
    s = cStringIO.StringIO()
    image.save(s, image.format)
    return s.getvalue()


def str_to_image(s):
    s = cStringIO.StringIO(s)
    image = Image.open(s)
    return image


def _image_entropy(img):
    """calculate the entropy of an image"""
    hist = img.histogram()
    hist_size = sum(hist)
    hist = [float(h) / hist_size for h in hist]

    return -sum(p * math.log(p, 2) for p in hist if p != 0)


def _crop_image_vertically(img, target_height):
    """crop image vertically the the specified height. determine
    which pieces to cut off based on the entropy pieces."""
    x,y = img.size

    while y > target_height:
        #slice 10px at a time until square
        slice_height = min(y - target_height, 10)

        bottom = img.crop((0, y - slice_height, x, y))
        top = img.crop((0, 0, x, slice_height))

        #remove the slice with the least entropy
        if _image_entropy(bottom) < _image_entropy(top):
            img = img.crop((0, 0, x, y - slice_height))
        else:
            img = img.crop((0, slice_height, x, y))

        x,y = img.size

    return img


def _square_image(img):
    """if the image is taller than it is wide, square it off."""
    width = img.size[0]
    return _crop_image_vertically(img, width)


def _strip_exif_data(image, image_file):
    """Remove exif data by saving the image."""
    image_file.seek(0)
    image.save(image_file.name, optimize=True, format=image.format,
        icc_profile=image.info.get('icc_profile'))


def _get_exif_tags(image):
    """Return exif data, if it exists.

    If the exif data is corrupted, return False.
    If exif_tags don't exist return None.
    """
    try:
        exif_tags = image._getexif() or {}
    except AttributeError:
        # Image format with no EXIF tags
        return None
    except (IndexError, SyntaxError):
        # Bad EXIF data
        return False

    return exif_tags


def _apply_exif_orientation(image):
    """Update the image's orientation if it has the relevant EXIF tag."""
    exif_tags = _get_exif_tags(image)
    if not exif_tags:
        return image

    # constant from EXIF spec
    ORIENTATION_TAG_ID = 0x0112
    orientation = exif_tags.get(ORIENTATION_TAG_ID)

    if orientation == 1:
        # 1 = Horizontal (normal)
        pass
    elif orientation == 2:
        # 2 = Mirror horizontal
        image = image.transpose(Image.FLIP_LEFT_RIGHT)
    elif orientation == 3:
        # 3 = Rotate 180
        image = image.transpose(Image.ROTATE_180)
    elif orientation == 4:
        # 4 = Mirror vertical
        image = image.transpose(Image.FLIP_TOP_BOTTOM)
    elif orientation == 5:
        # 5 = Mirror horizontal and rotate 90 CCW
        image = image.transpose(Image.FLIP_LEFT_RIGHT)
        image = image.transpose(Image.ROTATE_90)
    elif orientation == 6:
        # 6 = Rotate 270 CCW
        image = image.transpose(Image.ROTATE_270)
    elif orientation == 7:
        # 7 = Mirror horizontal and rotate 270 CCW
        image = image.transpose(Image.FLIP_LEFT_RIGHT)
        image = image.transpose(Image.ROTATE_270)
    elif orientation == 8:
        # 8 = Rotate 90 CCW
        image = image.transpose(Image.ROTATE_90)

    return image


def _prepare_image(image):
    image = _apply_exif_orientation(image)

    image = _square_image(image)

    hidpi_dims = [int(d * g.thumbnail_hidpi_scaling) for d in g.thumbnail_size]

    # If the image width is smaller than hidpi requires, set to non-hidpi
    if image.size[0] < hidpi_dims[0]:
        thumbnail_size = g.thumbnail_size
    else:
        thumbnail_size = hidpi_dims

    image.thumbnail(thumbnail_size, Image.ANTIALIAS)
    return image


def _clean_url(url):
    """url quotes unicode data out of urls"""
    url = url.encode('utf8')
    url = ''.join(urllib.quote(c) if ord(c) >= 127 else c for c in url)
    return url


def _initialize_request(url, referer, gzip=False):
    url = _clean_url(url)

    if not url.startswith(("http://", "https://")):
        return

    req = advocate.Request("GET", url).prepare()
    if gzip:
        req.headers["Accept-Encoding"] = "gzip"
    if g.useragent:
        req.headers["User-Agent"] = g.useragent
    if referer:
        req.headers["Referer"] = referer
    return req


def _fetch_url(url, referer=None):
    request = _initialize_request(url, referer=referer, gzip=True)
    if not request:
        return None, None

    response = SESSION.send(request)
    response.raise_for_status()
    return response.headers.get("Content-Type"), response.content


@contextlib.contextmanager
def _request_image(url, timeout, referer=None):
    url = _clean_url(url)
    res = None
    p = UrlParser(url)
    if not (p.is_web_safe_url() and p.scheme.startswith("http")):
        yield None
        return

    try:
        headers = dict()
        if g.useragent:
            headers["User-Agent"] = g.useragent
        if referer:
            headers["Referer"] = referer

        res = advocate.get(
            url,
            timeout=timeout,
            stream=True,
            headers=headers,
        )
        yield res
    finally:
        if res:
            res.close()


def _fetch_image_url(url, timeout, max_image_size, max_gif_size, referer=None):
    _error_response = None, None

    with _request_image(url, timeout, referer=referer) as res:
        if not res:
            return _error_response

        content_type = res.headers.get("Content-Type", "").lower()
        if not content_type.startswith("image/"):
            return _error_response

        if content_type == "image/gif":
            max_size = max_gif_size
        else:
            max_size = max_image_size

        try:
            expressed_size = int(res.headers.get('Content-Length', 0))
            if expressed_size > max_size:
                return _error_response
        except ValueError:
            pass

        content = []
        content_size = 0
        for chunk in res.iter_content(4096):
            content.append(chunk)
            content_size += len(chunk)
            if content_size > max_size:
                return _error_response
        content = "".join(content)
        return content_type, content


@memoize('media.fetch_size', time=3600)
def _fetch_image_size(url, referer):
    """Return the size of an image by URL downloading as little as possible."""

    request = _initialize_request(url, referer)
    if not request:
        return None

    parser = ImageFile.Parser()
    response = None
    try:
        response = SESSION.send(request, stream=True)
        response.raise_for_status()

        while True:
            chunk = response.raw.read(1024)
            if not chunk:
                break

            parser.feed(chunk)
            if parser.image:
                return parser.image.size
    except advocate.RequestException:
        return None
    finally:
        if response:
            response.close()


def optimize_jpeg(filename):
    with open(os.path.devnull, 'w') as devnull:
        subprocess.check_call(("/usr/bin/jpegoptim", filename), stdout=devnull)

def optimize_gif(filename):
    with open(os.path.devnull, 'w') as devnull:
        args = ("/usr/bin/gifsicle",
                "--no-comments",
                "--no-names",
                "--batch",
                filename)
        subprocess.check_call(args, stdout=devnull)

def thumbnail_url(link):
    """Given a link, returns the url for its thumbnail based on its fullname"""
    if link.has_thumbnail:
        if hasattr(link, "thumbnail_url"):
            return link.thumbnail_url
        else:
            return ''
    else:
        return ''


def mobile_ad_url(link):
    """Given a link, returns the url for its mobile card based on its fullname"""
    if link.has_thumbnail:
        if hasattr(link, "mobile_ad_url"):
            return link.mobile_ad_url
        else:
            return ''
    else:
        return ''


def _filename_from_content(contents, image_key=None):
    """Generate the filename based on the contents.

    If an image upload, hash on the image_key to separate the
    preview and thumbnail objects in case they get crossposted,
    so they can all be deleted when the original image upload is
    deleted, but leave the other versions of the image intact.
    """
    hash_bytes = hashlib.sha256(contents)
    if image_key:
        hash_bytes.update(image_key)
    hash_bytes = hash_bytes.digest()
    return base64.urlsafe_b64encode(hash_bytes).rstrip("=")


def _flatten_alpha(img):
    """Given an image, flatten alpha channels."""
    if img.format == "JPG":
        return img

    # convert to rgba because PIL doesn't handle non-rgba in paste
    rgba_img = img.convert("RGBA")

    # paste into white background because PIL defaults to a black
    background = Image.new('RGBA', img.size, (255, 255, 255))
    background.paste(rgba_img, rgba_img)
    return background.convert('RGB')


def upload_media(image, file_type='jpg', category='thumbs',
        filename_hash=None):
    """Upload an image to the media provider."""
    f = tempfile.NamedTemporaryFile(suffix=".{}".format(file_type), delete=True)
    try:
        img = image
        do_convert = True
        if isinstance(img, basestring):
            img = str_to_image(img)
            img_format = img.format.lower()
            if img_format == file_type and img_format in ("png", "gif"):
                img.verify()
                f.write(image)
                do_convert = False

        if do_convert:
            # if the requested type was jpg, convert and flatten alpha chanels
            # before saving
            if file_type == "jpg":
                img = _flatten_alpha(img)
                img.save(f, quality=85)
            else:
                img.save(f)

        f.seek(0)
        if file_type == "png":
            optimize_level = 0 if category == 'previews' else 2
            optimize_png(f.name, optimize_level=optimize_level)
        elif file_type == "jpg":
            optimize_jpeg(f.name)
        if file_type == "gif":
            optimize_gif(f.name)
        contents = open(f.name).read()
        file_name = "{file_name}.{file_type}".format(
            file_name=_filename_from_content(contents, filename_hash),
            file_type=file_type,
        )
        return g.media_provider.put(category, file_name, contents)
    finally:
        f.close()
    return ""


def upload_media_raw(image_bytes, file_type='jpg', category='thumbs'):
    """Given an image, upload it, without alterations."""
    file_name = "{file_name}.{file_type}".format(
        file_name=_filename_from_content(image_bytes),
        file_type=file_type,
    )
    return g.media_provider.put(category, file_name, image_bytes)


def upload_stylesheet(content):
    file_name = _filename_from_content(content) + ".css"
    return g.media_provider.put('stylesheets', file_name, content)


def _scrape_media(url, autoplay=False, maxwidth=600, force=False,
                  save_thumbnail=True, use_cache=False, max_cache_age=None):
    media = None
    autoplay = bool(autoplay)
    maxwidth = int(maxwidth)

    # Use media from the cache (if available)
    if not force and use_cache:
        mediaByURL = MediaByURL.get(url,
                                    autoplay=autoplay,
                                    maxwidth=maxwidth,
                                    max_cache_age=max_cache_age)
        if mediaByURL:
            media = mediaByURL.media

    # Otherwise, scrape it if thumbnail is not present
    if not media or not media.thumbnail_url:
        media_object = secure_media_object = None
        thumbnail_image = thumbnail_url = thumbnail_size = None

        scraper = Scraper.for_url(url, autoplay=autoplay)
        try:
            thumbnail_image, preview_object, media_object, secure_media_object = (
                scraper.scrape())
        except (HTTPError, URLError) as e:
            if use_cache:
                MediaByURL.add_error(url, str(e),
                                     autoplay=autoplay,
                                     maxwidth=maxwidth)
            return None

        # the scraper should be able to make a media embed out of the
        # media object it just gave us. if not, null out the media object
        # to protect downstream code
        if media_object and not scraper.media_embed(media_object):
            print "%s made a bad media obj for url %s" % (scraper, url)
            media_object = None

        if (secure_media_object and
            not scraper.media_embed(secure_media_object)):
            print "%s made a bad secure media obj for url %s" % (scraper, url)
            secure_media_object = None

        # If thumbnail can't be found, attempt again using _HTMLParsingScraper
        # This should fix bugs that occur when embed.ly caches links before the 
        # thumbnail is available
        if (not thumbnail_image and 
                not isinstance(scraper, _HTMLParsingScraper)):
            scraper = _HTMLParsingScraper(url)
            try:
                thumbnail_image, preview_object, _, _ = scraper.scrape()
            except (HTTPError, URLError) as e:
                use_cache = False

        if thumbnail_image and save_thumbnail:
            thumbnail_size = thumbnail_image.size
            parsed_url = UrlParser(url)
            thumbnail_url = upload_media(thumbnail_image,
                filename_hash=parsed_url.path)
        else:
            # don't cache if thumbnail is absent
            use_cache = False

        media = Media(media_object, secure_media_object, preview_object,
                      thumbnail_url, thumbnail_size)

    if use_cache and save_thumbnail and media is not ERROR_MEDIA:
        # Store the media in the cache, possibly extending the ttl
        MediaByURL.add(url,
                       media,
                       autoplay=autoplay,
                       maxwidth=maxwidth)

    return media


def _get_scrape_url(link):
    if not link.is_self:
        p = UrlParser(link.url)
        # If it's a gifv link on imgur, replacing it with gif should give us
        # the _ImageScraper-friendly url, so we'll get native mp4 previews
        if is_subdomain(p.hostname, "imgur.com"):
            if p.path_extension().lower() == "gifv":
                p.set_extension("gif")
                return p.unparse()
        return link.url

    urls = extract_urls_from_markdown(link.selftext)
    second_choice = None
    for url in urls:
        p = UrlParser(url)
        if p.is_reddit_url():
            continue
        # If we don't find anything we like better, use the first image.
        if not second_choice:
            second_choice = url
        # This is an optimization for "proof images" in AMAs.
        if is_subdomain(p.netloc, 'imgur.com') or p.has_image_extension():
            return url

    return second_choice


def set_media(link, force=False, **kwargs):
    sr = link.subreddit_slow
    
    # Do not process thumbnails for quarantined subreddits
    if sr.quarantine:
        return

    if not link.is_self:
        if not force and (link.has_thumbnail or link.media_object):
            return

    if not force and link.promoted:
        return

    scrape_url = _get_scrape_url(link)

    if not scrape_url:
        if link.preview_object:
            # If the user edited out an image from a self post, we need to make
            # sure to remove its metadata.
            link.set_preview_object(None)
            link._commit()
        return

    media = _scrape_media(scrape_url, force=force, **kwargs)

    if media and not link.promoted:
        # While we want to add preview images to self posts for the new apps,
        # let's not muck about with the old-style thumbnails in case that
        # breaks assumptions.
        if not link.is_self:
            link.thumbnail_url = media.thumbnail_url
            link.thumbnail_size = media.thumbnail_size

            link.set_media_object(media.media_object)
            link.set_secure_media_object(media.secure_media_object)
        link.set_preview_object(media.preview_object)

        link._commit()

        hooks.get_hook("scraper.set_media").call(link=link)

        amqp.add_item("new_media", link._fullname)

        if media.media_object or media.secure_media_object:
            amqp.add_item("new_media_embed", link._fullname)


def force_thumbnail(link, image_data, file_type="jpg"):
    image = str_to_image(image_data)
    image = _prepare_image(image)
    thumb_url = upload_media(image, file_type=file_type)

    link.thumbnail_url = thumb_url
    link.thumbnail_size = image.size
    link._commit()


def force_mobile_ad_image(link, image_data, file_type="jpg"):
    image = str_to_image(image_data)
    image_width = image.size[0]
    x,y = g.mobile_ad_image_size
    max_height = image_width * y / x
    image = _crop_image_vertically(image, max_height)
    image.thumbnail(g.mobile_ad_image_size, Image.ANTIALIAS)
    image_url = upload_media(image, file_type=file_type)

    link.mobile_ad_url = image_url
    link.mobile_ad_size = image.size
    link._commit()


def make_temp_uploaded_image_permanent(image_key):
    """Move the image to the permanent bucket.

    The temp image is converted into an image to determine
    the image format. If the image has exif data, the image
    has the exif orientation applied and then strips the
    exif data. The image is then uploaded to the permanent
    bucket and returns the new image url.

    In a try/finally block so that the file is always deleted.
    """
    try:
        key_name = image_key.name
        data = {
            "successful": False,
            "key_name": key_name,
            "mimetype": image_key.content_type,
            "size": image_key.size,
            "px_size": None,
            "image_url": None,
        }

        f = tempfile.NamedTemporaryFile(delete=True)
        image_key.get_contents_to_file(f)
        f.seek(0)
        image = Image.open(f.name)

        file_name = os.path.split(key_name)[1]
        file_type = image.format.lower().replace("jpeg", "jpg")
        full_filename = "%s.%s" % (file_name, file_type)
        data["mimetype"] = file_type

        if file_type not in ("jpg", "jpeg", "png", "gif"):
            return data

        exif_tags = _get_exif_tags(image)
        if exif_tags:
            # When saving the image again (after applying orientation),
            # the image format prop is lost.
            original_format = image.format
            # Strip exif data after applying orientation
            image = _apply_exif_orientation(image)
            image.format = original_format
            _strip_exif_data(image, f)
        elif exif_tags is False:
            # Getting exif data failed because of invalid format.
            _strip_exif_data(image, f)
        data["px_size"] = image.size

        f.seek(0)
        image_url = g.media_provider.put("images", full_filename, f)
        data["successful"] = bool(image_url)
        data["image_url"] = image_url
    except IOError:
        # Not an image file
        successful = False
    finally:
        f.close()

    return data


def upload_icon(image_data, size):
    image = str_to_image(image_data)
    image.format = 'PNG'
    image.thumbnail(size, Image.ANTIALIAS)
    icon_data = _image_to_str(image)
    file_name = _filename_from_content(icon_data)
    return g.media_provider.put('icons', file_name + ".png", icon_data)


def allowed_media_preview(url, preview_object):
    p = UrlParser(url)
    if p.has_image_extension():
        return True
    # anytime we have a preview image with a gif source, we want to show it
    elif preview_object.get('url', '').endswith('.gif'):
        return True
    for allowed_domain in g.media_preview_domain_whitelist:
        if is_subdomain(p.hostname, allowed_domain):
            return True

    # This can be reached from MinimalController where c.user is unset
    # so it needs to support c.user=''
    if ((not c.user or c.user.pref_media_preview != 'off') and
            feature.is_enabled('title_to_commentspage')):
        if url_is_image(url):
            return True

    return False


def get_preview_media_object(preview_object, include_censored=False):
    """Returns a media_object for rendering a media preview image"""
    min_width, min_height = g.preview_image_min_size
    max_width, max_height = g.preview_image_max_size
    source_width = preview_object['width']
    source_height = preview_object['height']

    if source_width <= max_width and source_height <= max_height:
        width = source_width
        height = source_height
    else:
        max_ratio = float(max_height) / max_width
        source_ratio = float(source_height) / source_width
        if source_ratio >= max_ratio:
            height = max_height
            width = int((height * source_width) / source_height)
        else:
            width = max_width
            height = int((width * source_height) / source_width)

    if width < min_width and height < min_height:
        return None

    is_gif = preview_object["url"].endswith('.gif')

    if not is_gif:
        static_url = g.image_resizing_provider.resize_image(preview_object, width)
        img_html = format_html(
            _IMAGE_PREVIEW_TEMPLATE,
            css_class="preview",
            url=static_url,
            width=width,
            height=height,
        )
    else:
        mp4_url = g.image_resizing_provider.resize_image(preview_object, width, file_type="mp4")
        img_html = format_html(
            _MP4_PREVIEW_TEMPLATE,
            css_class="preview",
            url=mp4_url,
            width=width,
            height=height,
        )

    if include_censored:
        censored_url = g.image_resizing_provider.resize_image(
            preview_object,
            width,
            censor_nsfw=True,
            file_type="png",
        )
        censored_img_html = format_html(
            _IMAGE_PREVIEW_TEMPLATE,
            css_class="censored-preview",
            url=censored_url,
            width=width,
            height=height,
        )
        img_html += censored_img_html

    media_object = {
        "type": "media-preview",
        "width": width,
        "height": height,
        "content": img_html,
    }

    return media_object


def get_embedly_card(url):
    html = format_html(
        _EMBEDLY_CARD_TEMPLATE,
        url=url,
    )
    return MediaEmbed(
        width=600,
        height=0,
        content=html,
        sandbox=True,
    )

def should_use_embedly_card(item):
    if (item.media_object or
            item.promoted or
            item.is_self or
            item.over_18 or
            (item.preview_object and
                allowed_media_preview(item.url, item.preview_object))
            ):
        return False
    return True


def _make_custom_media_embed(media_object):
    # this is for promoted links with custom media embeds.
    return MediaEmbed(
        height=media_object.get("height"),
        width=media_object.get("width"),
        content=media_object.get("content"),
    )


def get_media_embed(media_object):
    if not isinstance(media_object, dict):
        return

    embed_hook = hooks.get_hook("scraper.media_embed")
    media_embed = embed_hook.call_until_return(media_object=media_object)
    if media_embed:
        return media_embed

    if media_object.get("type") == "custom":
        return _make_custom_media_embed(media_object)

    # _GfycatScraper is not represented here because it does not generate
    # media_objects.  If a gfycat link has a media_object attached, it was
    # scraped with _EmbedlyScraper, which is handled below.

    if "oembed" in media_object:
        if media_object.get("type") == "youtube.com":
            return _YouTubeScraper.media_embed(media_object)

        return _EmbedlyScraper.media_embed(media_object)


class MediaEmbed(object):
    """A MediaEmbed holds data relevant for serving media for an object."""

    width = None
    height = None
    content = None
    scrolling = False

    def __init__(self, height, width, content, scrolling=False,
                 public_thumbnail_url=None, sandbox=True):
        """Build a MediaEmbed.

        :param height int - The height of the media embed, in pixels
        :param width int - The width of the media embed, in pixels
        :param content string - The content of the media embed - HTML.
        :param scrolling bool - Whether the media embed should scroll or not.
        :param public_thumbnail_url string - The URL of the most representative
            thumbnail for this media. This may be on an uncontrolled domain,
            and is not necessarily our own thumbs domain (and should not be
            served to browsers).
        :param sandbox bool - True if the content should be sandboxed
            in an iframe on the media domain.
        """

        self.height = int(height)
        self.width = int(width)
        self.content = content
        self.scrolling = scrolling
        self.public_thumbnail_url = public_thumbnail_url
        self.sandbox = sandbox


class Scraper(object):
    @classmethod
    def for_url(cls, url, autoplay=False, maxwidth=600):
        scraper = hooks.get_hook("scraper.factory").call_until_return(url=url)
        if scraper:
            return scraper

        if _ImageScraper.matches(url):
            return _ImageScraper(url)

        if _GfycatScraper.matches(url):
            s = _GfycatScraper(url)
            if s.media_url:
                return s

        if _GiphyScraper.matches(url):
            s = _GiphyScraper(url)
            if s.media_url:
                return s

        if _YouTubeScraper.matches(url):
            return _YouTubeScraper(url, maxwidth=maxwidth)

        if _EmbedlyScraper.matches(url):
            return _EmbedlyScraper(
                url,
                autoplay=autoplay,
                maxwidth=maxwidth,
            )

        return _HTMLParsingScraper(url)

    @classmethod
    def matches(cls, url):
        """Return true if this scraper should be used for the given URL"""
        raise NotImplementedError

    def scrape(self):
        # should return a 4-tuple of:
        #     thumbnail, preview_object, media_object, secure_media_obj
        raise NotImplementedError

    @classmethod
    def media_embed(cls, media_object):
        # should take a media object and return an appropriate MediaEmbed
        raise NotImplementedError


class _MediaScraper(Scraper):
    """A simplified scraper for creating static media previews.

    Preview images for gifs are converted to static images.
    """
    @classmethod
    def matches(cls, url):
        p = UrlParser(url)
        return p.has_image_extension()

    def fetch_media(self):
        """Request image data suitable for creating media previews."""
        content_type, content = _fetch_url(self.url)

        if content_type and "image" in content_type and content:
            return content

        return None

    def make_media_previews(self, content):
        """Returns a tuple of thumbnail, preview_object"""
        uid = _filename_from_content(content)
        image = str_to_image(content)
        storage_url = upload_media(image, category='previews')
        width, height = image.size
        preview_object = {
            'uid': uid,
            'url': storage_url,
            'width': width,
            'height': height,
        }
        thumbnail = _prepare_image(image)

        return thumbnail, preview_object

    def scrape(self):
        content = self.fetch_media()
        if not content:
            return None, None, None, None
        thumbnail, preview_object = self.make_media_previews(content)
        return thumbnail, preview_object, None, None

    @classmethod
    def media_embed(cls, media_object):
        return None


class _HTMLParsingScraper(_MediaScraper):
    """Suitable for scraping content from HTML documents.

    HTML documents are parsed and the best candidate URL for a preview image
    is then scraped. Direct links to images are also supported.
    """
    def __init__(self, url):
        self.url = url
        # Having the source document's protocol on hand makes it easier to deal
        # with protocol-relative urls we extract from it.
        self.protocol = UrlParser(url).scheme

    @classmethod
    def matches(self, url):
        return True

    def fetch_media(self):
        content_type, content = _fetch_url(self.url)

        # if it's an image, it's pretty easy to guess what we should thumbnail.
        if content_type and "image" in content_type and content:
            return content

        if content_type and "html" in content_type and content:
            thumbnail_url = self._find_thumbnail_url_from_html(content)
            if not thumbnail_url:
                return None

            # When isolated from the context of a webpage, protocol-relative
            # URLs are ambiguous, so let's absolutify them now.
            if thumbnail_url.startswith('//'):
                thumbnail_url = coerce_url_to_protocol(
                    thumbnail_url,
                    self.protocol,
                )

            _, content = _fetch_url(thumbnail_url, referer=self.url)
            return content

        return None

    def _extract_image_urls(self, soup):
        for img in soup.findAll("img", src=True):
            yield urlparse.urljoin(self.url, img["src"])

    def _find_thumbnail_url_from_html(self, content):
        """Find what we think is the best thumbnail image for a link."""
        soup = BeautifulSoup.BeautifulSoup(content)
        # Allow the content author to specify the thumbnail using the Open
        # Graph protocol: http://ogp.me/
        og_image = (soup.find('meta', property='og:image') or
                    soup.find('meta', attrs={'name': 'og:image'}))
        if og_image and og_image.get('content'):
            return og_image['content']
        og_image = (soup.find('meta', property='og:image:url') or
                    soup.find('meta', attrs={'name': 'og:image:url'}))
        if og_image and og_image.get('content'):
            return og_image['content']

        # <link rel="image_src" href="http://...">
        thumbnail_spec = soup.find('link', rel='image_src')
        if thumbnail_spec and thumbnail_spec['href']:
            return thumbnail_spec['href']

        # ok, we have no guidance from the author. look for the largest
        # image on the page with a few caveats. (see below)
        max_area = 0
        max_url = None
        for image_url in self._extract_image_urls(soup):
            # When isolated from the context of a webpage, protocol-relative
            # URLs are ambiguous, so let's absolutify them now.
            if image_url.startswith('//'):
                image_url = coerce_url_to_protocol(image_url, self.protocol)
            size = _fetch_image_size(image_url, referer=self.url)
            if not size:
                continue

            area = size[0] * size[1]

            # ignore little images
            if area < 5000:
                g.log.debug('ignore little %s' % image_url)
                continue

            # ignore excessively long/wide images
            if max(size) / min(size) > 1.5:
                g.log.debug('ignore dimensions %s' % image_url)
                continue

            # penalize images with "sprite" in their name
            if 'sprite' in image_url.lower():
                g.log.debug('penalizing sprite %s' % image_url)
                area /= 10

            if area > max_area:
                max_area = area
                max_url = image_url

        return max_url


class _ImageScraper(_MediaScraper):
    """Given a URL that looks like an image, scrape it directly.

    Previews for gifs are preserved as gifs.
    """
    FETCH_TIMEOUT = 10
    MAXIMUM_IMAGE_SIZE = 1024 * 1024 * 20 # 20MB
    MAXIMUM_GIF_SIZE = 1024 * 1024 * 100 # 100MB

    def __init__(self, url):
        self.url = url

    @property
    def media_url(self):
        return self.url

    def fetch_media(self):
        content_type, content = _fetch_image_url(
            self.media_url,
            timeout=self.FETCH_TIMEOUT,
            max_image_size=self.MAXIMUM_IMAGE_SIZE,
            max_gif_size=self.MAXIMUM_GIF_SIZE,
            referer=self.media_url,
        )
        return content

    def make_media_previews(self, content):
        filename_hash = None
        # If this is scraping an image upload, use the s3 key as part of
        # the hash for thumbnails and previews. This associates all of the
        # thumbnails and previews with this one s3 key so they can be 
        # deleted together when the original image has been deleted, rather
        # than deleting all previews and thumbnails for any link to this
        # specific image (whether on another site or not) since it's
        # hashed on content.
        parsed_url = UrlParser(self.url)
        if parsed_url.hostname in (g.image_hosting_domain, g.gif_hosting_domain):
            filename_hash = parsed_url.path
        uid = _filename_from_content(content, filename_hash)
        image = str_to_image(content)
        file_type = image.format.lower()
        upload_input = image

        if file_type == "gif":
            # PIL does not support writing gifs, so we instead use it solely to
            # read and verify the GIF spec and pass in the content raw.
            # upload_media sanitizes all images via external optimizers
            upload_input = content
        elif file_type not in ("png", "jpg"):
            file_type = "jpg"

        storage_url = upload_media(
            upload_input,
            file_type=file_type,
            category='previews',
            filename_hash=filename_hash,
        )

        width, height = image.size
        preview_object = {
            'uid': uid,
            'url': storage_url,
            'width': width,
            'height': height,
        }
        thumbnail = _prepare_image(image)

        return thumbnail, preview_object


class _GifHostScraper(_ImageScraper):
    """Scraper for 3rd party gif hosting sites"""
    @classmethod
    def matches(cls, url):
        p = UrlParser(url)
        return is_subdomain(p.hostname, cls.HOSTNAME)

    def scrape(self):
        if not self.media_url:
            return None, None, None, None
        return super(_GifHostScraper, self).scrape()

    @property
    def media_url(self):
        if not hasattr(self, "_gif_url"):
            self._gif_url = self._get_gif_url()
        return self._gif_url

    def _get_gif_url(self):
        raise NotImplementedError


class _GfycatScraper(_GifHostScraper):
    """Use gfycat's api to get embed information.

    https://gfycat.com/api
    """
    HOSTNAME = "gfycat.com"
    GFYCAT_API_URL = "https://gfycat.com/cajax/get/"

    def _get_gif_url(self):
        p = UrlParser(self.url)
        gfy_name = p.path.strip("/")

        if "/" in gfy_name:
            return None

        with g.stats.get_timer("providers.gfycat.api"):
            content = advocate.get(self.GFYCAT_API_URL + gfy_name).content

        try:
            res = json.loads(content)
            gfy_item = res["gfyItem"]
            gif_url = gfy_item["gifUrl"]
            gif_size = int(gfy_item["gifSize"])

            if gif_size > self.MAXIMUM_GIF_SIZE:
                return None
            else:
                return gif_url
        except (ValueError, KeyError, TypeError):
            return None


class _GiphyScraper(_GifHostScraper):
    HOSTNAME = "giphy.com"
    GIPHY_MEDIA_URL_TEMPLATE = "https://media.giphy.com/media/{}/giphy.gif"

    def _get_gif_url(self):
        # example giphy url
        # http://giphy.com/gifs/excited-realms-con-the-life-of-un-cdi5XykCOXl8Q
        # example gif url
        # https://media.giphy.com/media/cdi5XykCOXl8Q/giphy.gif
        p = UrlParser(self.url)
        giphy_id = p.path.strip('/').split('-')[-1]
        if giphy_id:
            return self.GIPHY_MEDIA_URL_TEMPLATE.format(giphy_id)


class _OEmbedScraper(_MediaScraper):
    """A generic oEmbed based scraper."""
    allowed_oembed_types = {"video"}

    def __init__(self, url, maxwidth, media_object_type=None):
        self.url = url
        self.maxwidth = int(maxwidth)
        self.oembed_params = {
            "url": self.url,
            "format": "json",
            "maxwidth": self.maxwidth,
        }
        self.media_object_type = media_object_type or domain(url)

    @classmethod
    def matches(cls, url):
        return False

    def fetch_oembed(self, oembed_api_url):
        """Request oembed data"""
        resp = advocate.get(oembed_api_url, params=self.oembed_params)
        oembed = None
        try:
            oembed = json.loads(resp.content)
        except ValueError:
            g.log.error("No JSON object for content of: {0}".format(self.url))
        return oembed

    @property
    def oembed(self):
        if not hasattr(self, "_oembed"):
            self._oembed = self.fetch_oembed()
        return self._oembed

    def make_media_object(self, oembed):
        if oembed.get("type") in self.allowed_oembed_types:
            return {
                "type": self.media_object_type,
                "oembed": oembed,
            }
        return None

    def fetch_media(self):
        if not self.oembed:
            return None
        thumbnail_url = self.oembed.get("thumbnail_url")
        _, content = _fetch_url(thumbnail_url, referer=self.url)
        return content

    def scrape(self):
        if not self.oembed:
            return None, None, None, None
        thumbnail, preview_object, _, _ = super(_OEmbedScraper, self).scrape()
        if not thumbnail:
            return None, None, None, None
        media_object = self.make_media_object(self.oembed)
        return thumbnail, preview_object, media_object, media_object

    @classmethod
    def media_embed(cls, media_object):
        oembed = media_object["oembed"]

        html = oembed.get("html")
        width = oembed.get("width")
        height = oembed.get("height")
        public_thumbnail_url = oembed.get('thumbnail_url')

        if not (html and width and height):
            return

        return MediaEmbed(
            width=width,
            height=height,
            content=html,
            public_thumbnail_url=public_thumbnail_url,
        )


class _EmbedlyScraper(_OEmbedScraper):
    """Use Embedly to get information about embed info for a url.

    http://embed.ly/docs/api/embed/endpoints/1/oembed
    """
    OEMBED_ENDPOINT = "https://api.embed.ly/1/oembed"

    allowed_oembed_types = {"video", "rich"}

    def __init__(self, url, autoplay=False, maxwidth=600):
        super(_EmbedlyScraper, self).__init__(
            url,
            maxwidth=maxwidth,
        )
        self.oembed_params["key"] = g.embedly_api_key
        if autoplay:
            self.oembed_params["autoplay"] = "true"

    @classmethod
    def matches(cls, url):
        embedly_services = cls._fetch_embedly_services()
        for service_re in embedly_services:
            if service_re.match(url):
                return True
        return False

    def fetch_oembed(self, secure=False):
        self.oembed_params.update({
            "secure": "true" if secure else "false",
        })

        with g.stats.get_timer("providers.embedly.oembed"):
            return super(_EmbedlyScraper, self).fetch_oembed(
                self.OEMBED_ENDPOINT
            )

    def fetch_media(self):
        oembed = self.oembed
        if not oembed:
            return None

        if oembed.get("type") == "photo":
            thumbnail_url = oembed.get("url")
        else:
            thumbnail_url = oembed.get("thumbnail_url")

        if not thumbnail_url:
            return None

        if (oembed.get('provider_name') == "Imgur" and
                "i.imgur" not in self.url):
            temp_url = UrlParser(thumbnail_url)
            if temp_url.query_dict.get('fb') is not None:
                del temp_url.query_dict['fb']
                thumbnail_url = temp_url.unparse()

        _, content = _fetch_url(thumbnail_url, referer=self.url)
        return content

    def scrape(self):
        scrape_results = super(_EmbedlyScraper, self).scrape()
        thumbnail, preview_object, media_object, _ = scrape_results

        if not thumbnail:
            return None, None, None, None

        secure_oembed = self.fetch_oembed(secure=True)
        if not self.validate_secure_oembed(secure_oembed):
            secure_oembed = {}

        return (
            thumbnail,
            preview_object,
            media_object,
            self.make_media_object(secure_oembed),
        )

    def validate_secure_oembed(self, oembed):
        """Check the "secure" embed is safe to embed, and not a placeholder"""
        if not oembed.get("html"):
            return False

        # Get the embed.ly iframe's src
        iframe_src = lxml.html.fromstring(oembed['html']).get('src')
        if not iframe_src:
            return False
        iframe_src_url = UrlParser(iframe_src)

        # Per embed.ly support: If the URL for the provider is HTTP, we're
        # gonna get a placeholder image instead
        provider_src_url = UrlParser(iframe_src_url.query_dict.get('src'))
        return (
            not provider_src_url.scheme or
            provider_src_url.scheme == "https"
        )

    @classmethod
    @memoize("media.embedly_services2", time=3600)
    def _fetch_embedly_service_data(cls):
        resp = advocate.get("https://api.embed.ly/1/services/python")
        return get_requests_resp_json(resp)

    @classmethod
    def _fetch_embedly_services(cls):
        if not g.embedly_api_key:
            if g.debug:
                g.log.info("No embedly_api_key, using no key while in debug mode.")
            else:
                g.log.warning("No embedly_api_key configured. Will not use "
                              "embed.ly.")
                return []

        service_data = cls._fetch_embedly_service_data()

        return [
            re.compile("(?:%s)" % "|".join(service["regex"]))
            for service in service_data
        ]


class _YouTubeScraper(_OEmbedScraper):
    """Use YouTube's oembed API to get video embeds directly."""
    OEMBED_ENDPOINT = "https://www.youtube.com/oembed"
    URL_MATCH = re.compile(r"https?://((www\.)?youtube\.com/watch|youtu\.be/)")

    def __init__(self, url, maxwidth):
        super(_YouTubeScraper, self).__init__(
            url,
            maxwidth=maxwidth,
            media_object_type="youtube.com",
        )

    @classmethod
    def matches(cls, url):
        return cls.URL_MATCH.match(url)

    def fetch_oembed(self):
        with g.stats.get_timer("providers.youtube.oembed"):
            return super(_YouTubeScraper, self).fetch_oembed(
                    self.OEMBED_ENDPOINT
                )


def run():
    @g.stats.amqp_processor('scraper_q')
    def process_link(msg):
        fname = msg.body
        link = Link._by_fullname(fname, data=True)

        try:
            TimeoutFunction(set_media, 30)(link, use_cache=True)
        except TimeoutFunctionException:
            print "Timed out on %s" % fname
        except KeyboardInterrupt:
            raise
        except:
            print "Error fetching %s" % fname
            print traceback.format_exc()

    amqp.consume_items('scraper_q', process_link)


def process_image_upload():
    """
    Process images in image_upload_q for image hosting.

    Move images to the permanent bucket and strip exif data.
    Create the link with the new image url and then fetch the
    thumbnail and preview images. Websockets broadcast either
    the failure of link creation or redirect to the submitted
    image url.
    """
    @g.stats.amqp_processor('image_upload_q')
    def process_image(msg):
        msg_dict = json.loads(msg.body)
        s3_image_key = s3_helpers.get_key(
            g.s3_image_uploads_bucket,
            key=msg_dict["s3_key"],
        )

        # Move to the permanent bucket and rewrite
        # the url to the new image url
        try:
            data = TimeoutFunction(
                make_temp_uploaded_image_permanent, 60)(s3_image_key)
        except TimeoutFunctionException:
            print "Timed out on %s" % s3_image_key.name
            return
        except KeyboardInterrupt:
            raise

        # Make the image in the temp bucket inaccessible
        g.media_provider.make_inaccessible(key=s3_image_key)

        image_url = data["image_url"]
        g.events.image_upload_event(
            successful=data["successful"],
            key_name=data["key_name"],
            mimetype=data["mimetype"],
            size=data["size"],
            px_size=data["px_size"],
            url=image_url,
            context_data=msg_dict["context_data"],
        )

        # Most likely failed because bad file type,
        # so don't create the link
        if not image_url:
            websockets.send_broadcast(
                namespace=msg_dict["s3_key"],
                type="failed",
                payload={},
            )
            return

        sr = Subreddit._byID36(msg_dict["sr_id36"])
        # If this link has already been submitted, redirect the
        # user to this link rather than creating a new Link.
        # Can't check if the link exists before this point since
        # the final file extension isn't known until PIL reads the
        # image, so the final url hasn't been determined.
        try:
            existing_link = Link._by_url(image_url, sr)
        except NotFound:
            existing_link = []

        if existing_link:
            url = add_sr(existing_link[0].make_permalink_slow())
            websockets.send_broadcast(
                namespace=msg_dict["s3_key"],
                type="already_created",
                payload={
                    "redirect": url,
                },
            )

            return

        l = Link._submit(
            is_self=False,
            title=msg_dict["title"],
            content=image_url,
            author=Account._byID36(msg_dict["author_id36"]),
            sr=sr,
            ip=msg_dict["ip"],
            sendreplies=msg_dict["sendreplies"],
            image_upload=True,
        )
        g.events.submit_event(l, context_data=msg_dict["context_data"])

        # Update listings to include this new link
        queries.new_link(l)
        l.update_search_index()

        # Generate thumbnails and preview objects for image uploads
        try:
            TimeoutFunction(set_media, 30)(l, use_cache=True)
        except TimeoutFunctionException:
            print "Timed out on %s" % l._fullname
        except KeyboardInterrupt:
            raise

        websockets.send_broadcast(
            namespace=msg_dict["s3_key"],
            type="success",
            payload={
                "redirect": add_sr(l.make_permalink_slow()),
            },
        )

    amqp.consume_items('image_upload_q', process_image)


def purge_imgix_images(preview_object, purge_nsfw=False, notify_failures=True):
    """Purge the image from imgix and copies on the CDN.

    This is quite ugly overall but seems to be necessary since the CDN
    gets a copy of each size of the image.
    """
    preview_is_gif = preview_object.get('url', '').endswith('.gif')

    # First, purge the desktop preview url from imgix and cdn
    static_preview_url = g.image_resizing_provider.resize_image(
            preview_object, preview_object['width'])
    purge_image(static_preview_url, notify_failures=notify_failures)

    # Second, purge all permutations of the image available through the API
    _purge_preview_links(preview_object)
    if preview_is_gif:
        _purge_preview_links(preview_object, file_type="jpg")
        _purge_preview_links(preview_object, file_type="mp4")
    if purge_nsfw:
        _purge_preview_links(preview_object, censor_nsfw=True, file_type="png")


def _purge_preview_links(preview_object, censor_nsfw=False, file_type=None):
    from r2.lib.jsontemplates import generate_image_links

    # get the nested dict that contains all the urls that we need to purge
    template_dict = generate_image_links(
        preview_object=preview_object,
        censor_nsfw=censor_nsfw,
        file_type=file_type,
    )

    # extract all the urls from that dict
    base_url = template_dict["source"]["url"]
    urls = [base_url]
    for resolution in template_dict["resolutions"]:
        urls.append(resolution["url"])

    # purge the base url and all resized versions from the CDN
    for url in urls:
        purge_from_cdn(url, verify=False)


def purge_from_cdn(url, verify=True, max_retries=10, pause=3,
        notify_failures=True):
    """Purge the url from the CDN.

    Supports optional verification/retrying due to inconsistency.
    If the purging still can't be verified despite all the retries,
    a notification will be sent to the #takedown-tool channel.
    """

    # transition: images might be on Fastly or CloudFlare
    parsed_url = UrlParser(url)
    if parsed_url.hostname in (g.image_hosting_domain, g.imgix_gif_domain):
        purge_content_function = g.cdn_provider.purge_content
    else:
        purge_content_function = CloudFlareCdnProvider().purge_content

    purge_content_function(url)

    if not verify:
        return

    try_count = 1
    while try_count <= max_retries:
        sleep(pause)
        response = advocate.head(url)

        if response.status_code in (401, 403, 404):
            return

        # the purge didn't take effect, try again
        purge_content_function(url)
        try_count += 1

    if notify_failures:
        hooks.get_hook("cdn_purge.failed").call(url=url)


def purge_image(url, notify_failures=True):
    parsed_url = UrlParser(url)

    # imgix hosted image (previews)
    if parsed_url.hostname == g.imgix_domain:
        # convert the url back to the one used for the image on S3
        s3_url = "http://{bucket}{path}".format(
            bucket=g.s3_image_buckets[0],
            path=parsed_url.path,
        )
        g.media_provider.make_inaccessible(s3_url)
        g.image_resizing_provider.purge_url(url)

    # imgix hosted gif (previews)
    elif parsed_url.hostname == g.imgix_gif_domain:
        # convert the url back to the one used for the image on S3
        s3_url = "http://{bucket}{path}".format(
            bucket=g.s3_image_buckets[0],
            path=parsed_url.path,
        )
        g.media_provider.make_inaccessible(s3_url)
        g.image_resizing_provider.purge_url(url)

    # uploaded image (or gif) submitted as a link
    elif (parsed_url.hostname == g.image_hosting_domain or
            parsed_url.hostname == g.gif_hosting_domain):
        # convert the url back to the one used for the image on S3
        s3_url = "http://{bucket}{path}".format(
            bucket=g.s3_image_uploads_perm_bucket[0],
            path=parsed_url.path,
        )
        g.media_provider.make_inaccessible(s3_url)

    # s3 url of an image (thumbnails)
    else:
        g.media_provider.make_inaccessible(url)

    purge_from_cdn(url, notify_failures=notify_failures)


def purge_associated_images(link, notify_failures=True):
    thumbnail_url = getattr(link, 'thumbnail_url', None)
    preview_url = None
    has_preview = (
        getattr(link, 'preview_object', None)
        and link.preview_object.get('url')
    )

    if has_preview:
        preview_url = link.preview_object['url']

    if getattr(link, 'image_upload', False):
        purge_image(link.url, notify_failures=notify_failures)

    if thumbnail_url:
        purge_image(thumbnail_url, notify_failures=notify_failures)

    if preview_url:
        purge_imgix_images(link.preview_object, purge_nsfw=link.over_18,
            notify_failures=notify_failures)
