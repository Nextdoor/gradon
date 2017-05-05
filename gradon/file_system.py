import collections
import contextlib
import logging
import os
import scandir
import shutil
import re


try:
    from StringIO import StringIO
except ImportError:
    from io import StringIO

import six

import git
import gitdb

log = logging.getLogger(__name__)


class FileSystem(object):
    def __init__(self, path):
        self._work_root = path

    def _normalize_path(self, path):
        return re.sub(r'^\./', '', re.sub(r'/\./', '/', path))

    @property
    def path(self):
        return self._work_root

    def _abs_dir_path(self, *parts):
        return os.path.join(self.path, *parts)

    def _rel_file_path(self, *parts):
        return os.path.join(*parts)

    def _abs_file_path(self, *parts):
        return os.path.join(self.path, self._rel_file_path(*parts))

    @contextlib.contextmanager
    def add_file(self, *path):
        abs_file_path = self._normalize_path(self._abs_file_path(*path))
        dirname = os.path.dirname(abs_file_path)
        if not os.path.exists(dirname):
            os.makedirs(dirname)
        with open(abs_file_path, 'w') as f:
            yield f

    def read(self, *path):
        abs_file_path = self._abs_file_path(*path)
        if os.path.exists(abs_file_path):
            return open(abs_file_path).read()
        else:
            return None

    def ls_files(self, path):
        if not os.path.exists(self._abs_dir_path(path)):
            return []
        return [e.name for e in scandir.scandir(self._abs_dir_path(path))]

    def ls_dirs(self, path):
        return [e.name for e in scandir.scandir(self._abs_dir_path(path))
                if (os.path.isdir(self._abs_dir_path(path, e.name)) and
                    not e.name.startswith('.'))]

    def rm(self, path):
        abs_file_path = self._abs_file_path(path)
        if os.path.exists(abs_file_path):
            os.remove(abs_file_path)

    def rmdir(self, path):
        full_path = self._abs_dir_path(path)
        if os.path.exists(full_path):
            try:
                os.rmdir(full_path)
            except OSError:  # Ignore error when directory is not empty
                pass


class CachedFileSystemMixin(object):
    def __init__(self, *args, **kwargs):
        super(CachedFileSystemMixin, self).__init__(*args, **kwargs)
        self._files_cache = collections.defaultdict(set)
        self._dirs_cache = collections.defaultdict(set)
        self._misses = []

    def _update_cache_to_contain_file(self, path):
        """ Keep existing caches up-to-date with the current directory structure """
        path = self._normalize_path(path)
        basename = os.path.basename(path)
        dirname = os.path.dirname(path) or '.'
        if dirname in self._files_cache:
            self._files_cache[dirname].add(basename)

        while path:
            if path == '.':
                break
            basename = os.path.basename(path)
            dirname = os.path.dirname(path) or '.'
            if dirname in self._dirs_cache:
                self._dirs_cache[dirname].add(basename)
            path = dirname

    @contextlib.contextmanager
    def add_file(self, *path, **kwargs):
        with super(CachedFileSystemMixin, self).add_file(*path, **kwargs) as f:
            yield f
        self._update_cache_to_contain_file(os.path.join(*path))

    def rm(self, path):
        path = self._normalize_path(path)
        dirname = os.path.dirname(path) or '.'
        basename = os.path.basename(path)
        if dirname in self._files_cache:
            try:
                self._files_cache[dirname].remove(basename)
            except KeyError:
                pass
        return super(CachedFileSystemMixin, self).rm(path)

    def rmdir(self, path):
        path = self._normalize_path(path)
        dirname = os.path.dirname(path)
        if dirname in self._dirs_cache:
            self._dirs_cache[dirname].remove(os.path.basename(path))
        return super(CachedFileSystemMixin, self).rmdir(path)

    def ls_files(self, path):
        path = self._normalize_path(path)
        if path in self._files_cache:
            return tuple(self._files_cache[path])
        files = super(CachedFileSystemMixin, self).ls_files(path)
        self._files_cache[path] = set(files)
        return files

    def ls_dirs(self, path):
        path = self._normalize_path(path)
        if path in self._dirs_cache:
            return tuple(self._dirs_cache[path])
        dirs = super(CachedFileSystemMixin, self).ls_dirs(path)
        self._dirs_cache[path] = set(dirs)
        return dirs

    def commit(self, message, **kwargs):
        log.debug('{} new cache misses prior to commit'.format(len(self._misses)))
        del self._misses[:]
        return super(CachedFileSystemMixin, self).commit(message, **kwargs)

    def ls_stats(self, path):
        if not os.path.exists(self._abs_dir_path(path)):
            return []
        return [e.name.replace('.stats.yaml', '')
                for e in scandir.scandir(self._abs_dir_path(path))
                if (e.name.endswith('.stats.yaml') and
                    not os.path.isdir(self._abs_dir_path(path, e.name)))]


