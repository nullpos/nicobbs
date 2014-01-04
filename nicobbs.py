#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import logging
import logging.config
import ConfigParser
import urllib2
import cookielib
import re
import time
import json

import nicoutil
from bs4 import BeautifulSoup
import pymongo
import tweepy

LOGIN_URL = 'https://secure.nicovideo.jp/secure/login'
COMMUNITY_TOP_URL = 'http://com.nicovideo.jp/community/'
COMMUNITY_VIDEO_URL = 'http://com.nicovideo.jp/video/'
COMMUNITY_BBS_URL = 'http://com.nicovideo.jp/bbs/'
RESPONSE_URL = 'http://dic.nicovideo.jp/b/c/'
DATE_REGEXP = '.*(20../.+/.+\(.+\) .+:.+:.+).*'
RESID_REGEXP = 'ID: (.+)'
NICOBBS_CONFIG = os.path.dirname(os.path.abspath(__file__)) + '/nicobbs.config'
NICOBBS_CONFIG_SAMPLE = NICOBBS_CONFIG + '.sample'
CRAWL_INTERVAL = 30
TWEET_INTERVAL = 3

# responses/lives just crawled from the web
STATUS_UNPROCESSED = "UNPROCESSED"
# spam responses
STATUS_SPAM = "SPAM"
# duplicate status updates
STATUS_DUPLICATE = "DUPLICATE"
# responses/lives that are failed to be posted to twitter. currently not used
STATUS_FAILED = "FAILED"
# reponses/lives that are successfully posted to twitter
STATUS_COMPLETED = "COMPLETED"

LOG_SEPARATOR = "---------- ---------- ---------- ---------- ----------"


class TwitterStatusUpdateError(Exception):
# magic methods
    def __init__(self, message="", code=0):
        self.message = message
        self.code = code

    def __str__(self):
        return "status: [%s] code: [%d]" % (self.message, self.code)


class TwitterDuplicateStatusUpdateError(TwitterStatusUpdateError):
    pass


class TwitterOverUpdateLimitError(TwitterStatusUpdateError):
    pass


class NicoBBS(object):
# life cycle
    def __init__(self, is_test=False):
        config_file = NICOBBS_CONFIG
        if is_test:
            config_file = NICOBBS_CONFIG_SAMPLE

        logging.config.fileConfig(config_file)
        logging.debug("initialized logger w/ file %s" % config_file)

        self.mail, self.password, database_name, self.ng_words = (
            self.get_basic_config(config_file))
        logging.debug(
            "mail: %s password: xxxxxxxxxx database_name: %s ng_words: %s" %
            (self.mail, database_name, self.ng_words))

        self.target_communities = []
        self.consumer_key = {}
        self.consumer_secret = {}
        self.access_key = {}
        self.access_secret = {}

        for (community, consumer_key, consumer_secret, access_key,
                access_secret) in self.get_community_config(config_file):
            self.target_communities.append(community)
            self.consumer_key[self.target_communities[-1]] = consumer_key
            self.consumer_secret[self.target_communities[-1]] = consumer_secret
            self.access_key[self.target_communities[-1]] = access_key
            self.access_secret[self.target_communities[-1]] = access_secret

            logging.debug("*** community: " + self.target_communities[-1])
            logging.debug("consumer_key: %s consumer_secret: xxxxxxxxxx" %
                          self.consumer_key[self.target_communities[-1]])
            logging.debug("access_key: %s access_secret: xxxxxxxxxx" %
                          self.access_key[self.target_communities[-1]])

        self.connection = pymongo.Connection()
        self.database = self.connection[database_name]

    def __del__(self):
        self.connection.disconnect()

# utility
    def get_basic_config(self, config_file):
        config = ConfigParser.ConfigParser()
        config.read(config_file)
        section = "nicobbs"

        mail = config.get(section, "mail")
        password = config.get(section, "password")
        database_name = config.get(section, "database_name")
        ng_words = config.get(section, "ng_words")
        if ng_words == '':
            ng_words = []
        else:
            ng_words = ng_words.split(',')

        return mail, password, database_name, ng_words

    def get_community_config(self, config_file):
        result = []

        config = ConfigParser.ConfigParser()
        config.read(config_file)

        for section in config.sections():
            matched = re.match(r'community-(.+)', section)
            if matched:
                community = matched.group(1)
                consumer_key = config.get(section, "consumer_key")
                consumer_secret = config.get(section, "consumer_secret")
                access_key = config.get(section, "access_key")
                access_secret = config.get(section, "access_secret")
                result.append(
                    (community, consumer_key, consumer_secret, access_key, access_secret))

        return result

