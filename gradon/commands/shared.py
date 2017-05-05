from __future__ import print_function

try:
    import contextlib2 as contextlib
except ImportError:
    import contextlib

import difflib
import functools
import logging
import os
import re
import subprocess
import sys
import time
import yaml

import six

import click

log = logging.getLogger(__name__)


def parse_rev_range(rev_range, repo):
    if rev_range:
        try:
            start_rev, stop_rev = rev_range.split('..')
        except ValueError:
            start_rev = None
            stop_rev = rev_range
    else:
        stop_rev = None
        with log_duration('Searching for initial commit...'):
            # Find the initial commit
            _, start_rev = max(enumerate(repo.iter_commits()))
            start_rev = start_rev.hexsha

    if stop_rev is None:
        stop_rev = repo.head.commit.hexsha

    return start_rev, stop_rev


def git_log_args(f):
    @click.argument('rev_range', nargs=1, required=False)
    @click.argument('path', nargs=1, type=click.Path(),
                    callback=lambda ctx, param, path: path or ctx.obj['repo'].working_tree_dir,
                    default=None,
                    required=False)
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        f(*args, **kwargs)
    return wrapper


def _print_individual_stats(s, source_repo, stats_fs, cruft_scores, all=False, show_header=False,
                            name_map=None, print_original_commit=False):
    name_map = name_map or {}
    if show_header:
        if print_original_commit:
            original_commit = source_repo.commit(re.match('\w+', s.commit.message).group(0))
            print('commit {}\nAuthor: {}<{}>\nDate: {}\n{}\n'.format(
                original_commit.hexsha,
                original_commit.author,
                original_commit.author.email,
                original_commit.committed_datetime,
                original_commit.message))
            for filename, data in sorted(
                source_repo.commit(original_commit).stats.files.items(),
                    key=lambda pair: pair[0]):
                print('{} +{} -{}'.format(filename, data['insertions'], data['deletions']))
            print()

        prev_commit_hexsha = '{}~1'.format(s.commit.hexsha)
        prev = []
        current = []
        for diff in s.commit.diff(prev_commit_hexsha):
            if (diff.b_path and diff.b_path.endswith('.methods.yaml') or
                    diff.a_path and diff.a_path.endswith('.methods.yaml')):

                def get_method_list(path, sha):
                    module_path = ''.join(m + '.' for m in os.path.dirname(path).split('/'))
                    if module_path == '.':
                        module_path = ''
                    methods = []
                    for entry in yaml.safe_load(stats_fs.repo.git.show('{}:{}'.format(sha, path))):
                        name, value = next(six.iteritems(entry))
                        grade, lines = next(six.iteritems(value))
                        methods.append('{module}{name}: {grade} * {lines}'.format(
                            module=module_path, name=name, grade=grade, lines=lines))
                    return methods

                log.debug('analyzing deleted:{}, new:{}, a:{}, b:{}'.format(
                    diff.deleted_file, diff.new_file, diff.a_path, diff.b_path))

                if not diff.new_file:  # deleted is an add because we're comparing backwards
                    current.extend(get_method_list(diff.b_path, s.commit.hexsha))

                if not diff.deleted_file:  # new is a delete because we're comparing backwards
                    prev.extend(get_method_list(diff.a_path, prev_commit_hexsha))

        print('METHOD DIFFS:')

        def diff_only(diffs):
            return filter(lambda s: not s.startswith(' ') and not s.startswith('?'), diffs)

        print('\n'.join(diff_only(difflib.ndiff(
            sorted(prev), sorted(current)))))

    name = s.filename
    for pat, value in name_map.items():
        if re.search(pat, s.filename):
            name = value

    print('\n{}:'.format(name))

    if all:
        print(s.delta)
    else:
        delta_cruft = 0
        for grade in 'ABCDEF':
            value = s.delta[('grades', grade)]
            if value:
                print('  {}: {:+.0f}'.format(grade, value))
            delta_cruft += int(value) * cruft_scores[grade]
        print('  CRUFT: {:+.0f}'.format(delta_cruft))


def print_stats(stats_iter, source_repo, stats_fs, cruft_scores, all=False, name_map=None,
                print_original_commit=False):
    prev_commit = None
    stats = None
    for stats in stats_iter:
        show_header = (stats.commit != prev_commit)
        if prev_commit and show_header:
            print()
        _print_individual_stats(stats, source_repo, stats_fs, cruft_scores,
                                all=all, name_map=name_map, show_header=show_header,
                                print_original_commit=print_original_commit)
        prev_commit = stats.commit

    if stats:
        print()


@contextlib.contextmanager
def log_duration(message, level=logging.DEBUG):
    start_time = time.time()
    log.debug(message)
    yield
    log.log(level, 'done ({:.1f}s)'.format(time.time() - start_time))


def page_output(f):
    @click.option('--pager/--nopager', default=True)
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        with _page_output(skip=(not kwargs['pager'])):
            return f(*args, **kwargs)
    return wrapper


@contextlib.contextmanager
def _page_output(skip):
    if skip or not sys.stdout.isatty():
        yield
        return

    terminal_settings = subprocess.check_output(['stty', '-g'])
    try:
        pipe_rd, pipe_wr = os.pipe()
        pager = subprocess.Popen(['less', '-F', '-R', '-S', '-X', '-K'],
                                 stdin=os.fdopen(pipe_rd, 'r'), close_fds=True)
        pipe_output = os.fdopen(pipe_wr, 'a', 0)
        try:
            with contextlib.redirect_stdout(pipe_output):
                yield
        except KeyboardInterrupt:
            # let less handle this, -K will exit cleanly
            pass
        finally:
            pipe_output.close()
            pager.wait()
    finally:
        subprocess.check_call(['stty', terminal_settings])
