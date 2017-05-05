from __future__ import print_function
from builtins import zip

import collections
import contextlib
import itertools
import logging
import os
import re
import shutil
import sys
import tempfile
import time
import yaml

import git
import six
import tqdm

from gradon import tools
from gradon import stats
from gradon import stats_fs_adapter

from .commands import shared

log = logging.getLogger(__name__)

DEFAULT_GRADON_REPO_PATH = '.gradon'


def _get_sha_from_message(message):
    return re.search(r'^\w+', message).group(0)


def _format_datetime_for_git(dt):
    # Internal git datetime format (see http://stackoverflow.com/questions/14023794/specification-for-syntax-of-git-dates)  # noqa
    return dt.strftime('%Y-%m-%d %H:%M:%S %z')


def _generate_changed_files(prev_commit, commit):
    """ Yields pairs of source->dest changed files """
    for diff in prev_commit.diff(commit.hexsha):
        if (diff.a_path or diff.b_path).endswith('.stats.yaml'):
            yield ((None if diff.new_file else diff.a_path),
                   (None if diff.deleted_file else diff.b_path))

Stats = collections.namedtuple('Stats',
                               ('filename', 'commit', 'lines', 'lines_test', 'lines_non_test',
                                'delta', 'after'))


def generate_stats_for_stats_fs_commits(stats_fs, shas, filters=None, test_patterns=()):
    """ Generates stats for an iterator of commits

    Args:
        stats_fs: A destination git file system
        shas: an iterator of commits shas in the dest fs
        reversed: Whether the commits are in the reverse order of the original git commits
        filters: Return only stats for the given filters
        test_patterns: Regexp for patterns considered to be tests

        Yields: rows of stats
    """

    empty_sha = stats_fs.repo.git.hash_object('/dev/null', t='tree')

    for current_sha in shas:
        log.info("Generating stats for '{}'".format(current_sha))
        commit = stats_fs.repo.commit(current_sha)
        prev_sha = _get_parent_sha(stats_fs.repo, current_sha, empty_sha)
        line_changes = yaml.safe_load(
            stats_fs.repo.git.show(current_sha + ':' + 'LATEST_CHANGES.yaml'))

        changed_files = set(_generate_changed_files(stats_fs.repo.commit(prev_sha), commit))

        for src, dest in ((s, d) for s, d in changed_files):
            before = after = None

            if src:
                before = stats_fs_adapter.read_stats_file(
                    stats_fs.repo.git.show(prev_sha + ':' + src))

            if dest:
                after = stats_fs_adapter.read_stats_file(
                    stats_fs.repo.git.show(current_sha + ':' + dest))

            if before is None:
                before = stats.zero_series(after)

            if after is None:
                after = stats.zero_series(before)

            diff = after - before

            # For deletes/renames, create two entries, one for src and one for dest
            for file in {v for v in [src, dest] if v is not None}:
                filename = file.replace('.stats.yaml', '')
                sign = 1 if file == dest else -1  # Flip the diff for deletes

                if (filters is not None and
                        not any(re.search(p, file) for p in filters)):
                    continue

                if filename.endswith('.py'):
                    prefix = filename
                else:
                    prefix = os.path.dirname(filename)

                def generate_deltas():
                    for entry, change_stats in six.iteritems(line_changes):
                        if prefix and not entry.startswith(prefix):
                            continue

                        basename = os.path.basename(entry)
                        is_test = any(re.search(regex, basename) for regex in test_patterns)

                        line_delta = (change_stats['lines'], change_stats['insertions'],
                                      change_stats['deletions'])

                        yield line_delta, is_test

                total, total_test, total_non_test = [(0, 0, 0)] * 3
                for line_delta, is_test in generate_deltas():
                    total = tuple(orig + delta for orig, delta in zip(total, line_delta))
                    if is_test:
                        total_test = tuple(orig + delta for orig, delta in
                                           zip(total_test, line_delta))
                    else:
                        total_non_test = tuple(orig + delta for orig, delta in
                                               zip(total_non_test, line_delta))

                yield Stats(filename, commit, total, total_test, total_non_test, diff.mul(sign),
                            after)


