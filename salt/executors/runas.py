# -*- coding: utf-8 -*-
"""
Runas executor module
"""
# Import python libs
from __future__ import absolute_import, print_function, unicode_literals
import functools
import logging

# Import salt libs
import salt.log.setup
import salt.utils.json
import salt.utils.path
import salt.utils.process
import salt.syspaths

from salt.ext import six
from salt.ext.six.moves import shlex_quote as _cmd_quote

log = logging.getLogger(__name__)

__virtualname__ = "runas"


def __virtual__():
    return __virtualname__


def _chugid_then_run(user, group, umask, pipe, func, args, kwargs):
    try:
        # QueueHandler should be sufficient
        salt.log.setup.shutdown_logfile_logging()

        salt.utils.user.chugid_and_umask(user, umask, group)
        ret = func(*args, **kwargs)
        return pipe.send((ret,))
    except Exception as e:
        import traceback

        tb = traceback.format_exc()
        pipe.send((e, traceback.format_exc()))


def execute(opts, data, func, args, kwargs):
    """
    Allow for the calling of execution modules via a specified user.

    Any execution module call done by the minion will be run under the given user with
    all privileges dropped from the level salt-minion runs as.
    Behavior differs depending on os:
    for POSIX operating systems, os.setuid and os.setgid are used, unless a 'strategy'
    executor-opt is provided with the value 'salt-call', then the same approach as windows
    is used.
    On Windows, salt-call will be invoked with runas functionality to drop privileges.
    The reason for this difference is performance and correctness, in some topologies
    salt-call isn't strictly equivalent to an in-process execution of a minion
    (i.e. multimaster).

    .. note::

        In order for this executor to work the minion pki dir must be readable
        by the target user, and the cache dir must be writable. When using the
        salt-call strategy, the minion log must also be writeable. The usual
        security caveats about trust with exposing these entities to the target
        user applies.

    '''
    .. code-block:: bash

        salt --module-executors='runas' --executor-opts='{user: op}' '*' pkg.version cowsay

    """

    if data.get("executor_opts", {}).get("user"):
        user = data["executor_opts"]["user"]
    else:
        raise ValueError("user must be specified in executor_opts")

    group = data.get("executor_opts", {}).get("group")
    umask = data.get("executor_opts", {}).get("umask")
    strategy = data.get("executor_opts", {}).get("strategy")

    # this isnt ideal, but I don't think a better way in windows exists
    if salt.utils.platform.is_windows():
        if group or umask:
            raise ValueError("group and umask are not supported on windows")
    elif not group:
        group = salt.utils.user.get_default_group(user)

    log.info("runas: attempting to drop to: '%s'", data.get("executor_opts"))

    if data["fun"] in ("state.sls", "state.highstate", "state.apply"):
        kwargs["concurrent"] = True

    if salt.utils.platform.is_windows() or strategy == "salt-call":
        cmd = [
            "salt-call",
            "--out",
            "json",
            "--metadata",
            "-c",
            opts.get("config_dir"),
            "--",
            data["fun"],
        ]

        for arg in args:
            cmd.append(
                _cmd_quote(six.text_type(arg))
            )  # matt note, test this on windows
        for key in kwargs:
            cmd.append(_cmd_quote("{0}={1}".format(key, kwargs[key])))

        cmd_ret = __salt__["cmd.run_all"](cmd, python_shell=False, runas=user)

        if cmd_ret["retcode"] == 0:
            cmd_meta = salt.utils.json.loads(cmd_ret["stdout"])["local"]
            ret = cmd_meta["return"]
            __context__["retcode"] = cmd_meta.get("retcode", 0)
        else:
            ret = cmd_ret["stderr"]
            __context__["retcode"] = cmd_ret["retcode"]

        return ret
    else:
        parent_conn, child_conn = salt.utils.process.Pipe()

        proc = salt.utils.process.MultiprocessingProcess(
            target=_chugid_then_run,
            args=(user, group, umask, child_conn, func, args, kwargs),
            name='salt.utils.executors.runas',
        )
        proc.start()
        ret = parent_conn.recv()
        proc.join()

        if isinstance(ret[0], Exception):
            log.debug('runas: received Exception in child process. child traceback: %s', ret[1])
            raise(ret[0])
        else:
            return ret[0]
