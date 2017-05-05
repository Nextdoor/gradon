from __future__ import print_function

import collections
import heapq
import itertools
import logging
import multiprocessing
import os
import re
import string
import yaml

from six.moves import map
from six.moves import zip

import scandir
import tqdm

from radon import complexity
from radon import metrics
from radon import visitors
from radon import raw

from . import stats_fs_adapter
from . import tools


log = logging.getLogger(__name__)


def tuple_to_dict(tup):
    return dict(tup._asdict())


def scandirs_depth_first(root):
    """Yield directory names not starting with '.' under given path."""
    for dir_name in (e.name for e in scandir.scandir(root)
                     if e.is_dir() and not e.name.startswith('.')):
        for subdir_path in scandirs_depth_first(os.path.join(root, dir_name)):
            yield os.path.join(dir_name, subdir_path)
        yield dir_name


def zero_series(series):
    return series.apply(lambda v: 0)


class AnalysisFailed(Exception):
    pass


def _preserve_integers(dct):
    return {key: (int(value) if int(value) == value else value)
            for key, value in dct.items()}


def _analyze_file(path):
    try:
        return _analyze_file_internal(path)
    except AnalysisFailed as e:
        log.debug("Unable to analyze '{}': {}".format(path, e))
        return None


def _analyze_file_internal(path):
    lines = open(path).readlines()
    code = ''.join(lines)
    try:
        ast = visitors.code2ast(code)
    except Exception as e:
        raise AnalysisFailed(e)

    complexity_visitor = visitors.ComplexityVisitor.from_ast(ast)
    halstead = metrics.h_visit_ast(ast)

    methods = []

    grades = {g: 0 for g in string.ascii_uppercase[0:6]}
    for block in complexity_visitor.blocks:
        if block.letter != 'C':  # ignore classes, which are aggregates of methods
            if block.classname:
                name = '{}.{}'.format(block.classname, block.name)
            else:
                name = block.name
            endlineno = block.endline
            block_code = ''.join(lines[block.lineno - 1:endlineno])
            while True:
                try:
                    lloc = raw.analyze(block_code).lloc
                    break
                except Exception as e:
                    # Keep adding lines until we have the full block
                    if endlineno < len(lines):
                        block_code += lines[endlineno]
                        endlineno += 1
                    else:
                        log.debug("Error: Unable to analyze '{}' at {}: {}".format(
                            path, block.lineno, e))
                        # Fall back to number of non-black lines
                        lloc = sum(1 for _ in (l for l in lines[block.lineno:block.endline+1] if l))
                        break
            grade = complexity.cc_rank(block.complexity)
            methods.append({name: {grade: lloc}})
            grades[grade] += lloc
    try:
        stats = raw.analyze(code)
    except Exception as e:
        raise AnalysisFailed(e)

    return dict(
        complexity=_preserve_integers(dict(
            {'class': complexity_visitor.classes_complexity},
            func=complexity_visitor.functions_complexity,
            total=complexity_visitor.total_complexity,
        )),
        grades=_preserve_integers(grades),
        halstead=_preserve_integers(tuple_to_dict(halstead)),
        stats=_preserve_integers(tuple_to_dict(stats)),
        methods=methods)