def update_stats_fs_from_repo(stats_fs, source_repo, rev_range=None, test_patterns=(),
                              exclude_patterns=(), paths=None, incremental=False,
                              parallel=False, debug=False):
    """
    Update gradon cache from a source repo path

    Args:
        stats_fs: The git filesystem to update
        source_repo: Repo to analyze
        paths: Source paths to update (None = "all")
        rev_range: Git rev range for source repo
        test_patterns: consider files with names that match the regexps in this list to be tests
        exclude_patterns: ignore files with names that match the regexps in this list
        incremental: Don't generate full stats if this is set
        parallel (boolean): Run analysis in parallel using all cores
        debug (boolean): Whether to log extra info

    """

    start_rev, stop_rev = shared.parse_rev_range(rev_range, source_repo)

    if start_rev:
        start_sha = source_repo.commit(start_rev).hexsha
        dest_start_sha = stats_fs.get_rev_for_sha(start_sha)
        if dest_start_sha:
            log.info('Restarting from commit {}'.format(start_sha), file=sys.stderr)
            stats_fs.repo.head.reset(dest_start_sha, index=True, working_tree=True)

    total, source_shas = tools.tee_count(
        generate_shas_for_source_range(source_repo, rev_range))

    stats_fs_commits = generate_stats_fs_commits_for_source_commits(
        stats_fs, source_repo, source_shas, incremental=incremental, paths=paths,
        test_patterns=test_patterns, exclude_patterns=exclude_patterns, parallel=parallel,
        debug=debug)

    log.debug("Analyzing repo range '{}' ...".format(rev_range))
    list(tqdm.tqdm(stats_fs_commits, total=total, unit='commit', unit_scale=True))


@contextlib.contextmanager
def _clone_source_repo(source_repo):
    tmpdir = tempfile.mkdtemp(prefix='cloned_source')
    try:
        yield source_repo.clone(tmpdir, shared=True)  # Copy the repo, just to be safe
    finally:
        shutil.rmtree(tmpdir)


def _get_parent_sha(repo, sha, default=None):
    parents = repo.commit(sha).parents
    if parents:
        return parents[0].hexsha
    else:
        return default


def generate_shas_for_source_range(source_repo, rev_range, reverse=False):
    return (c.hexsha for c in source_repo.iter_commits(rev_range, reverse=(not reverse)))


