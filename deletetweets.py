#!/usr/bin/env python3

import argparse
import io
import os
import sys
import time
import json

import twitter
from dateutil.parser import parse

__author__ = "Koen Rouwhorst, Heinrich Ulbricht"
__version__ = "1.0.0"


class TweetDestroyer(object):
    def __init__(self, twitter_api):
        self.twitter_api = twitter_api

    def destroy(self, id_str, created_at, full_text):
        try:
            print("delete tweet %s (%s: '%s')" % (id_str, created_at, full_text.encode('ascii', 'replace').decode('ascii')))
            self.twitter_api.DestroyStatus(id_str)
            # NOTE: A poor man's solution to honor Twitter's rate limits.
            time.sleep(0.5)
        except twitter.TwitterError as err:
            print("Exception: %s\n" % err.message)

class LikeRemover(object):
    def __init__(self, twitter_api):
        self.twitter_api = twitter_api

    def removeLike(self, id_str, created_at, full_text):
        try:
            print("removing like %s (%s: '%s')" % (id_str, created_at, full_text.encode('ascii', 'replace').decode('ascii')))

            self.twitter_api.DestroyFavorite(status_id=id_str)
            # NOTE: A poor man's solution to honor Twitter's rate limits.
            time.sleep(0.5)
        except twitter.TwitterError as err:
            print("Exception: %s\n" % err.message)

class TweetReader(object):
    def __init__(self, reader, date=None, restrict=None, spare=[], min_likes=0, min_retweets=0, remove_likes = False):
        self.reader = reader
        if date is not None:
            self.date = parse(date, ignoretz=True).date()
        self.restrict = restrict
        self.spare = spare
        self.min_likes = min_likes
        self.min_retweets = min_retweets
        self.remove_likes = remove_likes

    def isTweetToDestroy(self, id_str, created_at, full_text, in_reply_to_user_id_str, favorite_count, retweet_count):
        if created_at != "":
            tweet_date = parse(created_at, ignoretz=True).date()
            if self.date != "" and \
                    self.date is not None and \
                    tweet_date >= self.date:
                return False

        if (self.restrict == "retweet" and
                not full_text.startswith("RT @")) or \
                (self.restrict == "reply" and
                    (in_reply_to_user_id_str == "" or in_reply_to_user_id_str == "None")):
            return False

        if id_str in self.spare:
            return False

        if (self.min_likes and int(favorite_count) >= self.min_likes) or \
                (self.min_retweets and int(retweet_count) >= self.min_retweets):
            return False
        
        return True

    def isLikeToRemove(self, id_str, created_at, favorite_count, retweet_count):
        if created_at != "":
            tweet_date = parse(created_at, ignoretz=True).date()
            if self.date != "" and \
                    self.date is not None and \
                    tweet_date >= self.date:
                return False

        if id_str in self.spare:
            return False

        if (self.min_likes and int(favorite_count) >= self.min_likes) or \
                (self.min_retweets and int(retweet_count) >= self.min_retweets):
            return False
        
        return True

    def readFromTweetJs(self):
        for row in self.reader:
            if not self.isTweetToDestroy(row.get("id_str"), row.get("created_at", ""), row.get("full_text"), row.get("in_reply_to_user_id_str"), row.get("favorite_count"), row.get("retweet_count")):
                continue

            yield row

    def readUserTimelineLive(self, api):
        maxCount = 200 # this is the maximum number of statuses retrievable in a single call according to the API documentation

        # we'll page with a page size of 200 up to the alledged maximum of 3200 tweets
        lastId = None
        while True:
            if (not lastId):
                statuses = api.GetUserTimeline(count=maxCount)
            else :
                time.sleep(0.5)
                statuses = api.GetUserTimeline(count=maxCount, max_id=lastId-1)
                if (len(statuses) == 0):
                    break
            for s in statuses:
                lastId = s.id
                if not self.isTweetToDestroy(s.id_str, s.created_at, s.text, str(s.in_reply_to_user_id), str(s.favorite_count), str(s.retweet_count)):
                    continue
                yield s

    def readFavoritesLive(self, api):
        maxCount = 200 # this is the maximum number of statuses retrievable in a single call according to the API documentation

        # we'll page with a page size of 200 up to the alledged maximum of 3200 tweets
        lastId = None
        while True:
            if (not lastId):
                statuses = api.GetFavorites(count=maxCount)
            else :
                time.sleep(0.5)
                statuses = api.GetFavorites(count=maxCount, max_id=lastId-1)
                if (len(statuses) == 0):
                    break
            for s in statuses:
                lastId = s.id
                if not self.isLikeToRemove(s.id_str, s.created_at, str(s.favorite_count), str(s.retweet_count)):
                    continue
                yield s
        
