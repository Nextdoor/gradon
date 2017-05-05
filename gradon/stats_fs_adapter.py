import collections
import logging
import re
import yaml

import pandas as pd
import six

try:
    import cPickle as pickle
except ImportError:
    import pickle

from . import file_system

log = logging.getLogger(__name__)


def series_to_dict(series):
    dct = collections.defaultdict(dict)
    for (category, metric), value in six.iteritems(series):
        dct[category][metric] = float(value) if value != int(value) else int(value)
    return dict(dct)


def dict_to_series(dct):
    return pd.DataFrame.from_dict(
        collections.OrderedDict(sorted(
            ((category, metric), [value])
            for category, category_dict in six.iteritems(dct)
            for metric, value in six.iteritems(category_dict))),
        orient='index')[0]


def read_stats_file(contents):
    dct = yaml.safe_load(contents)
    return dict_to_series(dct)


class StatsFSAdapter(object):
    def __init__(self, fs):
        self._fs = fs

    def set(self, path, series):
        with self._fs.add_file(path + '.stats.yaml') as f:
            yaml.safe_dump(series_to_dict(series), f, default_flow_style=False)

    def get(self, path, default=None):
        data = self._fs.read(path + '.stats.yaml')
        if data:
            return read_stats_file(data)
        else:
            return default

    def rm(self, path):
        self._fs.rm(path + '.stats.yaml')

    def ls(self, path):
        return [f.replace('.stats.yaml', '')
                for f in self._fs.ls_files(path) if f.endswith('.stats.yaml')]


class GitStatsAdapter(StatsFSAdapter):
    def set(self, path, series):
        filename = path + '.stats.yaml'
        with self._fs.add_file(filename, deferred=True) as f:
            log.debug("Writing file '{}'".format(filename))
            yaml.safe_dump(series_to_dict(series), f, default_flow_style=False)


class CachedStatsFSAdapterMixin(object):
    def __init__(self,  *args, **kwargs):
        super(CachedStatsFSAdapterMixin, self).__init__(*args, **kwargs)
        self._cache = {}

    def _normalize_path(self, path):
        return re.sub(r'^\./', '', re.sub(r'/\./', '/', path))

    def get(self, path, default=None):
        path = self._normalize_path(path)
        try:
            data = self._cache[path]
        except KeyError:
            log.debug('Cache stats miss: {}'.format(path))
        else:
            if data:
                return pickle.loads(data)
            else:
                return None
        series = super(CachedStatsFSAdapterMixin, self).get(path, default)
        self._cache[path] = pickle.dumps(series)
        return series

    def set(self, path, series):
        path = self._normalize_path(path)
        self._cache[path] = pickle.dumps(series)
        return super(CachedStatsFSAdapterMixin, self).set(path, series)

    def rm(self, path):
        self._cache[path] = None
        return super(CachedStatsFSAdapterMixin, self).rm(path)


class GitCachedStatsFSAdapter(CachedStatsFSAdapterMixin, GitStatsAdapter):
    pass


class CachedStatsFSAdapter(CachedStatsFSAdapterMixin, StatsFSAdapter):
    pass


def create_adapter_for_fs(fs):
    """ Create a stats adapter for the given file system """
    assert isinstance(fs, file_system.FileSystem)
    if isinstance(fs, file_system.GitStatsFileSystem):
        return GitCachedStatsFSAdapter(fs)
    else:
        return CachedStatsFSAdapter(fs)
