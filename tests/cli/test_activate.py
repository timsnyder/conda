# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function, unicode_literals

import os
from os.path import dirname, join
import subprocess
import sys
import tempfile

import pytest

from conda.base.context import context
from conda.cli.activate import _get_prefix_paths, binpath_from_arg
from conda.compat import TemporaryDirectory
from conda.config import root_dir
from conda.gateways.disk.create import mkdir_p
from conda.gateways.disk.update import touch
from conda.install import symlink_conda
from conda.utils import on_win, shells, translate_stream, unix_path_to_win
from tests.helpers import assert_equals, assert_in, assert_not_in

# ENVS_PREFIX = "envs" if PY2 else "envsßôç"
ENVS_PREFIX = "envs"


def gen_test_env_paths(envs, shell, num_test_folders=5):
    """People need not use all the test folders listed here.
    This is only for shortening the environment string generation.

    Also encapsulates paths in double quotes.
    """
    paths = [os.path.join(envs, "test {}".format(test_folder+1)) for test_folder in range(num_test_folders)]
    for path in paths[:2]:
        # These tests assume only the first two paths can be activated
        # Create symlinks ONLY for the first two folders.
        symlink_conda(path, sys.prefix, shell)
        mkdir_p(join(path, 'conda-meta'))
        touch(join(path, 'conda-meta', 'history'))
    converter = shells[shell]["path_to"]
    paths = [converter(path) for path in paths]
    return paths


def _envpaths(env_root, env_name="", shell=None):
    """Supply the appropriate platform executable folders.  rstrip on root removes
       trailing slash if env_name is empty (the default)

    Assumes that any prefix used here exists.  Will not work on prefixes that don't.
    """
    sep = shells[shell]['sep']
    return binpath_from_arg(sep.join([env_root, env_name]), shell)


PYTHONPATH = os.path.dirname(os.path.dirname(__file__))

# Make sure the subprocess activate calls this python
syspath = os.pathsep.join(_get_prefix_paths(context.root_prefix))


def make_win_ok(path):
    if on_win:
        return unix_path_to_win(path)
    else:
        return path


def print_ps1(env_dirs, raw_ps, number):
    return u"(%s) %s" % (make_win_ok(env_dirs[number]), raw_ps)


CONDA_ENTRY_POINT = """\
#!{syspath}/python
import sys
from conda.cli import main

sys.exit(main())
"""

def raw_string(s):
    if isinstance(s, str):
        s = s.encode('string-escape')
    elif isinstance(s, unicode):
        s = s.encode('unicode-escape')
    return s

def strip_leading_library_bin(path_string, shelldict):
    entries = path_string.split(shelldict['pathsep'])
    if "library{}bin".format(shelldict['sep']) in entries[0].lower():
        entries = entries[1:]
    return shelldict['pathsep'].join(entries)


def _format_vars(shell):
    shelldict = shells[shell]

    base_path, _ = run_in(shelldict['printpath'], shell)
    # windows forces Library/bin onto PATH when starting up.  Strip it for the purposes of this test.
    if on_win:
        base_path = strip_leading_library_bin(base_path, shelldict)

    raw_ps, _ = run_in(shelldict["printps1"], shell)

    command_setup = """\
{set} PYTHONPATH="{PYTHONPATH}"
{set} CONDARC=
{set} CONDA_PATH_BACKUP=
""".format(here=dirname(__file__), PYTHONPATH=shelldict['path_to'](PYTHONPATH),
           set=shelldict["set_var"])
    if shelldict["shell_suffix"] == '.bat':
        command_setup = "@echo off\n" + command_setup

    return {
        'echo': shelldict['echo'],
        'nul': shelldict['nul'],
        'printpath': shelldict['printpath'],
        'printdefaultenv': shelldict['printdefaultenv'],
        'printps1': shelldict['printps1'],
        'raw_ps': raw_ps,
        'set_var': shelldict['set_var'],
        'source': shelldict['source_setup'],
        'binpath': shelldict['binpath'],
        'shell_suffix': shelldict['shell_suffix'],
        'syspath': shelldict['path_to'](sys.prefix),
        'command_setup': command_setup,
        'base_path': base_path,
}


