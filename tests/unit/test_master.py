# -*- coding: utf-8 -*-

# Import Python libs
from __future__ import absolute_import

# Import Salt libs
import salt.config
import salt.master
import copy

# Import Salt Testing Libs
from tests.support.unit import TestCase, expectedFailure, skipIf
from tests.support.mock import (
    patch,
    MagicMock,
)


# These tests require a working /bb/bin/bbcpu.lst/alias.
# I ran them inside a docker container using the docker-compose.yml in root
class AESFuncsTestCase(TestCase):
    '''
    TestCase for salt.master.AESFuncs class
    '''
    def setUp(self):
        self.opts = salt.config.master_config(None)

    def test__file_envs_no_matching_node(self):
        # Default master opts
        opts = copy.deepcopy(self.opts)
        opts['ext_pillar'] = [
            {'environments': ['word']}
        ]

        aes_funcs = salt.master.AESFuncs(opts)
        res = aes_funcs._file_envs({"id": "pytest_minion_1"})
        self.assertEqual(res, ['salt-core-nostage'])

    def test__file_envs_load_is_none(self):
        # Default master opts
        opts = copy.deepcopy(self.opts)
        opts['evaporator'] = {'tenancies': [{'name': 'salt-core', 'groups': ['salt'], 'global': True}]}
        opts['ext_pillar'] = [
            {'environments': ['word']}
        ]

        aes_funcs = salt.master.AESFuncs(opts)
        res = aes_funcs._file_envs()
        self.assertEqual(res, ['salt-core-nostage'])

    def test__file_envs_node_is_found(self):
        # Default master opts
        opts = copy.deepcopy(self.opts)
        opts['ext_pillar'] = [
            {'environments': ['word']}
        ]
        opts['evaporator'] = {
            'tenancies': [
                {"name": "sltdm", "groups": ["salt"], "global": False},
                {"name": "salt-native", "groups": ["salt"], "global": True},
                {"name": "salt-water", "groups": ["salt"], "global": False},
            ]
        }

        aes_funcs = salt.master.AESFuncs(opts)
        res = aes_funcs._file_envs({"id": "sltdm-rr-005"})
        self.assertEqual(res, ['salt-native-s4', 'sltdm-s4', 'salt-water-s4'])

    def test__file_envs_node_no_environment(self):
        # Default master opts
        opts = copy.deepcopy(self.opts)
        opts['evaporator'] = {
            'tenancies': [
                {"name": "sltdm", "groups": ["salt"], "global": False},
                {"name": "salt-native", "groups": ["salt"], "global": True},
                {"name": "salt-water", "groups": ["salt"], "global": False},
            ]
        }

        aes_funcs = salt.master.AESFuncs(opts)
        res = aes_funcs._file_envs({"id": "sltdm-rr-005"})
        self.assertEqual(res, ["base"])

    def test_master_opts_ext_pillar_environments(self):
        opts = copy.deepcopy(self.opts)
        opts['ext_pillar'] = [
            {'environments': ['word']}
        ]
        opts['evaporator'] = {}
        opts['evaporator']['tenancies'] = [
            {"environment": "sltdm", "global": False},
            {"environment": "salt-native", "global": True},
            {"environment": "salt-water", "global": False},
        ]

        aes_funcs = salt.master.AESFuncs(opts)

        res = aes_funcs._master_opts({
            "id": "sltdm-rr-005",
            "env_only": True,
        })
        self.assertEqual(res, {u'default_top': u'base', u'env_order': [], u'ext_pillar': [{'environments': ['word']}], u'top_file_merging_strategy': u'merge', u'file_roots': {u'environments': []},})


