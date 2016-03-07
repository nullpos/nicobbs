#!/usr/bin/env python
# -*- coding: utf-8 -*-

import re
import xml.etree.ElementTree as ET

TWITTER_STATUS_MAX_LENGTH = 140
TCO_URL_LENGTH = 23

REGEXP_VIDEO = r'sm\d{3,}'
REGEXP_LIVE = r'lv\d{3,}'
REGEXP_SEIGA = r'im\d{3,}'
REGEXP_COMMUNITY = r'co\d{2,}'
REGEXP_MANGA = r'mg\d{3,}'
REGEXP_MYLIST = r'mylist\/\d{3,}'
BASE_URL_VIDEO = u'http://www.nicovideo.jp/watch/'
BASE_URL_LIVE = u'http://live.nicovideo.jp/watch/'
BASE_URL_SEIGA = u'http://seiga.nicovideo.jp/seiga/'
BASE_URL_COMMUNITY = u'http://com.nicovideo.jp/community/'
BASE_URL_MANGA = u'http://seiga.nicovideo.jp/watch/'
BASE_URL_MYLIST = u'http://www.nicovideo.jp/mylist/'

API_VIDEO_INFO = u'http://ext.nicovideo.jp/api/getthumbinfo/'
API_LIVE_INFO = u'http://live.nicovideo.jp/api/getplayerstatus/'

# regexp for...
# - http(s), http://www.megasoft.co.jp/mifes/seiki/s310.html
# - mail, http://bit.ly/1f2qKGZ
# - twitter account, http://stackoverflow.com/a/4424288
REGEXP_HTTP = r'https?://[\w/:%#\$&\?\(\)~\.=\+\-]+'
REGEXP_GOOGLE = r'goo.gl/[\w/:%#\$&\?\(\)~\.=\+\-]+'
REGEXP_MAIL = (
    r"[\w!#$%&'*+/=?^_{}\\|~-]+(?:\.[\w!#$%&'*+/=?^_{}\\|~-]+)*@(?:[\w][\w-]*\.)+[\w][\w-]*")
REGEXP_TWITTER = r'@[A-Za-z0-9_]{1,15}'

# replace twitter's @account with !account
ENABLE_MASKING_TWITTER = True
REGEXP_TWITTER_REPLACE_FROM = ur'[@＠]([A-Za-z0-9_]{1,15})'
REGEXP_TWITTER_REPLACE_TO = ur'%\1'

CHUNK_TYPE_UNKNOWN = 1
CHUNK_TYPE_TEXT = 2
CHUNK_TYPE_HTTP = 3
CHUNK_TYPE_MAIL = 4
CHUNK_TYPE_TWITTER = 5


# internal methods
def create_finalized_statuses(status_bodies, header, continued_mark, continue_mark):
    finalized_statuses = []
    status_bodies_count = len(status_bodies)

    header = re.sub(REGEXP_TWITTER_REPLACE_FROM, REGEXP_TWITTER_REPLACE_TO, header)

    index = 0
    for status_body in status_bodies:
        if ENABLE_MASKING_TWITTER:
            status_body = re.sub(
                REGEXP_TWITTER_REPLACE_FROM, REGEXP_TWITTER_REPLACE_TO, status_body)
        if status_bodies_count == 1:
            status = header + status_body
        else:
            if index == 0:
                status = header + status_body + continue_mark
            elif index < status_bodies_count - 1:
                status = header + continued_mark + status_body + continue_mark
            else:
                status = header + continued_mark + status_body
        finalized_statuses.append(status)
        index += 1

    return finalized_statuses


def replace_body(body):
    body = re.sub(r'>>(' + REGEXP_VIDEO + r')\n' + REGEXP_VIDEO,
                  BASE_URL_VIDEO + r'\1', body)
    body = re.sub(r'>>(' + REGEXP_LIVE + r')\n' + REGEXP_LIVE,
                  BASE_URL_LIVE + r'\1', body)
    body = re.sub(r'>>(' + REGEXP_SEIGA + r')\n' + REGEXP_SEIGA,
                  BASE_URL_SEIGA + r'\1', body)
    body = re.sub(r'>>(' + REGEXP_COMMUNITY + r')\n' + REGEXP_COMMUNITY,
                  BASE_URL_COMMUNITY + r'\1', body)
    body = re.sub(r'>>(' + REGEXP_MANGA + r')\n' + REGEXP_MANGA,
                  BASE_URL_MANGA + r'\1', body)
    body = re.sub(r'>>(' + REGEXP_MYLIST + r')\n' + REGEXP_MYLIST,
                  BASE_URL_MYLIST + r'\1', body)

    body = re.sub(r'\n+$', '', body)

    return body