class StatsUpdater(object):
    def __init__(self, source_root, dest_fs, debug=False, test_patterns=(), parallel=False):
        """ Create a StatsUpdater

        Args:
            source_root: Path to source tree
            dest_fs (StatsFileSystem): Destination for stats data
            debug (boolean): Print debug info
            test_patterns: Regexes to identify test code
            parallel (boolean): Use multiple processes
        """
        self._source_root = source_root
        self._dest_fs = dest_fs
        self._dest_stats = stats_fs_adapter.create_adapter_for_fs(dest_fs)
        self._debug = debug
        self._test_patterns = test_patterns
        if parallel:
            self._imap_processor = multiprocessing.Pool().imap
        else:
            self._imap_processor = map

    def _source_path(self, *parts):
        return os.path.join(self._source_root, *parts)

    def _source_exists(self, *parts):
        return os.path.exists(os.path.join(self._source_root, *parts))

    def _store_stats(self, series, *path):
        log.debug('Storing stats: {}'.format(os.path.join(*path)))
        self._dest_stats.set(os.path.join(*path), series)

    def _load_stats(self, *path):
        log.debug('Loading stats: {}'.format(os.path.join(*path)))
        return self._dest_stats.get(os.path.join(*path), None)

    def _remove_stats_file(self, *path):
        self._dest_stats.rm(os.path.join(*path))

    def _remove_stats_dir(self, *path):
        self._dest_fs.rmdir(os.path.join(*path))

    def _stats_dirs(self, *path):
        return self._dest_fs.ls_dirs(os.path.join(*path))

    def _py_stats_files(self, *path):
        return [f for f in self._dest_stats.ls(os.path.join(*path))
                if f.endswith('.py')]

    def _py_method_files(self, *path):
        return [f for f in self._dest_fs.ls_files(os.path.join(*path))
                if f.endswith('.py')]

    def _non_py_stats_files(self, *path):
        return [f for f in self._dest_stats.ls(os.path.join(*path))
                if not f.endswith('.py')]

    def update(self, changed_files=None, paths=None, test_patterns=(), ignore_patterns=(),
               progress=False):
        """ Update the destination workspace with changed files

        Args:
            changed_files: A list of files to analyze (optional, None means analyze all files)
            paths: A list of paths to consider (optional, None means entire subtree)
            test_patterns: A list of regexes to use to identify tests
            ignore_patterns: ignore files with names that match the regexps in this list
            progress (boolean): If True, display a progress indicator

        Returns:
            A set of changed directories
        """

        dir_files_iter = self._generate_dirs_and_files(changed_files)

        if progress:
            total, dir_files_iter = tools.tee_count(dir_files_iter)
        else:
            total = 1

        dirty_dirs = set()
        bar = tqdm.tqdm(disable=(not progress), total=total, unit_scale=True, unit='directory')
        for dir_path, files in dir_files_iter:
            has_changes = self._visit_files_in_dir(dir_path, files, paths=paths,
                                                   ignore_patterns=ignore_patterns)
            if has_changes:
                dirty_dirs.add(dir_path)
                self._aggregate_dir(dir_path)
            bar.update(1)

        if dirty_dirs:
            dirty_dirs.update(self._aggregate_subtrees(dirty_dirs))

        return dirty_dirs

    def _visit_files_in_dir(self, dir_path, changed_files=None, paths=None, ignore_patterns=()):
        if changed_files is None:
            changed_files_iter = (e.name for e in scandir.scandir(self._source_path(dir_path)))
        else:
            changed_files_iter = (f for f in changed_files if self._source_exists(dir_path, f))

        files_to_analyze_iter = (
            f for f in changed_files_iter
            if (f.endswith('.py') and
                (paths is None or
                 not any(os.path.join(dir_path, f).startswith(p) for p in paths)) and
                not any(re.search(pat, os.path.join(dir_path, f)) for pat in ignore_patterns)))

        if self._debug:
            log.debug("Visiting directory '{}'".format(dir_path))
            files_to_analyze_iter, files_to_print = itertools.tee(files_to_analyze_iter)
            files_to_print = list(files_to_print)
            if files_to_print:
                log.debug('Analyzing files: {}'.format(' '.join(files_to_print)))

        files_to_analyze_iter, file_names_iter = itertools.tee(files_to_analyze_iter)
        result_dicts = self._imap_processor(_analyze_file, (
            self._source_path(dir_path, f) for f in files_to_analyze_iter))

        has_changes = False
        for result_dict, file_name in zip(result_dicts, file_names_iter):
            if result_dict:
                methods = result_dict.pop('methods')
                series = stats_fs_adapter.dict_to_series(result_dict)
                self._store_stats(series, dir_path, file_name)
                has_changes = True
                with self._dest_fs.add_file(dir_path, file_name + '.methods.yaml') as file:
                    yaml.safe_dump(sorted(methods, key=lambda m: next(iter(m))), file)

        # Remove stale stats files
        stale_stats_files = [
            f for f in self._py_stats_files(dir_path) + self._py_method_files(dir_path)
            if ((changed_files is None or f in changed_files) and
                not self._source_exists(dir_path, f))]

        log.debug('Removing stale files: {}'.format(' '.join(stale_stats_files)))

        for stale_file in stale_stats_files:
            self._remove_stats_file(dir_path, stale_file)

        return bool(has_changes or stale_stats_files)

    def _aggregate_dir(self, dir_path):
        totals = dict(TOTAL=None, TOTAL_TEST=None, TOTAL_NON_TEST=None)
        individual_stats_files = self._py_stats_files(dir_path)

        for stats_file in individual_stats_files:
            series = self._load_stats(dir_path, stats_file)
            if totals['TOTAL'] is None:
                totals['TOTAL'] = zero_series(series)
                totals['TOTAL_TEST'] = totals['TOTAL'].copy()
                totals['TOTAL_NON_TEST'] = totals['TOTAL'].copy()

            totals['TOTAL'] = totals['TOTAL'].add(series, fill_value=0)

            basename = re.sub(r'.stats.yaml$', '', stats_file)
            is_test = any(re.search(regex, basename) for regex in self._test_patterns)

            if is_test:
                totals['TOTAL_TEST'] = totals['TOTAL_TEST'].add(series, fill_value=0)
            else:
                totals['TOTAL_NON_TEST'] = totals['TOTAL_NON_TEST'].add(series, fill_value=0)

        if individual_stats_files:
            for name, series in totals.items():
                self._store_stats(series, dir_path, name)
        else:
            # Remove total files if there are no python files in the directory
            for name in totals.keys():
                self._remove_stats_file(dir_path, name)

    def _aggregate_subtree(self, dir_path):
        subdirs = self._stats_dirs(dir_path)
        log.debug("Aggregating stats directories ({}) in '{}'".format(' '.join(subdirs), dir_path))
        found_stats = set()
        existing_totals = self._non_py_stats_files(dir_path)
        for name in ('TOTAL', 'TOTAL_TEST', 'TOTAL_NON_TEST'):
            subtree_name = 'SUBTREE_' + name
            subtotal_paths = (path for path in
                              [(dir_path, d, subtree_name) for d in subdirs] +
                              [(dir_path, name)])
            subtotal_stats = []
            for subtotal_path in subtotal_paths:
                stats = self._load_stats(*subtotal_path)
                if stats is not None:
                    subtotal_stats.append(stats)
                    found_stats.add(subtotal_path[1:-1])  # Keep track of subdirs that exist

            total = sum(subtotal_stats)
            if total is 0:  # List was empty
                if subtree_name in existing_totals:
                    self._remove_stats_file(dir_path, subtree_name)
            else:
                self._store_stats(total, dir_path, subtree_name)

        # Next, remove any empty subdirectories
        for subdir in subdirs:
            if (subdir,) not in found_stats:
                log.debug("Removing stats directory '{}'".format(os.path.join(dir_path, subdir)))
                self._remove_stats_dir(dir_path, subdir)

    def _aggregate_subtrees(self, dir_paths):
        # Use a heap to ensure that we process paths with the longest names first
        remaining_path_heap = []
        for path in dir_paths:
            heapq.heappush(remaining_path_heap, (-len(path), path))
        finished_paths = set()

        while remaining_path_heap:
            _, dir_path = heapq.heappop(remaining_path_heap)
            if dir_path in finished_paths:
                continue

            log.debug("Aggregating subtree '{}'".format(dir_path))

            self._aggregate_subtree(dir_path)

            parent_path = os.path.dirname(dir_path) or '.'
            heapq.heappush(remaining_path_heap, (-len(parent_path), parent_path))
            finished_paths.add(dir_path)

        return finished_paths

    def _generate_dirs_and_files(self, changed_files=None):
        """ Generate a list of files that have changed and their directories.

        Args:
            changed_files: Select on these files or directories that have changed

        Returns:
            A generator of (dir_name, files)
        """

        if changed_files is None:
            for dir_name in scandirs_depth_first(self._source_root):
                yield dir_name, None
            yield '.', None
        else:
            files_by_dir = collections.defaultdict(set)
            for f in changed_files:
                files_by_dir[os.path.dirname(f) or '.'].add(os.path.basename(f))
            for dir_name, files in files_by_dir.items():
                yield dir_name, files