# twitter
    def update_twitter_status(self, community, status):
        auth = tweepy.OAuthHandler(self.consumer_key[community], self.consumer_secret[community])
        auth.set_access_token(self.access_key[community], self.access_secret[community])

        # for test; simulating post error like case of api limit
        # raise TwitterStatusUpdateError

        try:
            tweepy.API(auth).update_status(status)
        except tweepy.error.TweepError, error:
            logging.error("twitter update error: %s" % error)
            # error.reason is the list object like following:
            #   [{"message":"Sorry, that page does not exist","code":34}]
            # see the following references for details:
            #   - https://dev.twitter.com/docs/error-codes-responses
            #   - ./tweepy/error.py

            # replace single quatation with double quatation to parse string properly
            normalized_reasons_string = re.sub("u'(.+?)'", r'"\1"', error.reason)

            reasons = json.loads(normalized_reasons_string)
            # logging.debug("reasons: %s %s" % (type(reasons), reasons))
            for reason in reasons:
                # logging.debug("reason: %s %s" % (type(reason), reason))
                if reason["code"] == 187:
                    # 'Status is a duplicate.'
                    raise TwitterDuplicateStatusUpdateError(reason["message"], reason["code"])
                elif reason["code"] == 186:
                    # 'Status is over 140 characters.'
                    raise TwitterStatusUpdateError(reason["message"], reason["code"])
                elif reason["code"] == 185:
                    # 'User is over daily status update limit.'
                    raise TwitterOverUpdateLimitError(reason["message"], reason["code"])
            raise TwitterStatusUpdateError()

# nico nico
    def create_opener(self):
        # cookie
        cookiejar = cookielib.CookieJar()
        opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(cookiejar))
        # logging.debug("finished setting up cookie library")

        # login
        opener.open(
            LOGIN_URL, "mail=%s&password=%s" % (self.mail, self.password))
        logging.info("finished login")

        return opener

# bbs
    def get_bbs_internal_url(self, opener, community_id):
        # get bbs
        url = COMMUNITY_BBS_URL + community_id
        # logging.debug(url)
        reader = opener.open(url)
        rawhtml = reader.read()
        logging.debug("finished to get raw bbs.")

        # print rawhtml
        # use scraping by regular expression, instead of by beautifulsoup.
        se = re.search('<iframe src="(.+?)"', rawhtml)
        internal_url = se.group(1)

        logging.debug("bbs internal url: " + internal_url)

        return internal_url

    def get_bbs_responses(self, opener, url, community):
        # logging.debug(url)
        reader = opener.open(url)
        rawhtml = reader.read()
        logging.debug("finished to get raw responses.")
        # logging.debug(rawhtml)

        soup = BeautifulSoup(rawhtml)
        resheads = soup.findAll("dt", {"class": "reshead"})
        resbodies = soup.findAll("dd", {"class": "resbody"})
        responses = []
        index = 0
        for reshead in resheads:
            # extract
            number = reshead.find("a", {"class": "resnumhead"})["name"]
            name = reshead.find("span", {"class": "name"}).text.strip()
            # use "search", instead of "mathch". http://www.python.jp/doc/2.6/library/re.html#vs
            date = "n/a"
            se = re.search(DATE_REGEXP, reshead.text.strip())
            if se:
                date = se.group(1)
            hash_id = re.search(RESID_REGEXP, reshead.text.strip()).group(1)
            body = "".join([unicode(x) for x in resbodies[index]]).strip()
            body = self.prefilter_message(body)
            # logging.debug(u"[%s] [%s] [%s] [\n%s\n]".encode('utf_8') %
            # (number, name, date, body))
            index += 1

            # append
            response = {
                "community": community,
                "number": number,
                "name": name,
                "date": date,
                "hash": hash_id,
                "body": body,
                "status": STATUS_UNPROCESSED
            }
            responses.append(response)

        return responses

