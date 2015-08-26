#! /usr/bin/env python3.4

import praw
import operator
import sqlite3
import re
import time
import logging
import logging.handlers

from configparser import ConfigParser
from sys import exit, stdout, stderr
from requests import exceptions


############################################################################
class Comments:
    
    def __init__(self, subreddit, r):
        # subreddit to parse through
        # set to /r/all, but could be
        # set to a specific sub if needed
        self.subreddit = subreddit
        # r is the praw Reddit Object
        self.r = r

    def get_comments_to_parse(self):
        # gets the subreddit, usually /r/all
        sub = self.r.get_subreddit(self.subreddit)
        # retrieves the comments from this subreddit
        # the limit is set to None, but is actually 1024
        self.comments = sub.get_comments(limit = None)
    
    def search_comments(self):
        log.debug("Searching comments")
        db = Database()
        # goes through each comment and 
        # searches for the keyword string
        for comment in self.comments:
            string, username = self.parse_for_keywords(comment)
            
            if string:

                ID = comment.id
                
                if not db.lookup(ID):
                    try:
                        self.user = User(self.r, username)
                    except exceptions.HTTPError:
                        log.debug("Error, not an actual username")
                        continue
                
                    reply_string = self.user.gone_wild_check()
                    self.reply(comment, reply_string)
                    
                    db.insert(ID)


    def parse_for_keywords(self, comment):
        # search for keyword string
        match = re.findall(r'(Has [/]?u/([\w\d_-]*) gone[\s]?wild\?)',
                           str(comment), re.IGNORECASE)
        try:
            # match will be None if we don't 
            # find the keyword string
            string = match[0][0]
            username = match[0][1]

        except IndexError:
            string = False 
            username = False

        return string, username

    def reply(self, comment, reply_string):
       comment_author = str(comment.author)
       
       log.debug("Replying to " + comment_author + " about user: " +\
             self.user.username)
       
       try:
           comment.reply(reply_string)
       
       except praw.errors.RateLimitExceeded as error:
           log.debug("Rate limit exceeded, must sleep for "
                     "{} mins".format(float(error.sleep_time / 60)))
           time.sleep(error.sleep_time)
           comment.reply(reply_string)
       
       log.debug("Reply sucessful!")
 
 
###########################################################################
class Database:

    def __init__(self):
        # connect to and create DB if not created yet
        self.sql = sqlite3.connect('commentID.db')
        self.cur = self.sql.cursor()

        self.cur.execute('CREATE TABLE IF NOT EXISTS comments(ID TEXT)')
        self.sql.commit()

    def insert(self, ID):
        """
        Add ID to comment database so we know we already replied to it
        """
        self.cur.execute('INSERT INTO comments (ID) VALUES (?)', [ID])
        self.sql.commit()

        log.debug("Inserted " + str(ID) + " into comment database!")


    def lookup(self, ID):
        """
        See if the ID has already been added to the database.
        """
        self.cur.execute('SELECT * FROM comments WHERE ID=?', [ID])
        result = self.cur.fetchone()
        return result