def getTwitterApi():
    api = twitter.Api(consumer_key=os.environ["TWITTER_CONSUMER_KEY"],
                        consumer_secret=os.environ["TWITTER_CONSUMER_SECRET"],
                        access_token_key=os.environ["TWITTER_ACCESS_TOKEN"],
                        access_token_secret=os.environ["TWITTER_ACCESS_TOKEN_SECRET"])
    return api

def startProcessing(tweetjs_path, date, restrict, spare_ids, min_likes, min_retweets, remove_likes):
    api = getTwitterApi()
    tweetDestroyer = TweetDestroyer(api)
    likeRemover = LikeRemover(api)
    deletedTweetCount = 0
    removedLikeCount = 0
    if (tweetjs_path != "twitter"):
        with io.open(tweetjs_path, mode="r", encoding="utf-8") as tweetjs_file:
            tweets = json.loads(tweetjs_file.read()[25:])
            for row in TweetReader(tweets, date, restrict, spare_ids, min_likes, min_retweets, remove_likes).readFromTweetJs():
                tweetDestroyer.destroy(row["id_str"], row["created_at"], row["full_text"])
                deletedTweetCount += 1
    else:
        for status in TweetReader(None, date, restrict, spare_ids, min_likes, min_retweets, remove_likes).readUserTimelineLive(api):
            tweetDestroyer.destroy(status.id_str, status.created_at, status.text)
            deletedTweetCount += 1
        if (remove_likes):
            for status in TweetReader(None, date, restrict, spare_ids, min_likes, min_retweets, remove_likes).readFavoritesLive(api):
                likeRemover.removeLike(status.id_str, status.created_at, status.text)
                removedLikeCount += 1
            print("Number of removed likes: %s\n" % removedLikeCount)
    print("Number of deleted tweets: %s\n" % deletedTweetCount)


def main():
    parser = argparse.ArgumentParser(description="Delete old tweets.")
    parser.add_argument("-d", dest="date", required=True,
                        help="Delete tweets until this date")
    parser.add_argument("-r", dest="restrict", choices=["reply", "retweet"],
                        help="Restrict to either replies or retweets")
    parser.add_argument("file", help="Path to the tweet.js file -OR- specify 'twitter' to activate LIVE MODE instead: read from current user timeline (Note: there is a limit of 3200 tweets that can be retrieved this way)",
                        type=str)
    parser.add_argument("--spare-ids", dest="spare_ids", help="A list of tweet ids to spare",
                        type=str, nargs="+", default=[])
    parser.add_argument("--spare-min-likes", dest="min_likes",
                        help="Spare tweets with more than the provided likes", type=int)
    parser.add_argument("--spare-min-retweets", dest="min_retweets",
                        help="Spare tweets with more than the provided retweets", type=int)
    parser.add_argument("--remove-likes", dest="remove_likes", action="store_true",
                        help="Remove likes (currently only supported in LIVE MODE, the same 3200 tweet limit applies)")

    args = parser.parse_args()

    if not ("TWITTER_CONSUMER_KEY" in os.environ and
            "TWITTER_CONSUMER_SECRET" in os.environ and
            "TWITTER_ACCESS_TOKEN" in os.environ and
            "TWITTER_ACCESS_TOKEN_SECRET" in os.environ):
        sys.stderr.write("Twitter API credentials not set.")
        exit(1)

    startProcessing(args.file, args.date, args.restrict, args.spare_ids, args.min_likes, args.min_retweets, args.remove_likes)


if __name__ == "__main__":
    main()