# @pytest.fixture(scope="module")
# def bash_profile(request):
#     # profile=os.path.join(os.path.expanduser("~"), ".bash_profile")
#     # if os.path.isfile(profile):
#     #     os.rename(profile, profile+"_backup")
#     # with open(profile, "w") as f:
#     #     f.write("export PS1=test_ps1\n")
#     #     f.write("export PROMPT=test_ps1\n")
#     # def fin():
#     #     if os.path.isfile(profile+"_backup"):
#     #         os.remove(profile)
#     #         os.rename(profile+"_backup", profile)
#     # request.addfinalizer(fin)
#     return request  # provide the fixture value


@pytest.mark.installed
def test_activate_test1(shell):
    shell_vars = _format_vars(shell)
    with TemporaryDirectory(prefix=ENVS_PREFIX, dir=dirname(__file__)) as envs:
        commands = (shell_vars['command_setup'] + """
        {source} "{syspath}{binpath}activate{shell_suffix}" "{env_dirs[0]}"
        {printpath}
        """).format(envs=envs, env_dirs=gen_test_env_paths(envs, shell), **shell_vars)

        stdout, stderr = run_in(commands, shell)
        assert_in(shells[shell]['pathsep'].join(_envpaths(envs, 'test 1', shell)),
                 stdout, shell)


@pytest.mark.installed
def test_activate_env_from_env_with_root_activate(shell):
    shell_vars = _format_vars(shell)
    with TemporaryDirectory(prefix=ENVS_PREFIX, dir=dirname(__file__)) as envs:
        commands = (shell_vars['command_setup'] + """
        {source} "{syspath}{binpath}activate" "{env_dirs[0]}" {nul}
        {source} "{syspath}{binpath}activate" "{env_dirs[1]}"
        {printpath}
        """).format(envs=envs, env_dirs=gen_test_env_paths(envs, shell), **shell_vars)

        stdout, stderr = run_in(commands, shell)
        assert_in(shells[shell]['pathsep'].join(_envpaths(envs, 'test 2', shell)), stdout)


@pytest.mark.installed
def test_activate_bad_directory(shell):
    shell_vars = _format_vars(shell)
    with TemporaryDirectory(prefix=ENVS_PREFIX, dir=dirname(__file__)) as envs:
        env_dirs = gen_test_env_paths(envs, shell)
        # Strange semicolons are here to defeat MSYS' automatic path conversion.
        #   See http://www.mingw.org/wiki/Posix_path_conversion
        commands = (shell_vars['command_setup'] + """
        {source} "{syspath}{binpath}activate" "{env_dirs[2]}"
        {printpath}
        """).format(envs=envs, env_dirs=env_dirs, **shell_vars)
        stdout, stderr = run_in(commands, shell)
        # another semicolon here for comparison reasons with one above.
        assert 'could not find conda environment' in stderr.lower() or 'not a conda environment' in stderr.lower()
        assert_not_in(env_dirs[2], stdout)


@pytest.mark.installed
def test_activate_bad_env_keeps_existing_good_env(shell):
    shell_vars = _format_vars(shell)
    with TemporaryDirectory(prefix=ENVS_PREFIX, dir=dirname(__file__)) as envs:
        commands = (shell_vars['command_setup'] + """
        {source} {syspath}{binpath}activate "{env_dirs[0]}" {nul}
        {source} "{syspath}{binpath}activate" "{env_dirs[2]}"
        {printpath}
        """).format(envs=envs, env_dirs=gen_test_env_paths(envs, shell), **shell_vars)

        stdout, stderr = run_in(commands, shell)
        assert_in(shells[shell]['pathsep'].join(_envpaths(envs, 'test 1', shell)),stdout)


@pytest.mark.installed
def test_activate_deactivate(shell):
    # if shell == "bash.exe" and datetime.now() < datetime(2017, 5, 1):
    #     pytest.xfail("fix this soon")
    shell_vars = _format_vars(shell)
    with TemporaryDirectory(prefix=ENVS_PREFIX, dir=dirname(__file__)) as envs:
        commands = (shell_vars['command_setup'] + """
        {source} "{syspath}{binpath}activate" "{env_dirs[0]}" {nul}
        {source} "{syspath}{binpath}deactivate"
        {printpath}
        """).format(envs=envs, env_dirs=gen_test_env_paths(envs, shell), **shell_vars)

        stdout, stderr = run_in(commands, shell)
        stdout = strip_leading_library_bin(stdout, shells[shell])
        assert_equals(stdout, u"%s" % shell_vars['base_path'])