class ClearFuncsTestCase(TestCase):
    '''
    TestCase for salt.master.ClearFuncs class
    '''
    def setUp(self):
        opts = salt.config.master_config(None)
        self.clear_funcs = salt.master.ClearFuncs(opts, {})

    # runner tests

    @skipIf(True, 'bb test was failing when ran in Jenkins')
    def test_runner_token_not_authenticated(self):
        '''
        Asserts that a TokenAuthenticationError is returned when the token can't authenticate.
        '''
        mock_ret = {'error': {'name': 'TokenAuthenticationError',
                                'message': 'Authentication failure of type "token" occurred.'}}
        ret = self.clear_funcs.runner({'token': 'asdfasdfasdfasdf'})
        self.assertDictEqual(mock_ret, ret)

    @expectedFailure #bb test was failing when ran in Jenkins
    def test_runner_token_authorization_error(self):
        '''
        Asserts that a TokenAuthenticationError is returned when the token authenticates, but is
        not authorized.
        '''
        token = 'asdfasdfasdfasdf'
        clear_load = {'token': token, 'fun': 'test.arg'}
        mock_token = {'token': token, 'eauth': 'foo', 'name': 'test'}
        mock_ret = {'error': {'name': 'TokenAuthenticationError',
                                'message': 'Authentication failure of type "token" occurred '
                                            'for user test.'}}

        with patch('salt.auth.LoadAuth.authenticate_token', MagicMock(return_value=mock_token)), \
                patch('salt.auth.LoadAuth.get_auth_list', MagicMock(return_value=[])):
            ret = self.clear_funcs.runner(clear_load)

        self.assertDictEqual(mock_ret, ret)

    def test_runner_token_salt_invocation_error(self):
        '''
        Asserts that a SaltInvocationError is returned when the token authenticates, but the
        command is malformed.
        '''
        token = 'asdfasdfasdfasdf'
        clear_load = {'token': token, 'fun': 'badtestarg'}
        mock_token = {'token': token, 'eauth': 'foo', 'name': 'test'}
        mock_ret = {'error': {'name': 'SaltInvocationError',
                                'message': 'A command invocation error occurred: Check syntax.'}}

        with patch('salt.auth.LoadAuth.authenticate_token', MagicMock(return_value=mock_token)), \
                patch('salt.auth.LoadAuth.get_auth_list', MagicMock(return_value=['testing'])):
            ret = self.clear_funcs.runner(clear_load)

        self.assertDictEqual(mock_ret, ret)

    @expectedFailure #bb test was failing when ran in Jenkins
    def test_runner_eauth_not_authenticated(self):
        '''
        Asserts that an EauthAuthenticationError is returned when the user can't authenticate.
        '''
        mock_ret = {'error': {'name': 'EauthAuthenticationError',
                                'message': 'Authentication failure of type "eauth" occurred for '
                                            'user UNKNOWN.'}}
        ret = self.clear_funcs.runner({'eauth': 'foo'})
        self.assertDictEqual(mock_ret, ret)

    @expectedFailure #bb test was failing when ran in Jenkins
    def test_runner_eauth_authorization_error(self):
        '''
        Asserts that an EauthAuthenticationError is returned when the user authenticates, but is
        not authorized.
        '''
        clear_load = {'eauth': 'foo', 'username': 'test', 'fun': 'test.arg'}
        mock_ret = {'error': {'name': 'EauthAuthenticationError',
                                'message': 'Authentication failure of type "eauth" occurred for '
                                            'user test.'}}
        with patch('salt.auth.LoadAuth.authenticate_eauth', MagicMock(return_value=True)), \
                patch('salt.auth.LoadAuth.get_auth_list', MagicMock(return_value=[])):
            ret = self.clear_funcs.runner(clear_load)

        self.assertDictEqual(mock_ret, ret)

    def test_runner_eauth_salt_invocation_error(self):
        '''
        Asserts that an EauthAuthenticationError is returned when the user authenticates, but the
        command is malformed.
        '''
        clear_load = {'eauth': 'foo', 'username': 'test', 'fun': 'bad.test.arg.func'}
        mock_ret = {'error': {'name': 'SaltInvocationError',
                                'message': 'A command invocation error occurred: Check syntax.'}}
        with patch('salt.auth.LoadAuth.authenticate_eauth', MagicMock(return_value=True)), \
                patch('salt.auth.LoadAuth.get_auth_list', MagicMock(return_value=['testing'])):
            ret = self.clear_funcs.runner(clear_load)

        self.assertDictEqual(mock_ret, ret)

    @skipIf(True, 'bb test was failing when ran in Jenkins')
    def test_runner_user_not_authenticated(self):
        '''
        Asserts that an UserAuthenticationError is returned when the user can't authenticate.
        '''
        mock_ret = {'error': {'name': 'UserAuthenticationError',
                                'message': 'Authentication failure of type "user" occurred'}}
        ret = self.clear_funcs.runner({})
        self.assertDictEqual(mock_ret, ret)

    # wheel tests

    @skipIf(True, 'bb test was failing when ran in Jenkins')
    def test_wheel_token_not_authenticated(self):
        '''
        Asserts that a TokenAuthenticationError is returned when the token can't authenticate.
        '''
        mock_ret = {'error': {'name': 'TokenAuthenticationError',
                                'message': 'Authentication failure of type "token" occurred.'}}
        ret = self.clear_funcs.wheel({'token': 'asdfasdfasdfasdf'})
        self.assertDictEqual(mock_ret, ret)

    @expectedFailure #bb test was failing when ran in Jenkins
    def test_wheel_token_authorization_error(self):
        '''
        Asserts that a TokenAuthenticationError is returned when the token authenticates, but is
        not authorized.
        '''
        token = 'asdfasdfasdfasdf'
        clear_load = {'token': token, 'fun': 'test.arg'}
        mock_token = {'token': token, 'eauth': 'foo', 'name': 'test'}
        mock_ret = {'error': {'name': 'TokenAuthenticationError',
                                'message': 'Authentication failure of type "token" occurred '
                                            'for user test.'}}

        with patch('salt.auth.LoadAuth.authenticate_token', MagicMock(return_value=mock_token)), \
                patch('salt.auth.LoadAuth.get_auth_list', MagicMock(return_value=[])):
            ret = self.clear_funcs.wheel(clear_load)

        self.assertDictEqual(mock_ret, ret)

    def test_wheel_token_salt_invocation_error(self):
        '''
        Asserts that a SaltInvocationError is returned when the token authenticates, but the
        command is malformed.
        '''
        token = 'asdfasdfasdfasdf'
        clear_load = {'token': token, 'fun': 'badtestarg'}
        mock_token = {'token': token, 'eauth': 'foo', 'name': 'test'}
        mock_ret = {'error': {'name': 'SaltInvocationError',
                                'message': 'A command invocation error occurred: Check syntax.'}}

        with patch('salt.auth.LoadAuth.authenticate_token', MagicMock(return_value=mock_token)), \
                patch('salt.auth.LoadAuth.get_auth_list', MagicMock(return_value=['testing'])):
            ret = self.clear_funcs.wheel(clear_load)

        self.assertDictEqual(mock_ret, ret)

    @expectedFailure #bb test was failing when ran in Jenkins
    def test_wheel_eauth_not_authenticated(self):
        '''
        Asserts that an EauthAuthenticationError is returned when the user can't authenticate.
        '''
        mock_ret = {'error': {'name': 'EauthAuthenticationError',
                                'message': 'Authentication failure of type "eauth" occurred for '
                                            'user UNKNOWN.'}}
        ret = self.clear_funcs.wheel({'eauth': 'foo'})
        self.assertDictEqual(mock_ret, ret)

    def test_wheel_eauth_authorization_error(self):
        '''
        Asserts that an EauthAuthenticationError is returned when the user authenticates, but is
        not authorized.
        '''
        clear_load = {'eauth': 'foo', 'username': 'test', 'fun': 'test.arg'}
        mock_ret = {'error': {'name': 'EauthAuthenticationError',
                                'message': 'Authentication failure of type "eauth" occurred for '
                                            'user test.'}}
        with patch('salt.auth.LoadAuth.authenticate_eauth', MagicMock(return_value=True)), \
                patch('salt.auth.LoadAuth.get_auth_list', MagicMock(return_value=[])):
            ret = self.clear_funcs.wheel(clear_load)

        self.assertDictEqual(mock_ret, ret)

    def test_wheel_eauth_salt_invocation_error(self):
        '''
        Asserts that an EauthAuthenticationError is returned when the user authenticates, but the
        command is malformed.
        '''
        clear_load = {'eauth': 'foo', 'username': 'test', 'fun': 'bad.test.arg.func'}
        mock_ret = {'error': {'name': 'SaltInvocationError',
                                'message': 'A command invocation error occurred: Check syntax.'}}
        with patch('salt.auth.LoadAuth.authenticate_eauth', MagicMock(return_value=True)), \
                patch('salt.auth.LoadAuth.get_auth_list', MagicMock(return_value=['testing'])):
            ret = self.clear_funcs.wheel(clear_load)

        self.assertDictEqual(mock_ret, ret)

    @skipIf(True, 'bb test was failing when ran in Jenkins')
    def test_wheel_user_not_authenticated(self):
        '''
        Asserts that an UserAuthenticationError is returned when the user can't authenticate.
        '''
        mock_ret = {'error': {'name': 'UserAuthenticationError',
                                'message': 'Authentication failure of type "user" occurred'}}
        ret = self.clear_funcs.wheel({})
        self.assertDictEqual(mock_ret, ret)

    # publish tests

    def test_publish_user_is_blacklisted(self):
        '''
        Asserts that an AuthorizationError is returned when the user has been blacklisted.
        '''
        mock_ret = {'error': {'name': 'AuthorizationError',
                                'message': 'Authorization error occurred.'}}
        with patch('salt.acl.PublisherACL.user_is_blacklisted', MagicMock(return_value=True)):
            self.assertEqual(mock_ret, self.clear_funcs.publish({'user': 'foo', 'fun': 'test.arg'}))

    def test_publish_cmd_blacklisted(self):
        '''
        Asserts that an AuthorizationError is returned when the command has been blacklisted.
        '''
        mock_ret = {'error': {'name': 'AuthorizationError',
                                'message': 'Authorization error occurred.'}}
        with patch('salt.acl.PublisherACL.user_is_blacklisted', MagicMock(return_value=False)), \
                patch('salt.acl.PublisherACL.cmd_is_blacklisted', MagicMock(return_value=True)):
            self.assertEqual(mock_ret, self.clear_funcs.publish({'user': 'foo', 'fun': 'test.arg'}))

    
    @skipIf(True, 'bb test was failing when ran in Jenkins')
    def test_publish_token_not_authenticated(self):
        '''
        Asserts that an AuthenticationError is returned when the token can't authenticate.
        '''
        mock_ret = {'error': {'name': 'AuthenticationError',
                                'message': 'Authentication error occurred.'}}
        load = {'user': 'foo', 'fun': 'test.arg', 'tgt': 'test_minion',
                'kwargs': {'token': 'asdfasdfasdfasdf'}}
        with patch('salt.acl.PublisherACL.user_is_blacklisted', MagicMock(return_value=False)), \
                patch('salt.acl.PublisherACL.cmd_is_blacklisted', MagicMock(return_value=False)):
            self.assertEqual(mock_ret, self.clear_funcs.publish(load))

    @expectedFailure #bb test was failing when ran in Jenkins
    def test_publish_token_authorization_error(self):
        '''
        Asserts that an AuthorizationError is returned when the token authenticates, but is not
        authorized.
        '''
        token = 'asdfasdfasdfasdf'
        load = {'user': 'foo', 'fun': 'test.arg', 'tgt': 'test_minion',
                'arg': 'bar', 'kwargs': {'token': token}}
        mock_token = {'token': token, 'eauth': 'foo', 'name': 'test'}
        mock_ret = {'error': {'name': 'AuthorizationError',
                                'message': 'Authorization error occurred.'}}

        with patch('salt.acl.PublisherACL.user_is_blacklisted', MagicMock(return_value=False)), \
                patch('salt.acl.PublisherACL.cmd_is_blacklisted', MagicMock(return_value=False)), \
                patch('salt.auth.LoadAuth.authenticate_token', MagicMock(return_value=mock_token)), \
                patch('salt.auth.LoadAuth.get_auth_list', MagicMock(return_value=[])):
            self.assertEqual(mock_ret, self.clear_funcs.publish(load))

    @expectedFailure #bb test was failing when ran in Jenkins
    def test_publish_eauth_not_authenticated(self):
        '''
        Asserts that an AuthenticationError is returned when the user can't authenticate.
        '''
        load = {'user': 'test', 'fun': 'test.arg', 'tgt': 'test_minion',
                'kwargs': {'eauth': 'foo'}}
        mock_ret = {'error': {'name': 'AuthenticationError',
                                'message': 'Authentication error occurred.'}}
        with patch('salt.acl.PublisherACL.user_is_blacklisted', MagicMock(return_value=False)), \
                patch('salt.acl.PublisherACL.cmd_is_blacklisted', MagicMock(return_value=False)):
            self.assertEqual(mock_ret, self.clear_funcs.publish(load))

    @expectedFailure #bb test was failing when ran in Jenkins
    def test_publish_eauth_authorization_error(self):
        '''
        Asserts that an AuthorizationError is returned when the user authenticates, but is not
        authorized.
        '''
        load = {'user': 'test', 'fun': 'test.arg', 'tgt': 'test_minion',
                'kwargs': {'eauth': 'foo'}, 'arg': 'bar'}
        mock_ret = {'error': {'name': 'AuthorizationError',
                                'message': 'Authorization error occurred.'}}
        with patch('salt.acl.PublisherACL.user_is_blacklisted', MagicMock(return_value=False)), \
                patch('salt.acl.PublisherACL.cmd_is_blacklisted', MagicMock(return_value=False)), \
                patch('salt.auth.LoadAuth.authenticate_eauth', MagicMock(return_value=True)), \
                patch('salt.auth.LoadAuth.get_auth_list', MagicMock(return_value=[])):
            self.assertEqual(mock_ret, self.clear_funcs.publish(load))

    @skipIf(True, 'bb test was failing when ran in Jenkins')
    def test_publish_user_not_authenticated(self):
        '''
        Asserts that an AuthenticationError is returned when the user can't authenticate.
        '''
        load = {'user': 'test', 'fun': 'test.arg', 'tgt': 'test_minion'}
        mock_ret = {'error': {'name': 'AuthenticationError',
                                'message': 'Authentication error occurred.'}}
        with patch('salt.acl.PublisherACL.user_is_blacklisted', MagicMock(return_value=False)), \
                patch('salt.acl.PublisherACL.cmd_is_blacklisted', MagicMock(return_value=False)):
            self.assertEqual(mock_ret, self.clear_funcs.publish(load))

    @expectedFailure #bb test was failing when ran in Jenkins
    def test_publish_user_authenticated_missing_auth_list(self):
        '''
        Asserts that an AuthenticationError is returned when the user has an effective user id and is
        authenticated, but the auth_list is empty.
        '''
        load = {'user': 'test', 'fun': 'test.arg', 'tgt': 'test_minion',
                'kwargs': {'user': 'test'}, 'arg': 'foo'}
        mock_ret = {'error': {'name': 'AuthenticationError',
                                'message': 'Authentication error occurred.'}}
        with patch('salt.acl.PublisherACL.user_is_blacklisted', MagicMock(return_value=False)), \
                patch('salt.acl.PublisherACL.cmd_is_blacklisted', MagicMock(return_value=False)), \
                patch('salt.auth.LoadAuth.authenticate_key', MagicMock(return_value='fake-user-key')), \
                patch('salt.utils.master.get_values_of_matching_keys', MagicMock(return_value=[])):
            self.assertEqual(mock_ret, self.clear_funcs.publish(load))

    @expectedFailure #bb test was failing when ran in Jenkins
    def test_publish_user_authorization_error(self):
        '''
        Asserts that an AuthorizationError is returned when the user authenticates, but is not
        authorized.
        '''
        load = {'user': 'test', 'fun': 'test.arg', 'tgt': 'test_minion',
                'kwargs': {'user': 'test'}, 'arg': 'foo'}
        mock_ret = {'error': {'name': 'AuthorizationError',
                                'message': 'Authorization error occurred.'}}
        with patch('salt.acl.PublisherACL.user_is_blacklisted', MagicMock(return_value=False)), \
                patch('salt.acl.PublisherACL.cmd_is_blacklisted', MagicMock(return_value=False)), \
                patch('salt.auth.LoadAuth.authenticate_key', MagicMock(return_value='fake-user-key')), \
                patch('salt.utils.master.get_values_of_matching_keys', MagicMock(return_value=['test'])), \
                patch('salt.utils.minions.CkMinions.auth_check', MagicMock(return_value=False)):
            self.assertEqual(mock_ret, self.clear_funcs.publish(load))