###########################################################################
class User:

    def __init__(self, r, user):

        log.debug("Checking " + user)

        # gets all the users' info
        self.user = r.get_redditor(user)
        self.username = str(self.user.name)

        # comment_subs is a list of 
        # all the subreddits they've commented in
        self.comments = self.subreddits_interacted_with(self.user.get_comments())
        
        # submission_subs is a list of all the subreddits they've submitted
        # text/photos/links to
        self.submissions = self.subreddits_interacted_with(self.user.get_submitted())
        
        # produces a dictionary of how many times the user has commented/posted in
        # each subreddit.
        self.comments = self.clean_up_subreddits(self.comments)
        self.submissions = self.clean_up_subreddits(self.submissions)

    def subreddits_interacted_with(self, fn):
        log.debug("Retrieving subreddits")
    
        subs = []

        # fn is either user.get_comments or user.get_submitted 
        for data in fn:
            subs.append(data.subreddit.display_name)
        
        return subs 
    
    def clean_up_subreddits(self, subreddits):
        counter_dict = {}
    
        for subreddit in subreddits:
            # counts and organizes the amount of times a user
            # has posted/commented in a subreddit
            if subreddit.lower() in counter_dict:
                counter_dict[subreddit] += 1
            else:
                counter_dict[subreddit] = 1

        return counter_dict

    def gone_wild_check(self):

        self.comment = False
        self.comment_num = 0
        self.submitted = False
        self.submitted_num = 0
        self.sub_to_check = "gonewild"
        
        log.debug(self.comments)
        log.debug(self.submissions)

        if self.sub_to_check in self.comments:
            # the second value is the value in the dict for
            # the number of times that user has 
            # commented/posted in gonewild 
            self.comment = True
            self.comment_num = self.comments[self.sub_to_check]

        if self.sub_to_check in self.submissions:
            self.submitted = True
            self.submitted_num = self.submissions[self.sub_to_check]
        
        self.format_string()
        
        return self.reply

    def format_string(self):
        reply_footer = "\n___\n"\
                       "^| [^About ^me](https://www.reddit.com/r/BotGoneWild/comments/3ifrj5/information_about_botgonewild_here/?ref=share&ref_source=link) "\
                       "^| [^Contact](https://www.reddit.com/message/compose/?to=camerongagnon) "\
                       '^| ^Syntax: ^"Has ^/u/username ^gone ^wild?" '\
                       "^| [^code](https://github.com/cameron-gagnon/botgonewild) ^|"

        # posted and commented
        if self.comment and self.submitted:
            self.reply = "/u/" + self.username +\
                         " has gone wild! They have posted " +\
                         str(self.submitted_num) +\
                         " time(s) and have commented " +\
                         str(self.comment_num) + " time(s)."

        # not posted but has commented
        elif self.comment and not self.submitted:
            self.reply = "/u/" + self.username +\
                         " has gone wild! They have commented "\
                         + str(self.comment_num) +\
                         " time(s) but have not posted."

        # posted but not commented
        elif not self.comment and self.submitted:
            self.reply = "/u/" + self.username +\
                         " has gone wild! They have posted "\
                         + str(self.submitted_num) +\
                         " time(s) but have not commented."

        # not posted and not commented
        elif not self.comment and not self.submitted:
            self.reply = "/u/" + self.username + " has not gone wild!"

        self.reply += reply_footer


##############################################################################
# Makes stdout and stderr print to the logging module
def config_logging():
    """ Configures the logging to external file """
    global log
    
    # set file logger
    rootLog = logging.getLogger('')
    rootLog.setLevel(logging.DEBUG)
    
    # make it so requests doesn't show up all the time in our output
    logging.getLogger('urllib3').setLevel(logging.WARNING)

    logging.getLogger('requests').setLevel(logging.WARNING)

    # set format for output to file
    formatFile = logging.Formatter(fmt='%(asctime)-s %(levelname)-6s: '\
                                       '%(lineno)d : %(message)s',
                                   datefmt='%m-%d %H:%M')
    
    # add filehandler so once the filesize reaches 5MB a new file is 
    # created, up to 3 files
    fileHandle = logging.handlers.RotatingFileHandler("INFO.log",
                                                      maxBytes=5000000,
                                                      backupCount=5,
                                                      encoding = "utf-8")
    fileHandle.setFormatter(formatFile)
    rootLog.addHandler(fileHandle)
    
    # configures logging to console
    # set console logger
    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG) #toggle console level output with this line
    
    # set format for console logger
    consoleFormat = logging.Formatter('%(levelname)-6s %(message)s')
    console.setFormatter(consoleFormat)
    
    # add handler to root logger so console && file are written to
    logging.getLogger('').addHandler(console)
    log = logging.getLogger('gonewild')
#stdout = LoggerWriter(log.debug)
#stderr = LoggerWriter(log.warning)

###############################################################################
class LoggerWriter:
    def __init__(self, level):
        self.level = level

    def write(self, message):
        # eliminate extra newlines in default sys.stdout
        if message != '\n':
            self.level(message)

    def flush(self):
        self.level(sys.stderr)


###############################################################################
def connect():
    log.debug("Logging in...")
    
    r = praw.Reddit("browser-based:GoneWild Script:v1.0 (by /u/camerongagnon)")
    
    config = ConfigParser()
    config.read("login.txt")
    
    username = config.get("Reddit", "username")
    password = config.get("Reddit", "password")
    
    r.login(username, password)
    
    return r


###############################################################################
def main():
    try:
        r = connect()
        
        while True:
            # get comments from r/all to search through
            com = Comments("all", r)
            com.get_comments_to_parse()
            com.search_comments()
            log.debug("Sleeping...")
            time.sleep(30)

    except KeyboardInterrupt:
        log.debug("Exiting")
        exit(0)
    

###############################################################################
#### MAIN ####
###############################################################################
if __name__ == '__main__':
    config_logging()
    main()