@pytest.mark.installed
def test_activate_root_simple(shell):
    # if shell == "bash.exe" and datetime.now() < datetime(2017, 5, 1):
    #     pytest.xfail("fix this soon")
    shell_vars = _format_vars(shell)
    with TemporaryDirectory(prefix=ENVS_PREFIX, dir=dirname(__file__)) as envs:
        commands = (shell_vars['command_setup'] + """
        {source} "{syspath}{binpath}activate" root
        {printpath}
        """).format(envs=envs, **shell_vars)

        stdout, stderr = run_in(commands, shell)
        assert_in(shells[shell]['pathsep'].join(_envpaths(root_dir, shell=shell)), stdout, stderr)

        commands = (shell_vars['command_setup'] + """
        {source} "{syspath}{binpath}activate" root
        {source} "{syspath}{binpath}deactivate"
        {printpath}
        """).format(envs=envs, **shell_vars)

        stdout, stderr = run_in(commands, shell)
        stdout = strip_leading_library_bin(stdout, shells[shell])
        assert_equals(stdout, u"%s" % shell_vars['base_path'])


# @pytest.mark.installed
# @pytest.mark.skip(reason="Test no longer relevant. Two envs activate at once is fine.")
# def test_activate_root_env_from_other_env(shell):
#     shell_vars = _format_vars(shell)
#     with TemporaryDirectory(prefix=ENVS_PREFIX, dir=dirname(__file__)) as envs:
#         commands = (shell_vars['command_setup'] + """
#         {source} "{syspath}{binpath}activate" "{env_dirs[0]}" {nul}
#         {source} "{syspath}{binpath}activate" root
#         {printpath}
#         """).format(envs=envs, env_dirs=gen_test_env_paths(envs, shell), **shell_vars)
#
#         stdout, stderr = run_in(commands, shell)
#         assert_in(shells[shell]['pathsep'].join(_envpaths(root_dir, shelldict=shells[shell])),
#                   stdout)
#         assert_not_in(shells[shell]['pathsep'].join(_envpaths(envs, 'test 1', shelldict=shells[shell])), stdout)


@pytest.mark.installed
def test_wrong_args(shell):
    shell_vars = _format_vars(shell)
    with TemporaryDirectory(prefix=ENVS_PREFIX, dir=dirname(__file__)) as envs:
        commands = (shell_vars['command_setup'] + """
        {source} "{syspath}{binpath}activate" two args
        {printpath}
        """).format(envs=envs, **shell_vars)

        stdout, stderr = run_in(commands, shell)
        stdout = strip_leading_library_bin(stdout, shells[shell])
        assert_in("activate only accepts a single argument", stderr)
        assert_equals(stdout, shell_vars['base_path'], stderr)


@pytest.mark.installed
def test_activate_help(shell):
    shell_vars = _format_vars(shell)
    with TemporaryDirectory(prefix=ENVS_PREFIX, dir=dirname(__file__)) as envs:
        if shell not in ['powershell.exe', 'cmd.exe']:
            commands = (shell_vars['command_setup'] + """
            "{syspath}{binpath}activate" Zanzibar
            """).format(envs=envs, **shell_vars)
            stdout, stderr = run_in(commands, shell)
            assert_equals(stdout, '')
            assert_in("activate must be sourced", stderr)
            # assert_in("Usage: source activate ENV", stderr)

        commands = (shell_vars['command_setup'] + """
        {source} "{syspath}{binpath}activate" --help
        """).format(envs=envs, **shell_vars)

        stdout, stderr = run_in(commands, shell)
        assert_equals(stdout, '')

        if shell in ["cmd.exe", "powershell"]:
            # assert_in("Usage: activate ENV", stderr)
            pass
        else:
            # assert_in("Usage: source activate ENV", stderr)

            commands = (shell_vars['command_setup'] + """
            {syspath}{binpath}deactivate
            """).format(envs=envs, **shell_vars)
            stdout, stderr = run_in(commands, shell)
            assert_equals(stdout, '')
            assert_in("deactivate must be sourced", stderr)
            # assert_in("Usage: source deactivate", stderr)

        commands = (shell_vars['command_setup'] + """
        {source} {syspath}{binpath}deactivate --help
        """).format(envs=envs, **shell_vars)
        stdout, stderr = run_in(commands, shell)
        assert_equals(stdout, '')
        # if shell in ["cmd.exe", "powershell"]:
        #     assert_in("Usage: deactivate", stderr)
        # else:
        #     assert_in("Usage: source deactivate", stderr)