# message utility
    def prefilter_message(self, message):
        message = re.sub("<br/>", "\n", message)
        message = re.sub("<.*?>", "", message)
        message = re.sub("&gt;", ">", message)
        message = re.sub("&lt;", "<", message)
        message = re.sub("&amp;", "&", message)

        return message

    def postfilter_message(self, message):
        message = re.sub(u"\(省略しています。全て読むにはこのリンクをクリック！\)",
                         u"(省略)", message)
        return message

# scraping utility
    def read_community_page(self, opener, base_url, community):
        url = base_url + community
        logging.info("*** reading community page, target: " + url)

        reader = opener.open(url)
        rawhtml = reader.read()
        # logging.debug(rawhtml)
        logging.info("finished to read community page.")

        return rawhtml

    def find_community_name(self, soup):
        return soup.find("h1", {"id": "community_name"}).text

# reserved live
    def get_community_reserved_live(self, rawhtml, community):
        reserved_lives = []
        soup = BeautifulSoup(rawhtml)
        community_name = self.find_community_name(soup)
        lives = soup.findAll("div", {"class": "item"})

        for live in lives:
            date = live.find("p", {"class": "date"})
            title = live.find("p", {"class": "title"})
            if title:
                anchor = title.find("a")
                link = anchor["href"]
                se = re.search("/gate/", link)
                if se:
                    reserved_live = {"community": community,
                                     "link": link,
                                     "community_name": community_name,
                                     "date": date.text,
                                     "title": anchor.text,
                                     "status": STATUS_UNPROCESSED}
                    reserved_lives.append(reserved_live)

        return reserved_lives

# news
    def get_community_news(self, rawhtml, community):
        news_items = []
        soup = BeautifulSoup(rawhtml)
        community_name = self.find_community_name(soup)

        community_news_tag = soup.find(id="community_news")
        if community_news_tag:
            items = community_news_tag.select(".item")
            for item in items:
                title = item.select(".title")[0].get_text()
                desc = item.select(".desc")[0].get_text()
                desc = self.prefilter_message(desc)

                date_and_name = item.select(".date")[0].get_text()
                date = None
                name = None
                matched = re.match(ur'(.+)（(.+)）', date_and_name)
                if matched:
                    date = matched.group(1)
                    name = matched.group(2)

                news_item = {"community": community,
                             "community_name": community_name,
                             "title": title,
                             "desc": desc,
                             "date": date,
                             "name": name,
                             "status": STATUS_UNPROCESSED}
                news_items.append(news_item)

        return news_items

# video
    def get_community_video(self, rawhtml, community):
        videos = []
        soup = BeautifulSoup(rawhtml)
        video_tag = soup.find(id="video")

        if video_tag:
            items = video_tag.select(".video")
            for item in items:
                title = item.get_text()
                link = item["href"]

                video = {"community": community,
                         "title": title,
                         "link": link,
                         "status": STATUS_UNPROCESSED}
                videos.append(video)

        return videos

# mongo
    # response
    def register_response(self, response):
        self.database.response.update(
            {"community": response["community"], "number": response["number"]}, response, True)

    def is_response_registered(self, response):
        count = self.database.response.find(
            {"community": response["community"], "number": response["number"]}).count()
        return True if 0 < count else False

    def get_responses_with_community_and_status(self, community, status):
        responses = self.database.response.find(
            {"community": community, "status": status},
            sort=[("number", 1)])
        return responses

    def update_response_status(self, response, status):
        self.database.response.update(
            {"community": response["community"], "number": response["number"]},
            {"$set": {"status": status}})

    # reserved live
    def register_live(self, live):
        self.database.live.update(
            {"community": live["community"], "link": live["link"]}, live, True)

    def is_live_registered(self, live):
        count = self.database.live.find(
            {"community": live["community"], "link": live["link"]}).count()
        return True if 0 < count else False

    def get_lives_with_community_and_status(self, community, status):
        lives = self.database.live.find({"community": community, "status": status})
        return lives

    def update_live_status(self, live, status):
        self.database.live.update(
            {"community": live["community"], "link": live["link"]},
            {"$set": {"status": status}})

    # news
    def register_news(self, news):
        self.database.news.update(
            {"community": news["community"], "date": news["date"]}, news, True)

    def is_news_registered(self, news):
        count = self.database.news.find(
            {"community": news["community"], "date": news["date"]}).count()
        return True if 0 < count else False

    def get_news_with_community_and_status(self, community, status):
        news = self.database.news.find({"community": community, "status": status})
        return news

    def update_news_status(self, news, status):
        self.database.news.update(
            {"community": news["community"], "date": news["date"]},
            {"$set": {"status": status}})

    # video
    def register_video(self, video):
        self.database.video.update(
            {"community": video["community"], "link": video["link"]}, video, True)

    def is_video_registered(self, video):
        count = self.database.video.find(
            {"community": video["community"], "link": video["link"]}).count()
        return True if 0 < count else False

    def get_video_with_community_and_status(self, community, status):
        videos = self.database.video.find({"community": community, "status": status})
        return videos

    def update_video_status(self, video, status):
        self.database.video.update(
            {"community": video["community"], "link": video["link"]},
            {"$set": {"status": status}})