class GitStatsFileSystem(FileSystem):
    def __init__(self, path, init=False):
        if not os.path.exists(os.path.join(path, '.git')) or init:
            if os.path.exists(path):
                shutil.rmtree(path)
            self._repo = git.Repo.init(path)
        else:
            self._repo = git.Repo(path)
        super(GitStatsFileSystem, self).__init__(self._repo.working_tree_dir)

    @property
    def head_message(self):
        try:
            return self._repo.head.commit.message
        except ValueError:
            return None

    @contextlib.contextmanager
    def add_file(self, *path, **kwargs):
        with super(GitStatsFileSystem, self).add_file(*path) as f:
            yield f

    def commit(self, message, **kwargs):
        env = dict()
        if 'author' in kwargs:
            author = kwargs.pop('author')
            env['GIT_AUTHOR_EMAIL'] = author.email
            env['GIT_AUTHOR_NAME'] = author.name
        if 'author_date' in kwargs:
            env['GIT_AUTHOR_DATE'] = str(kwargs.pop('author_date'))
        if 'committer' in kwargs:
            committer = kwargs.pop('committer')
            env['GIT_COMMITTER_EMAIL'] = committer.email
            env['GIT_COMMITTER_NAME'] = committer.name
        if 'commit_date' in kwargs:
            env['GIT_COMMITTER_DATE'] = kwargs.pop('commit_date')
        old_env = self._repo.git.update_environment(**env)
        try:
            self._repo.git.add(all=True)
            return self._repo.git.commit(message=message, allow_empty=True)
        finally:
            self._repo.git.update_environment(**old_env)

    def rm(self, path):
        abs_file_path = self._abs_file_path(*path)
        if os.path.exists(abs_file_path):
            self._repo.git.rm(abs_file_path, ignore_unmatch=True)

    @property
    def repo(self):
        return self._repo

    def get_rev_for_sha(self, hexsha):
        try:
            message = self.repo.git.log(grep='^' + hexsha, oneline=True)
        except git.exc.GitCommandError:
            return None

        if not message:
            return None

        sha, _ = message.split(' ', 1)
        return sha


class GitIndexStatsFileSystem(GitStatsFileSystem):
    def __init__(self, path, init=False):
        # TODO: create a working tree somewhere else
        super(GitIndexStatsFileSystem, self).__init__(path, init=init)
        # self._work_root = tempfile.mkdtemp(prefix='gradon-git-index-fs')
        # self._repo.git.update_environment(GIT_WORK_TREE=self._work_root)
        self._repo.head.reset(index=True, working_tree=True)
        self._dirty = False
        self._deferred_entries = []
        self._added_files = []

    # TODO: enable this once we have a working tree elsewhere
    # def __del__(self):
    #     shutil.rmtree(self.path)

    def _flush(self):
        if self._added_files or self._deferred_entries:
            self._repo.index.add(self._deferred_entries + self._added_files)
        del self._added_files[:]
        del self._deferred_entries[:]

    @contextlib.contextmanager
    def add_file(self, *path, **kwargs):
        deferred = kwargs.pop('deferred', False)
        if deferred:
            stream = StringIO()
            yield stream
        else:
            with super(GitIndexStatsFileSystem, self).add_file(*path) as f:
                yield f

        if deferred:
            data = stream.getvalue()
            istream = self._repo.odb.store(gitdb.IStream('blob', len(data),
                                                         six.BytesIO(data.encode())))
            blob = git.Blob(self._repo, istream.binsha, git.Blob.file_mode,
                            self._rel_file_path(*path))
            self._deferred_entries.append(git.IndexEntry.from_blob(blob))
        else:
            self._added_files.append(self._normalize_path(os.path.join(*path)))
        self._dirty = True

    def _sync_working_tree(self, path):
        if self._dirty:
            self._flush()
            self._repo.index.checkout(force=True)
            self._dirty = False

    def commit(self, message, **kwargs):
        self._flush()
        return self._repo.index.commit(message=message, **kwargs).hexsha

    def rm(self, path):
        self._sync_working_tree(path)
        return super(GitIndexStatsFileSystem, self).rm(path)
        # blob = git.Blob(self._repo, None, git.Blob.file_mode, self._rel_file_path(path))
        # self._repo.index.add([git.IndexEntry.from_blob(blob)])

    def read(self, *path):
        self._sync_working_tree(path)
        return super(GitIndexStatsFileSystem, self).read(*path)

    def ls_files(self, path):
        self._sync_working_tree(path)
        return super(GitIndexStatsFileSystem, self).ls_files(path)

    def ls_dirs(self, path):
        self._sync_working_tree(path)
        return super(GitIndexStatsFileSystem, self).ls_dirs(path)


class GitCachedStatsFileSystem(CachedFileSystemMixin, GitStatsFileSystem):
    pass


class GitCachedIndexStatsFileSystem(CachedFileSystemMixin, GitIndexStatsFileSystem):
    pass