# @pytest.mark.skip(reason="Test no longer relevant. Symlinking stops in conda 4.4.0.")
# @pytest.mark.installed
# def test_activate_symlinking(shell):
#     """Symlinks or bat file redirects are created at activation time.  Make sure that the
#     files/links exist, and that they point where they should."""
#     shell_vars = _format_vars(shell)
#     with TemporaryDirectory(prefix=ENVS_PREFIX, dir=dirname(__file__)) as envs:
#         where = 'Scripts' if on_win else 'bin'
#         for env in gen_test_env_paths(envs, shell)[:2]:
#             scripts = ["conda", "activate", "deactivate"]
#             for f in scripts:
#                 if on_win:
#                     file_path = os.path.join(env, where, f + shells[shell]["shell_suffix"])
#                     # must translate path to windows representation for Python's sake
#                     file_path = shells[shell]["path_from"](file_path)
#                     assert(os.path.lexists(file_path))
#                 else:
#                     file_path = os.path.join(env, where, f)
#                     assert(os.path.lexists(file_path))
#                     s = os.lstat(file_path)
#                     assert(stat.S_ISLNK(s.st_mode))
#                     assert(os.readlink(file_path) == '{root_path}'.format(root_path=os.path.join(sys.prefix, where, f)))
#
#         if platform != 'win':
#             # Test activate when there are no write permissions in the
#             # env.
#             prefix_bin_path = os.path.join(gen_test_env_paths(envs, shell)[2], 'bin')
#             commands = (shell_vars['command_setup'] + """
#             mkdir -p "{prefix_bin_path}"
#             chmod 444 "{prefix_bin_path}"
#             {source} "{syspath}{binpath}activate" "{env_dirs[2]}"
#             """).format(prefix_bin_path=prefix_bin_path, envs=envs,
#                                 env_dirs=gen_test_env_paths(envs, shell),
#                 **shell_vars)
#             stdout, stderr = run_in(commands, shell)
#             assert_in("not have write access", stderr)
#
#             # restore permissions so the dir will get cleaned up
#             run_in('chmod 777 "{prefix_bin_path}"'.format(prefix_bin_path=prefix_bin_path), shell)


@pytest.mark.installed
def test_PS1_changeps1(shell):  # , bash_profile
    shell_vars = _format_vars(shell)
    with TemporaryDirectory(prefix=ENVS_PREFIX, dir=dirname(__file__)) as envs:
        # activate changes PS1 correctly
        commands = (shell_vars['command_setup'] + """
        {source} "{syspath}{binpath}activate" "{env_dirs[0]}"
        {printps1}
        """).format(envs=envs, env_dirs=gen_test_env_paths(envs, shell), **shell_vars)
        stdout, stderr = run_in(commands, shell)
        assert_equals(stdout.strip(), print_ps1(env_dirs=gen_test_env_paths(envs, shell),
                                        raw_ps=shell_vars["raw_ps"], number=0).strip(), stderr)

        # second activate replaces earlier activated env PS1
        commands = (shell_vars['command_setup'] + """
        {source} "{syspath}{binpath}activate" "{env_dirs[0]}" {nul}
        {source} "{syspath}{binpath}activate" "{env_dirs[1]}"
        {printps1}
        """).format(envs=envs, env_dirs=gen_test_env_paths(envs, shell), **shell_vars)
        stdout, sterr = run_in(commands, shell)
        assert_equals(stdout.strip(), print_ps1(env_dirs=gen_test_env_paths(envs, shell),
                                        raw_ps=shell_vars["raw_ps"], number=1).strip(), stderr)

        # failed activate does not touch raw PS1
        commands = (shell_vars['command_setup'] + """
        {source} "{syspath}{binpath}activate" "{env_dirs[2]}"
        {printps1}
        """).format(envs=envs, env_dirs=gen_test_env_paths(envs, shell), **shell_vars)
        stdout, stderr = run_in(commands, shell)
        assert_equals(stdout, shell_vars['raw_ps'], stderr)

        # ensure that a failed activate does not touch PS1 (envs[3] folders do not exist.)
        commands = (shell_vars['command_setup'] + """
        {source} "{syspath}{binpath}activate" "{env_dirs[0]}" {nul}
        {source} "{syspath}{binpath}activate" "{env_dirs[2]}"
        {printps1}
        """).format(envs=envs, env_dirs=gen_test_env_paths(envs, shell), **shell_vars)
        stdout, stderr = run_in(commands, shell)
        assert_equals(stdout.strip(), print_ps1(env_dirs=gen_test_env_paths(envs, shell),
                                        raw_ps=shell_vars["raw_ps"], number=0).strip(), stderr)

        # deactivate doesn't do anything bad to PS1 when no env active to deactivate
        commands = (shell_vars['command_setup'] + """
        {source} {syspath}{binpath}deactivate
        {printps1}
        """).format(envs=envs, **shell_vars)
        stdout, stderr = run_in(commands, shell)
        assert_equals(stdout, shell_vars['raw_ps'], stderr)

        # deactivate script in activated env returns us to raw PS1
        commands = (shell_vars['command_setup'] + """
        {source} "{syspath}{binpath}activate" "{env_dirs[0]}" {nul}
        {source} "{env_dirs[0]}{binpath}deactivate"
        {printps1}
        """).format(envs=envs, env_dirs=gen_test_env_paths(envs, shell), **shell_vars)
        stdout, stderr = run_in(commands, shell)
        assert_equals(stdout, shell_vars['raw_ps'], stderr)

        # make sure PS1 is unchanged by faulty activate input
        commands = (shell_vars['command_setup'] + """
        {source} "{syspath}{binpath}activate" two args
        {printps1}
        """).format(envs=envs, **shell_vars)
        stdout, stderr = run_in(commands, shell)
        assert_equals(stdout, shell_vars['raw_ps'], stderr)