def get_video_status(opener, video_id):
    url = API_VIDEO_INFO + video_id
    xml = ET.fromstring(opener.open(url).read())
    if xml.attrib.get('status') == 'fail':
        return BASE_URL_VIDEO + video_id
    thumb = xml.find('thumb')
    title = thumb.find('title').text
    name = thumb.find('user_nickname').text

    return ('[%s:%s]\n' + BASE_URL_VIDEO + '%s') % (title, name, video_id)


def get_live_status(opener, live_id):
    url = API_LIVE_INFO + live_id
    xml = ET.fromstring(opener.open(url).read())
    if xml.attrib.get('status') == 'fail':
        return BASE_URL_LIVE + live_id
    stream = xml.find('stream')
    title = stream.find('title').text
    name = stream.find('owner_name').text

    if name is None:
        return ('[%s]\n' + BASE_URL_LIVE + '%s') % (title, live_id)
    return ('[%s:%s]\n' + BASE_URL_LIVE + '%s') % (title, name, live_id)


def parse_video_info(opener, body):
    match = re.findall(BASE_URL_VIDEO + '([sn]m\d{3,})', body)
    for video_id in match:
        text = get_video_status(opener, video_id)
        body = re.sub(BASE_URL_VIDEO + video_id, text, body)
    return body


def parse_live_info(opener, body):
    match = re.findall(BASE_URL_LIVE + '(lv\d{3,})', body)
    for live_id in match:
        text = get_live_status(opener, live_id)
        body = re.sub(BASE_URL_LIVE + live_id, text, body)
    return body


# public methods
def create_twitter_statuses(header, continued_mark, body, continue_mark, opener=None):
    available_length = TWITTER_STATUS_MAX_LENGTH - len(header + continued_mark + continue_mark)
    # print available_length

    # print 'before replace: [' + body + ']'
    body = replace_body(body)
    # print 'after replace: [' + body + ']'
    if opener:
        body = parse_video_info(opener, body)
        body = parse_live_info(opener, body)

    statuses_with_body = []
    status_buffer = u""
    chunk_type = CHUNK_TYPE_UNKNOWN
    remaining_length = available_length

    regexp = u'(%s|%s|%s|%s)' % (REGEXP_HTTP, REGEXP_GOOGLE, REGEXP_MAIL, REGEXP_TWITTER)
    chunks = re.split(regexp, body)

    for chunk in chunks:
        # print u'chunk: [' + chunk + u']'
        # print u'remaining_length, pre-processed: %d' % remaining_length

        chunk_length = 0
        if re.match(REGEXP_HTTP, chunk) or re.match(REGEXP_GOOGLE, chunk):
            chunk_type = CHUNK_TYPE_HTTP
            chunk_length = TCO_URL_LENGTH
        elif re.match(REGEXP_MAIL, chunk):
            chunk_type = CHUNK_TYPE_MAIL
            chunk_length = len(chunk)
        elif re.match(REGEXP_TWITTER, chunk):
            chunk_type = CHUNK_TYPE_TWITTER
            chunk_length = len(chunk)
        else:
            chunk_type = CHUNK_TYPE_TEXT

        if chunk_type in [CHUNK_TYPE_HTTP, CHUNK_TYPE_MAIL, CHUNK_TYPE_TWITTER]:
            if chunk_length <= remaining_length:
                status_buffer += chunk
                remaining_length -= chunk_length
            else:
                statuses_with_body.append(status_buffer)
                status_buffer = chunk
                remaining_length = available_length - chunk_length
        elif chunk_type == CHUNK_TYPE_TEXT:
            while len(chunk):
                breaking_chunk = chunk[0:remaining_length]
                chunk = chunk[remaining_length:]

                status_buffer += breaking_chunk
                remaining_length -= len(breaking_chunk)

                if not remaining_length:
                    statuses_with_body.append(status_buffer)
                    status_buffer = u""
                    remaining_length = available_length
        # print u'remaining_length, post-processed: %d' % remaining_length

    if len(status_buffer):
        statuses_with_body.append(status_buffer)
        status_buffer = u""
        remaining_length = available_length

    return create_finalized_statuses(statuses_with_body, header, continued_mark, continue_mark)

if __name__ == "__main__":
    pass