# filter
    def contains_ng_words(self, message):
        for word in self.ng_words:
            if re.search(word, message):
                return True
        return False

    def contains_too_many_link(self, message):
        videos = re.findall("sm\d{5,}", message)
        communities = re.findall("co\d{5,}", message)
        limit = 5
        if limit < len(videos) or limit < len(communities):
            return True
        return False

# main
    # def page_number(self, strnum):
    #     intnum = int(strnum)
    #     return str(intnum - ((intnum-1) % 30))

    # bbs
    def crawl_bbs_response(self, opener, community):
        logging.info("*** crawling responses, community: %s" % community)

        internal_url = self.get_bbs_internal_url(opener, community)
        responses = self.get_bbs_responses(opener, internal_url, community)
        logging.debug("scraped %s responses" % len(responses))

        skipped_responses = []
        registered_responses = []

        for response in responses:
            response_number = "#%s" % response["number"]
            if self.is_response_registered(response):
                skipped_responses.append(response_number)
            else:
                self.register_response(response)
                registered_responses.append(response_number)

        logging.debug("skipped: %s" % skipped_responses)
        logging.debug("registered: %s" % registered_responses)
        logging.info("completed to crawl responses")

    def tweet_bbs_response(self, community, limit=0):
        unprocessed_responses = self.get_responses_with_community_and_status(
            community, STATUS_UNPROCESSED)
        tweet_count = 0

        logging.info("*** processing responses, community: %s unprocessed: %d" %
                     (community, unprocessed_responses.count()))

        for response in unprocessed_responses:
            logging.debug("processing response #%s" % response["number"])

            response_name = response["name"]
            response_body = response["body"]

            if (self.contains_ng_words(response_body) or
                    self.contains_too_many_link(response_body)):
                logging.debug(
                    "response contains ng word/too many video, so skip: [%s]" % response_body)
                self.update_response_status(response, STATUS_SPAM)
                continue

            # create statuses
            response_body = self.postfilter_message(response_body)
            statuses = nicoutil.create_twitter_statuses(
                u'(' + response_name + u')\n', u'[続き]\n', response_body, u'\n[続く]')

            for status in statuses:
                if 0 < tweet_count:
                    logging.debug("sleeping %d secs before next tweet..." % TWEET_INTERVAL)
                    time.sleep(TWEET_INTERVAL)
                try:
                    self.update_twitter_status(community, status)
                except TwitterDuplicateStatusUpdateError, error:
                    # status is already posted to twitter. so response status should be
                    # changed from 'unprocessed' to other, in order to avoid reprocessing
                    logging.error("twitter status update error, duplicate: %s" % error)
                    self.update_response_status(response, STATUS_DUPLICATE)
                    break
                except TwitterOverUpdateLimitError, error:
                    # quit this status update sequence
                    logging.error("twitter status update error, over limit: %s" % error)
                    raise
                except TwitterStatusUpdateError, error:
                    # twitter error case including api limit
                    # response status should not be changed here for future retrying
                    logging.error("twitter status update error, unknown: %s" % error)
                    break
                else:
                    self.update_response_status(response, STATUS_COMPLETED)
                    logging.info("status updated: [%s]" % status)
                tweet_count += 1

            if limit and limit <= tweet_count:
                logging.info("breaking tweet processing, limit: %d tweet_count: %d" %
                             (limit, tweet_count))
                break

        logging.info("completed to process responses")

    # reserved live
    def crawl_reserved_live(self, rawhtml, community):
        logging.info("*** crawling new reserved lives, community: %s" % community)
        reserved_lives = self.get_community_reserved_live(rawhtml, community)
        logging.debug("scraped %s reserved lives" % len(reserved_lives))

        for reserved_live in reserved_lives:
            if self.is_live_registered(reserved_live):
                logging.debug("skipped: %s" % reserved_live["link"])
            else:
                self.register_live(reserved_live)
                logging.debug("registered: %s" % reserved_live["link"])

        logging.info("completed to crawl reserved lives")

    def tweet_reserved_live(self, community, limit=0):
        unprocessed_lives = self.get_lives_with_community_and_status(
            community, STATUS_UNPROCESSED)

        logging.info("*** processing lives, community: %s unprocessed: %d" %
                     (community, unprocessed_lives.count()))

        for live in unprocessed_lives:
            logging.debug("processing live %s" % live["link"])

            status = (u"【放送予約】「" + live["community_name"] + u"」で生放送「" +
                      live["title"] + u"」が予約されました。" + live["date"] + u" " +
                      live["link"])
            try:
                self.update_twitter_status(community, status)
            except TwitterDuplicateStatusUpdateError, error:
                logging.error("twitter status update error, duplicate: %s", error)
                self.update_live_status(live, STATUS_DUPLICATE)
                break
            except TwitterOverUpdateLimitError, error:
                logging.error("twitter status update error, over limit: %s" % error)
                raise
            except TwitterStatusUpdateError, error:
                logging.error("twitter status update error, unknown")
                break
            else:
                self.update_live_status(live, STATUS_COMPLETED)
                logging.info("status updated: [%s]" % status)

            if limit and limit <= tweet_count:
                logging.info("breaking tweet processing, limit: %d tweet_count: %d" %
                             (limit, tweet_count))
                break

        logging.info("completed to process reserved lives")

    # news
    def crawl_news(self, rawhtml, community):
        logging.info("*** crawling news, community: %s" % community)
        news_items = self.get_community_news(rawhtml, community)
        logging.debug("scraped %s news" % len(news_items))

        for news_item in news_items:
            if self.is_news_registered(news_item):
                logging.debug("skipped: %s" % news_item["date"])
            else:
                self.register_news(news_item)
                logging.debug("registered: %s" % news_item["date"])

        logging.info("completed to crawl news")

    def tweet_news(self, community, limit=0):
        unprocessed_news = self.get_news_with_community_and_status(
            community, STATUS_UNPROCESSED)
        tweet_count = 0

        logging.info("*** processing news, community: %s unprocessed: %d" %
                     (community, unprocessed_news.count()))

        for news in unprocessed_news:
            logging.debug("processing news %s" % news["date"])

            statuses = nicoutil.create_twitter_statuses(
                u"【お知らせ更新】\n" +
                u"「%s」(%s)\n\n" % (news["title"], news["name"]),
                u'[続き]\n', news["desc"], u'\n[続く]')

            for status in statuses:
                if 0 < tweet_count:
                    logging.debug("sleeping %d secs before next tweet..." % TWEET_INTERVAL)
                    time.sleep(TWEET_INTERVAL)
                try:
                    self.update_twitter_status(community, status)
                except TwitterDuplicateStatusUpdateError, error:
                    logging.error("twitter status update error, duplicate: %s" % error)
                    self.update_news_status(news, STATUS_DUPLICATE)
                    break
                except TwitterOverUpdateLimitError, error:
                    logging.error("twitter status update error, over limit: %s" % error)
                    raise
                except TwitterStatusUpdateError, error:
                    logging.error("twitter status update error, unknown: %s" % error)
                    break
                else:
                    self.update_news_status(news, STATUS_COMPLETED)
                    logging.info("status updated: [%s]" % status)
                tweet_count += 1

            if limit and limit <= tweet_count:
                logging.info("breaking tweet processing, limit: %d tweet_count: %d" %
                             (limit, tweet_count))
                break

        logging.info("completed to process news")

    # video
    def crawl_video(self, rawhtml, community):
        logging.info("*** crawling video, community: %s" % community)
        videos = self.get_community_video(rawhtml, community)
        logging.debug("scraped %s videos" % len(videos))

        for video in videos:
            if self.is_video_registered(video):
                logging.debug("skipped: %s" % video["link"])
            else:
                self.register_video(video)
                logging.debug("registered: %s" % video["link"])

        logging.info("completed to crawl video")

    def tweet_video(self, community, limit=0):
        unprocessed_videos = self.get_video_with_community_and_status(
            community, STATUS_UNPROCESSED)
        tweet_count = 0

        logging.info("*** processing video, community: %s unprocessed: %d" %
                     (community, unprocessed_videos.count()))

        for video in unprocessed_videos:
            logging.debug("processing video %s" % video["link"])

            statuses = nicoutil.create_twitter_statuses(
                u"【コミュニティ動画投稿】",
                u'[続き]\n',
                u"動画「%s」が投稿されました。%s" % (video["title"], video["link"]),
                u'\n[続く]')

            for status in statuses:
                if 0 < tweet_count:
                    logging.debug("sleeping %d secs before next tweet..." % TWEET_INTERVAL)
                    time.sleep(TWEET_INTERVAL)
                try:
                    self.update_twitter_status(community, status)
                except TwitterDuplicateStatusUpdateError, error:
                    logging.error("twitter status update error, duplicate: %s" % error)
                    self.update_video_status(video, STATUS_DUPLICATE)
                    break
                except TwitterOverUpdateLimitError, error:
                    logging.error("twitter status update error, over limit: %s" % error)
                    raise
                except TwitterStatusUpdateError, error:
                    logging.error("twitter status update error, unknown: %s" % error)
                    break
                else:
                    self.update_video_status(video, STATUS_COMPLETED)
                    logging.info("status updated: [%s]" % status)
                tweet_count += 1

            if limit and limit <= tweet_count:
                logging.info("breaking tweet processing, limit: %d tweet_count: %d" %
                             (limit, tweet_count))
                break

        logging.info("completed to process video")