@pytest.mark.installed
def test_PS1_no_changeps1(shell):  # , bash_profile
    """Ensure that people's PS1 remains unchanged if they have that setting in their RC file."""
    shell_vars = _format_vars(shell)
    with TemporaryDirectory(prefix=ENVS_PREFIX, dir=dirname(__file__)) as envs:
        rc_file = os.path.join(envs, ".condarc")
        with open(rc_file, 'w') as f:
            f.write("changeps1: False\n")
        condarc = "{set_var}CONDARC=%s\n" % rc_file
        commands = (shell_vars['command_setup'] + condarc + """
        {source} "{syspath}{binpath}activate" "{env_dirs[0]}"
        {printps1}
        """).format(envs=envs, env_dirs=gen_test_env_paths(envs, shell), **shell_vars)
        stdout, stderr = run_in(commands, shell)
        assert_equals(stdout, shell_vars['raw_ps'], stderr)

        commands = (shell_vars['command_setup'] + condarc + """
        {source} "{syspath}{binpath}activate" "{env_dirs[0]}" {nul}
        {source} "{syspath}{binpath}activate" "{env_dirs[1]}"
        {printps1}
        """).format(envs=envs, env_dirs=gen_test_env_paths(envs, shell), **shell_vars)
        stdout, stderr = run_in(commands, shell)
        assert_equals(stdout, shell_vars['raw_ps'], stderr)

        commands = (shell_vars['command_setup'] + condarc + """
        {source} "{syspath}{binpath}activate" "{env_dirs[2]}"
        {printps1}
        """).format(envs=envs, env_dirs=gen_test_env_paths(envs, shell), **shell_vars)
        stdout, stderr = run_in(commands, shell)
        assert_equals(stdout, shell_vars['raw_ps'], stderr)

        commands = (shell_vars['command_setup'] + condarc + """
        {source} "{syspath}{binpath}activate" "{env_dirs[0]}" {nul}
        {source} "{syspath}{binpath}activate" "{env_dirs[2]}"
        {printps1}
        """).format(envs=envs, env_dirs=gen_test_env_paths(envs, shell), **shell_vars)
        stdout, stderr = run_in(commands, shell)
        assert_equals(stdout, shell_vars['raw_ps'], stderr)

        commands = (shell_vars['command_setup'] + condarc + """
        {source} "{syspath}{binpath}activate" "{env_dirs[0]}" {nul}
        {source} "{env_dirs[0]}{binpath}deactivate"
        {printps1}
        """).format(envs=envs, env_dirs=gen_test_env_paths(envs, shell), **shell_vars)
        stdout, stderr = run_in(commands, shell)
        assert_equals(stdout, shell_vars['raw_ps'], stderr)

        commands = (shell_vars['command_setup'] + condarc + """
        {source} "{syspath}{binpath}activate" two args
        {printps1}
        """).format(envs=envs, **shell_vars)
        stdout, stderr = run_in(commands, shell)
        assert_equals(stdout, shell_vars['raw_ps'], stderr)


