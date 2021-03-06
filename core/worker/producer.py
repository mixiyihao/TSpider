#!/usr/bin/python
# -*- coding:utf-8 -*-
#
"""
Copyright (c) 2016-2017 twi1ight@t00ls.net (http://twi1ight.com/)
See the file 'doc/COPYING' for copying permission
"""
import json
import time

from core.utils.redis_utils import RedisUtils
from core.utils.mongo_utils import MongoUtils
from core.utils.url import URL
from core.utils.log import logger


class Producer(object):
    """
    Producer Class
    make targets for consumer
    save results to mongodb
    """

    def __init__(self, **kwargs):
        """
        :return: :class:Producer object
        :rtype: Producer
        """
        self.context = kwargs.pop('context')
        self.__mongo_db = kwargs.pop('mongo_db')
        self.mongo_handle = None
        self.redis_handle = RedisUtils(db=kwargs.pop('redis_db'), tld=kwargs.pop('tld'))

    def produce(self):
        # mongodb with multipleprocessing must be init after fork
        self.mongo_handle = MongoUtils(db=self.__mongo_db)
        if not self.redis_handle.connected or not self.mongo_handle.connected:
            logger.error('no redis/mongodb connection found! exit.')
            return

        while True:
            try:
                _, req = self.redis_handle.fetch_one_result()
                with self.context['lock']:
                    self.context['result_counts'].value -= 1
                logger.debug('got req, %d results left' % self.context['result_counts'].value)
                self.proc_req(req)
            except:
                logger.exception('produce exception!')
                if not self.redis_handle.connected:
                    logger.error('redis disconnected! reconnecting...')
                    self.redis_handle.connect()
                if not self.mongo_handle.connected:
                    logger.error('mongodb disconnected! reconnecting...')
                    self.mongo_handle.connect()
                time.sleep(10)
            finally:
                with self.context['lock']:
                    if self.context['result_counts'].value == 0:
                        if self.context['live_spider_counts'].value == 0 and self.context['task_counts'].value == 0:
                            self.context['task_done'].set()

    def proc_req(self, req):
        try:
            data = json.loads(req)
        except:
            logger.exception('json loads req error: %s' % req)
            return
        urlstring = data.get('url', '')
        if not urlstring:
            logger.error('empty url found!')
            return
        url = URL(urlstring)

        method = data.get('method', '')
        if not method:
            logger.error('not method found!')
            return
        # save to mongodb
        data.update({'pattern': url.pattern,
                     'hostname': url.hostname,
                     'domain': url.domain
                     })
        target = self.redis_handle.is_target(url)

        if not self.redis_handle.is_url_saved(method, url):
            logger.debug('redis saved pattern not found!')
            self.mongo_handle.save(data, is_target=target)
            self.redis_handle.set_url_saved(method, url)
        else:
            logger.debug('redis saved pattern found!')

        if not target:
            logger.debug('%s is not target' % url.hostname)
            return

        # todo post req
        if method == 'POST':
            logger.debug('POST not support now')
        elif method == 'GET':
            # new host found, add index page to task queue
            if self.redis_handle.get_hostname_reqcount(url.hostname) == 0:
                self.create_task_from_url(URL(url.index_page), add_whitelist=False)
            # check url validation inside create_url_task
            self.create_task_from_url(url, add_whitelist=False)
        else:
            # not GET nor POST
            logger.error('HTTP Verb %s found!' % method)
            logger.debug(data)

    def create_task_from_url(self, url, **kwargs):
        with self.context['lock']:
            if self.redis_handle.create_task_from_url(url, **kwargs):
                self.context['task_counts'].value += 1

    def create_task_from_file(self, fileobj):
        """
        create task from file
        :param filename:
        :return:
        """
        with fileobj:
            for line in fileobj:
                line = line.strip()
                if not line: continue
                url = URL(line)
                self.create_task_from_url(url)


if __name__ == '__main__':
    # tld=False, only scan links inside demo.aisec.cn
    # no scan www.aisec.cn even got links from demo.aisc.cn
    p = Producer(tld=False)
    url = URL('http://demo.aisec.cn/demo/aisec/')
    p.create_task_from_url(url)
    p.produce()

    # with open('test.txt') as f:
    #     p.create_file_task(f)