# main
    def start(self, limit=0):
        # inifinite loop
        while True:
            try:
                logging.debug(LOG_SEPARATOR)
                opener = self.create_opener()
            except Exception, error:
                logging.error("*** caught error when creating opener, error : %s" % error)
            else:
                for community in self.target_communities:
                    logging.debug(LOG_SEPARATOR)
                    try:
                        try:
                            self.crawl_bbs_response(opener, community)
                            self.tweet_bbs_response(community, limit)
                        except TwitterOverUpdateLimitError:
                            raise
                        except urllib2.HTTPError, error:
                            logging.error(
                                "*** caught http error when processing bbs, error: %s" % error)
                            if error.code == 403:
                                logging.info("bbs is closed?")
                        except Exception, error:
                            logging.error(
                                "*** caught error when processing bbs, error: %s" % error)

                        try:
                            rawhtml = self.read_community_page(opener, COMMUNITY_TOP_URL, community)
                            self.crawl_reserved_live(rawhtml, community)
                            self.tweet_reserved_live(community, limit)
                            self.crawl_news(rawhtml, community)
                            self.tweet_news(community, limit)

                            rawhtml = self.read_community_page(opener, COMMUNITY_VIDEO_URL, community)
                            self.crawl_video(rawhtml, community)
                            self.tweet_video(community, limit)
                        except TwitterOverUpdateLimitError:
                            raise
                        except Exception, error:
                            logging.error(
                                "*** caught error when processing live/video, error: %s" % error)
                    except TwitterOverUpdateLimitError:
                        logging.warning("status update over limit, so skip.")

            if limit:
                break
            else:
                logging.debug(LOG_SEPARATOR)
                logging.debug("*** sleeping %d secs..." % CRAWL_INTERVAL)
                time.sleep(CRAWL_INTERVAL)


if __name__ == "__main__":
    nicobbs = NicoBBS()
    nicobbs.start()