@pytest.mark.installed
def test_CONDA_DEFAULT_ENV(shell):
    shell_vars = _format_vars(shell)
    with TemporaryDirectory(prefix=ENVS_PREFIX, dir=dirname(__file__)) as envs:
        env_dirs=gen_test_env_paths(envs, shell)
        commands = (shell_vars['command_setup'] + """
        {source} "{syspath}{binpath}activate" "{env_dirs[0]}"
        {printdefaultenv}
        """).format(envs=envs, env_dirs=env_dirs, **shell_vars)
        stdout, stderr = run_in(commands, shell)
        assert_equals(stdout.rstrip(), make_win_ok(env_dirs[0]), stderr)

        commands = (shell_vars['command_setup'] + """
        {source} "{syspath}{binpath}activate" "{env_dirs[0]}" {nul}
        {source} "{syspath}{binpath}activate" "{env_dirs[1]}"
        {printdefaultenv}
        """).format(envs=envs, env_dirs=env_dirs, **shell_vars)
        stdout, stderr = run_in(commands, shell)
        assert_equals(stdout.rstrip(), make_win_ok(env_dirs[1]), stderr)

        commands = (shell_vars['command_setup'] + """
        {source} "{syspath}{binpath}activate" "{env_dirs[2]}"
        {printdefaultenv}
        """).format(envs=envs, env_dirs=gen_test_env_paths(envs, shell), **shell_vars)
        stdout, stderr = run_in(commands, shell)
        assert_equals(stdout, '', stderr)

        commands = (shell_vars['command_setup'] + """
        {source} "{syspath}{binpath}activate" "{env_dirs[0]}" {nul}
        {source} "{syspath}{binpath}activate" "{env_dirs[2]}"
        {printdefaultenv}
        """).format(envs=envs, env_dirs=gen_test_env_paths(envs, shell), **shell_vars)
        stdout, stderr = run_in(commands, shell)
        assert_equals(stdout.rstrip(), make_win_ok(env_dirs[0]), stderr)

        commands = (shell_vars['command_setup'] + """
        {source} {syspath}{binpath}deactivate
        {printdefaultenv}
        """).format(envs=envs, env_dirs=gen_test_env_paths(envs, shell), **shell_vars)
        stdout, stderr = run_in(commands, shell)
        assert_equals(stdout, '', stderr)

        commands = (shell_vars['command_setup'] + """
        {source} "{syspath}{binpath}activate" "{env_dirs[0]}" {nul}
        {source} "{env_dirs[0]}{binpath}deactivate"
        {printdefaultenv}
        """).format(envs=envs, env_dirs=gen_test_env_paths(envs, shell), **shell_vars)
        stdout, stderr = run_in(commands, shell)
        assert_equals(stdout, '', stderr)

        commands = (shell_vars['command_setup'] + """
        {source} "{syspath}{binpath}activate" two args
        {printdefaultenv}
        """).format(envs=envs, **shell_vars)
        stdout, stderr = run_in(commands, shell)
        assert_equals(stdout, '', stderr)

        commands = (shell_vars['command_setup'] + """
        {source} "{syspath}{binpath}activate" root {nul}
        {printdefaultenv}
        """).format(envs=envs, **shell_vars)
        stdout, stderr = run_in(commands, shell)
        assert_equals(stdout.rstrip(), 'root', stderr)

        commands = (shell_vars['command_setup'] + """
        {source} "{syspath}{binpath}activate" root {nul}
        {source} "{env_dirs[0]}{binpath}deactivate" {nul}
        {printdefaultenv}
        """).format(envs=envs, env_dirs=gen_test_env_paths(envs, shell), **shell_vars)
        stdout, stderr = run_in(commands, shell)
        assert_equals(stdout, '', stderr)


@pytest.mark.installed
def test_activate_from_env(shell):
    """Tests whether the activate bat file or link in the activated environment works OK"""
    shell_vars = _format_vars(shell)
    with TemporaryDirectory(prefix=ENVS_PREFIX, dir=dirname(__file__)) as envs:
        env_dirs=gen_test_env_paths(envs, shell)
        commands = (shell_vars['command_setup'] + """
        {source} "{syspath}{binpath}activate" "{env_dirs[0]}"
        {source} "{env_dirs[0]}{binpath}activate" "{env_dirs[1]}"
        {printdefaultenv}
        """).format(envs=envs, env_dirs=env_dirs, **shell_vars)
        stdout, stderr = run_in(commands, shell)
        # rstrip on output is because the printing to console picks up an extra space
        assert_equals(stdout.rstrip(), make_win_ok(env_dirs[1]), stderr)


