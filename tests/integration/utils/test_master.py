# -*- coding: utf-8 -*-
'''
Test master code from utils
'''
from __future__ import absolute_import

import os
import time

import setproctitle  # pylint: disable=W8410

import salt.config
import salt.utils.master as master

from tests.support.case import ShellTestCase
from tests.support.paths import TMP_ROOT_DIR
from tests.support.helpers import flaky

DEFAULT_CONFIG = salt.config.master_config(None)
DEFAULT_CONFIG['cachedir'] = os.path.join(TMP_ROOT_DIR, 'cache')


class MasterUtilJobsTestCase(ShellTestCase):

    def setUp(self):
        # Necessary so that the master pid health check
        # passes as it looks for salt in cmdline
        setproctitle.setproctitle('salt')

    @flaky
    def test_get_running_jobs(self):
        '''
        Test get running jobs
        '''
        ret = self.run_run_plus("test.sleep", '90', asynchronous=True)
        jid = ret['jid']
        time.sleep(20)
        jobs = master.get_running_jobs(DEFAULT_CONFIG)
        jids = [job['jid'] for job in jobs]
        assert jids.count(jid) == 1