def generate_stats_fs_commits_for_source_commits(
        stats_fs, source_repo, source_shas, test_patterns=(), exclude_patterns=(),
        paths=None, incremental=False, parallel=False, reversed=False,
        debug=False):

    with _clone_source_repo(source_repo) as source_repo:
        empty_sha = source_repo.git.hash_object('/dev/null', t='tree')
        stats_updater = stats.StatsUpdater(source_repo.working_tree_dir, stats_fs,
                                           test_patterns=test_patterns, parallel=parallel,
                                           debug=debug)

        # Generate initial data if necessary and not incremental
        if not incremental and stats_fs.head_message is None:
            first_sha = next(source_shas)
            source_shas = itertools.chain([first_sha], source_shas)
            prev_sha = _get_parent_sha(source_repo, first_sha)

            source_repo.head.reset(commit=prev_sha, index=True,     working_tree=True)

            # Create the first commit
            with shared.log_duration('Performing initial analysis.  This could take a while...'):
                stats_updater.update(None, ignore_patterns=exclude_patterns,
                                     progress=True)

            with shared.log_duration('Committing initial stats to repo...'):
                stats_fs.commit(message='{}\nInitial gradon commit'.format(prev_sha))

        prev_shas, source_shas = itertools.tee(source_shas)

        if reversed:
            # Discard first previous commit
            prev_shas = itertools.chain(itertools.islice(prev_shas, 1, None), [None])
        else:
            first_sha = next(prev_shas)
            first_prev_sha = _get_parent_sha(source_repo, first_sha, empty_sha)
            prev_shas = itertools.chain([first_prev_sha, first_sha], prev_shas)

        update_times = []
        start = time.time()
        for current_sha, prev_sha in zip(source_shas, prev_shas):
            log.info("Generating fs stats for '{}'".format(current_sha))

            if prev_sha is None:
                prev_sha = _get_parent_sha(source_repo, current_sha, empty_sha)

            commit = source_repo.commit(current_sha)
            changed_files = set(p for diffs in commit.diff(prev_sha)
                                for p in (diffs.a_path, diffs.b_path))

            if incremental:
                if prev_sha != empty_sha:
                    source_repo.head.reset(commit=prev_sha, index=True, working_tree=True)
                    stats_updater.update(changed_files, paths=paths,
                                         ignore_patterns=exclude_patterns)
                else:
                    stats_updater.update((), paths=paths, ignore_patterns=exclude_patterns)
                stats_fs.commit('[ignore] ' + current_sha + '\n')

            source_repo.head.reset(commit=current_sha, index=True, working_tree=True)

            dirty_dirs = stats_updater.update(changed_files, paths=paths,
                                              test_patterns=test_patterns,
                                              ignore_patterns=exclude_patterns)
            if dirty_dirs:
                update_times.append(time.time() - start)
                if len(update_times) == 100:
                    log.info('Last 100 updates took {}s each (avg))'.format(
                        sum(update_times) / 100), file=sys.stderr)
                    update_times = []
                    start = time.time()

            with stats_fs.add_file('LATEST_CHANGES.yaml') as f:
                yaml.safe_dump(commit.stats.files, f, default_flow_style=False)
            with stats_fs.add_file('LATEST_CHANGES_TOTAL.yaml') as f:
                yaml.safe_dump(commit.stats.total, f, default_flow_style=False)

            yield stats_fs.commit(commit.hexsha + '\n' + commit.message,
                                  author=commit.author,
                                  author_date=_format_datetime_for_git(commit.authored_datetime),
                                  committer=commit.committer,
                                  commit_date=_format_datetime_for_git(
                                      commit.committed_datetime))


def generate_stats_fs_commit_for_diff(
        stats_fs, source_repo, first_rev, second_rev, test_patterns=(), exclude_patterns=(),
        paths=None, parallel=False, debug=False):
    if first_rev is None:
        first_rev = 'HEAD'
    commit = source_repo.commit(first_rev)
    diff = commit.diff(second_rev)
    log.info('Generating diff between {} and {}'.format(first_rev, second_rev or '<working tree>'))
    changed_files = set(p for diffs in diff for p in (diffs.a_path, diffs.b_path))
    diff_stats = git.Stats._list_from_string(
        source_repo, source_repo.git.diff(first_rev, second_rev, numstat=True))

    before_sha = source_repo.commit(first_rev).hexsha
    with _clone_source_repo(source_repo) as working_source_repo:
        working_source_repo.head.reset(commit=before_sha,
                                       index=True, working_tree=True)
        stats_updater = stats.StatsUpdater(working_source_repo.working_tree_dir, stats_fs,
                                           test_patterns=test_patterns, parallel=parallel,
                                           debug=debug)
        stats_updater.update(changed_files, paths=paths, ignore_patterns=exclude_patterns)
        stats_fs.commit('[ignore] ' + before_sha)

        repo = (source_repo if second_rev is None else working_source_repo)
        after_stats_updater = stats.StatsUpdater(
            repo.working_tree_dir,
            stats_fs,
            test_patterns=test_patterns, parallel=parallel,
            debug=debug)

        if second_rev is not None:
            after_sha = source_repo.commit(second_rev).hexsha
            working_source_repo.head.reset(commit=after_sha, index=True, working_tree=True)

        after_stats_updater.update(changed_files, paths=paths, test_patterns=test_patterns,
                                   ignore_patterns=exclude_patterns)

    with stats_fs.add_file('LATEST_CHANGES.yaml') as f:
        yaml.safe_dump(diff_stats.files, f, default_flow_style=False)
    with stats_fs.add_file('LATEST_CHANGES_TOTAL.yaml') as f:
        yaml.safe_dump(diff_stats.total, f, default_flow_style=False)

    return stats_fs.commit('{}..{}'.format(first_rev, second_rev or '<working tree>'))