@pytest.mark.installed
def test_deactivate_from_env(shell):
    """Tests whether the deactivate bat file or link in the activated environment works OK"""
    shell_vars = _format_vars(shell)
    with TemporaryDirectory(prefix=ENVS_PREFIX, dir=dirname(__file__)) as envs:
        commands = (shell_vars['command_setup'] + """
        {source} "{syspath}{binpath}activate" "{env_dirs[0]}"
        {source} "{env_dirs[0]}{binpath}deactivate"
        {printdefaultenv}
        """).format(envs=envs, env_dirs=gen_test_env_paths(envs, shell), **shell_vars)
        stdout, stderr = run_in(commands, shell)
        assert_equals(stdout, u'', stderr)


@pytest.mark.installed
def test_activate_relative_path(shell):
    """
    current directory should be searched for environments
    """
    shell_vars = _format_vars(shell)
    with TemporaryDirectory(prefix=ENVS_PREFIX, dir=dirname(__file__)) as envs:
        env_dirs = gen_test_env_paths(envs, shell)
        env_dir = os.path.basename(env_dirs[0])
        work_dir = os.path.dirname(env_dir)
        commands = (shell_vars['command_setup'] + """
        cd {work_dir}
        {source} "{syspath}{binpath}activate" "{env_dir}"
        {printdefaultenv}
        """).format(work_dir=envs, envs=envs, env_dir=env_dir, **shell_vars)
        cwd = os.getcwd()
        # this is not effective for running bash on windows.  It starts
        #    in your home dir no matter what.  That's what the cd is for above.
        os.chdir(envs)
        try:
            stdout, stderr = run_in(commands, shell, cwd=envs)
        except:
            raise
        finally:
            os.chdir(cwd)
        if shell == 'cmd.exe':
            assert_equals(stdout.rstrip(), env_dir, stderr)
        else:
            assert_equals(stdout.rstrip(), make_win_ok(env_dirs[0]), stderr)


@pytest.mark.skipif(not on_win, reason="only relevant on windows")
def test_activate_does_not_leak_echo_setting(shell):
    """Test that activate's setting of echo to off does not disrupt later echo calls"""

    if not on_win or shell != "cmd.exe":
        pytest.skip("test only relevant for cmd.exe on win")
    shell_vars = _format_vars(shell)
    with TemporaryDirectory(prefix=ENVS_PREFIX, dir=dirname(__file__)) as envs:
        commands = (shell_vars['command_setup'] + """
        @echo on
        @call "{syspath}{binpath}activate.bat" "{env_dirs[0]}"
        @echo
        """).format(envs=envs, env_dirs=gen_test_env_paths(envs, shell), **shell_vars)
        stdout, stderr = run_in(commands, shell)
        assert_equals(stdout, u'ECHO is on.', stderr)


@pytest.mark.skip(reason="need to get 4.4. alpha outs")
@pytest.mark.installed
def test_activate_non_ascii_char_in_path(shell):
    shell_vars = _format_vars(shell)
    with TemporaryDirectory(prefix='Ånvs', dir=dirname(__file__)) as envs:
        commands = (shell_vars['command_setup'] + """
        {source} "{syspath}{binpath}activate" "{env_dirs[0]}"
        {source} "{env_dirs[0]}{binpath}deactivate"
        {printdefaultenv}.
        """).format(envs=envs, env_dirs=gen_test_env_paths(envs, shell), **shell_vars)

        stdout, stderr = run_in(commands, shell)

        if shell == 'cmd.exe':
            assert_equals(stdout, u'', stderr)
        else:
            assert_equals(stdout, u'.', stderr)


@pytest.mark.installed
def test_activate_has_extra_env_vars(shell):
    """Test that environment variables in activate.d show up when activated"""
    shell_vars = _format_vars(shell)
    with TemporaryDirectory(prefix=ENVS_PREFIX, dir=dirname(__file__)) as envs:
        env_dirs=gen_test_env_paths(envs, shell)
        for path in ["activate", "deactivate"]:
            dir = os.path.join(shells[shell]['path_from'](env_dirs[0]), "etc", "conda", "%s.d" % path)
            os.makedirs(dir)
            file = os.path.join(dir, "test" + shells[shell]["env_script_suffix"])
            setting = "test" if path == "activate" else ""
            with open(file, 'w') as f:
                f.write(shells[shell]["set_var"] + "TEST_VAR=%s\n" % setting)
        commands = (shell_vars['command_setup'] + """
        {source} "{syspath}{binpath}activate" "{env_dirs[0]}"
        {echo} {var}
        """).format(envs=envs, env_dirs=env_dirs, var=shells[shell]["var_format"].format("TEST_VAR"), **shell_vars)
        stdout, stderr = run_in(commands, shell)
        assert_equals(stdout, u'test', stderr)

        # Make sure the variable is reset after deactivation

        commands = (shell_vars['command_setup'] + """
        {source} "{syspath}{binpath}activate" "{env_dirs[0]}"
        {source} "{env_dirs[0]}{binpath}deactivate"
        {echo} {var}.
        """).format(envs=envs, env_dirs=env_dirs, var=shells[shell]["var_format"].format("TEST_VAR"), **shell_vars)
        stdout, stderr = run_in(commands, shell)
        # period here is because when var is blank, windows prints out the current echo setting.
        assert_equals(stdout, u'.', stderr)


@pytest.mark.skip(reason="will be covered with cmd.exe implmentation in new framework")
@pytest.mark.slow
@pytest.mark.installed
def test_activate_keeps_PATH_order(shell):
    if not on_win or shell != "cmd.exe":
        pytest.xfail("test only implemented for cmd.exe on win")
    shell_vars = _format_vars(shell)
    with TemporaryDirectory(prefix=ENVS_PREFIX, dir=dirname(__file__)) as envs:
        commands = (shell_vars['command_setup'] + """
        @set "PATH=somepath;CONDA_PATH_PLACEHOLDER;%PATH%"
        @call "{syspath}{binpath}activate.bat"
        {printpath}
        """).format(envs=envs, env_dirs=gen_test_env_paths(envs, shell), **shell_vars)
        stdout, stderr = run_in(commands, shell)
        assert stdout.startswith("somepath;" + sys.prefix)


@pytest.mark.slow
@pytest.mark.installed
def test_deactivate_placeholder(shell):
    if not on_win or shell != "cmd.exe":
        pytest.xfail("test only implemented for cmd.exe on win")
    shell_vars = _format_vars(shell)
    with TemporaryDirectory(prefix=ENVS_PREFIX, dir=dirname(__file__)) as envs:
        commands = (shell_vars['command_setup'] + """
        @set "PATH=flag;%PATH%"
        @call "{syspath}{binpath}activate.bat"
        @call "{syspath}{binpath}deactivate.bat" "hold"
        {printpath}
        """).format(envs=envs, env_dirs=gen_test_env_paths(envs, shell), **shell_vars)
        stdout, stderr = run_in(commands, shell)
        assert stdout.startswith("CONDA_PATH_PLACEHOLDER;flag")


# This test depends on files that are copied/linked in the conda recipe.  It is unfortunately not going to run after
#    a setup.py install step
# @pytest.mark.slow
# def test_activate_from_exec_folder(shell):
#     """The exec folder contains only the activate and conda commands.  It is for users
#     who want to avoid conda packages shadowing system ones."""
#     shell_vars = _format_vars(shell)
#     with TemporaryDirectory(prefix=ENVS_PREFIX, dir=dirname(__file__)) as envs:
#         env_dirs=gen_test_env_paths(envs, shell)
#         commands = (shell_vars['command_setup'] + """
#         {source} "{syspath}/exec/activate" "{env_dirs[0]}"
#         {echo} {var}
#         """).format(envs=envs, env_dirs=env_dirs, var=shells[shell]["var_format"].format("TEST_VAR"), **shell_vars)
#         stdout, stderr = run_in(commands, shell)
#         assert_equals(stdout, u'test', stderr)


def run_in(command, shell, cwd=None, env=None):
    if hasattr(shell, "keys"):
        shell = shell["exe"]
    if shell == 'cmd.exe':
        cmd_script = tempfile.NamedTemporaryFile(suffix='.bat', mode='wt', delete=False)
        cmd_script.write(command)
        cmd_script.close()
        cmd_bits = [shells[shell]["exe"]] + shells[shell]["shell_args"] + [cmd_script.name]
        try:
            print(cmd_bits)
            p = subprocess.Popen(cmd_bits, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 cwd=cwd, env=env)
            stdout, stderr = p.communicate()
        finally:
            os.unlink(cmd_script.name)
    elif shell == 'powershell':
        raise NotImplementedError
    else:
        cmd_bits = ([shells[shell]["exe"]] + shells[shell]["shell_args"] +
                    [translate_stream(command, shells[shell]["path_to"])])
        print(cmd_bits)
        p = subprocess.Popen(cmd_bits, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = p.communicate()
    streams = [u"%s" % stream.decode('utf-8').replace('\r\n', '\n').rstrip("\n")
               for stream in (stdout, stderr)]
    return streams
