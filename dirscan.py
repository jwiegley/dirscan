#!/usr/bin/env python

# dirscan.py, version 2.0

import os
import re
import sys
import cPickle
import random
import subprocess
import logging as l

from copy import deepcopy
from datetime import datetime, timedelta
from getopt import getopt, GetoptError
from operator import attrgetter
from fcntl import flock, LOCK_SH, LOCK_EX, LOCK_UN

from hashlib import sha1
from stat import ST_ATIME, ST_MTIME, ST_MODE, ST_SIZE, S_ISDIR, S_ISREG
from os.path import (join, expanduser, dirname, basename,
                     exists, lexists, isfile, isdir, islink)

random.seed()
rightNow = datetime.now()

class InvalidArgumentException(Exception): pass


def delfile(path):
    if lexists(path):
        os.remove(path)

def deltree(path):
    if True:                    # using a dedicated rm is faster
        run('/bin/rm -fr', path)
    else:
        if not lexists(path): return
        for root, dirs, files in os.walk(path, topdown = False):
            for f in files:
                os.remove(join(root, f))
            for d in dirs:
                os.rmdir(join(root, d))
        os.rmdir(path)


def run(cmd, path, dryrun = False):
    path = re.sub("([$\"\\\\])", "\\\\\\1", path)

    if re.search('%s', cmd):
        cmd = re.sub('%s', '"' + path + '"', cmd)
    else:
        cmd = "%s \"%s\"" % (cmd, path)

    l.debug("Executing: %s" % cmd)

    if not dryrun:
        p = subprocess.Popen(cmd, shell = True)
        sts = os.waitpid(p.pid, 0)
        return sts[1] == 0

    return True

def safeRun(cmd, path, sudo = False, dryrun = False):
    try:
        if not run(cmd, path, dryrun):
            l.error("Command failed: '%s' with '%s'" % (cmd, path))
            raise Exception()
        else:
            return True
    except:
        if sudo:
            try:
                run('sudo ' + cmd, path, dryrun)
                return True
            except:
                l.error("Command failed: 'sudo %s' with '%s'" % (cmd, path))
        return False

def safeRemove(entry):
    entry.remove()

def safeTrash(entry):
    entry.trash()


class Entry(object):
    _scanner   = None
    _prevStamp = None
    _stamp     = None
    _prevInfo  = None
    _checksum  = None
    _lastCheck = None
    _info      = None
    _dirSize   = None

    def __init__(self, theScanner, path):
        self._scanner = theScanner
        self._path    = path

    @property
    def scanner(self):
        return self._scanner

    @property
    def path(self):
        return self._path

    def __str__(self):
        return self.path

    @property
    def dryrun(self):
        return self._scanner.dryrun

    @property
    def sudo(self):
        return self._scanner.sudo

    @property
    def secure(self):
        return self._scanner.secure

    def exists(self):
        return lexists(self.path)

    @property
    def info(self):
        if not self._info:
            try:
                self._info = os.lstat(self.path)
            except:
                # This can fail if the parent directory no longer exists
                pass
        return self._info

    @property
    def lastAccessTime(self):
        # Clear the cached info, since it may have changed
        if not self._scanner.cacheAttrs:
            self._info = None
        return datetime.fromtimestamp(self.info[ST_ATIME])

    @property
    def lastModTime(self):
        # Clear the cached info, since it may have changed
        if not self._scanner.cacheAttrs:
            self._info = None
        return datetime.fromtimestamp(self.info[ST_MTIME])

    @property
    def lastCheckedTime(self):
        # Clear the cached info, since it may have changed
        return self._lastCheck

    @property
    def size(self):
        # Clear the cached info, since it may have changed
        if not self._scanner.cacheAttrs:
            self._info    = None
            self._dirSize = None

        if self.isRegularFile():
            return long(self.info[ST_SIZE])
        elif self.isDirectory():
            if not self._dirSize:
                self._dirSize = 0L
                for root, dirs, files in os.walk(self.path):
                    for f in files:
                        self._dirSize += long(os.lstat(join(root, f))[ST_SIZE])
            return self._dirSize
        else:
            return 0L

    @property
    def checksum(self):
        # Clear the cached info, since it may have changed
        if not self._scanner.cacheAttrs:
            self._checksum = None
        if self.isRegularFile():
            if not self._checksum:
                m = sha1()
                l.debug("Computing SHA1 for: %s" % self.path)
                self._scanner._bytesScanned += self.size
                with open(self.path, "rb") as fd:
                    data = fd.read(8192)
                    while data:
                        m.update(data)
                        data = fd.read(8192)
                self._checksum  = m.hexdigest()
                if self._scanner.checkWindow:
                    days = random.randint(0, self._scanner.checkWindow - 1)
                    self._lastCheck = rightNow - timedelta(days)
                # Make sure that this checksum calculation is written
                self._scanner._dirty = True
            return self._checksum
        else:
            return None

    def contentsHaveChanged(self):
        if not self._prevInfo:
            return False
        self._info = None

        if self.info[ST_MTIME] != self._prevInfo[ST_MTIME]:
            if self._scanner.useChecksum:
                csum = self._checksum
                self._checksum = None
                if not csum:
                    csum = self.checksum
                else:
                    return self.checksum != csum
            return True

        elif self._scanner.useChecksumAlways:
            checkContents = True
            if self._scanner.checkWindow:
                lastCheck = self.lastCheckedTime
                if lastCheck:
                    days = (rightNow - lastCheck).days
                    checkContents = days >= self._scanner.checkWindow
                else:
                    csum = self._checksum
                    if not csum:
                        csum = self.checksum
            if checkContents:
                csum = self._checksum
                self._checksum = None
                if csum:
                    return self.checksum != csum
                else:
                    csum = self.checksum

        return False

    def getTimestamp(self):
        if self._scanner.atime:
            return self.lastAccessTime
        elif self._scanner.mtime:
            return self.lastModTime

        if not self._stamp:
            self._stamp = rightNow
        return self._stamp

    def setTimestamp(self, stamp):
        if not isinstance(stamp, datetime):
            msg = "`setTimestamp' requires an argument of type `datetime'"
            l.exception(msg); raise InvalidArgumentException(msg)
        self._stamp = stamp

    timestamp = property(getTimestamp, setTimestamp)

    def timestampHasChanged(self):
        if not self._prevStamp:
            return False
        return self.timestamp != self._prevStamp

    def isRegularFile(self):
        return self.info and S_ISREG(self.info[ST_MODE])

    def isDirectory(self):
        return self.info and S_ISDIR(self.info[ST_MODE])

    def shouldEnterDirectory(self):
        return self.isDirectory()

    def onEntryEvent(self, eventHandler):
        if isinstance(eventHandler, str):
            if safeRun(eventHandler, self.path, self.sudo, self.dryrun):
                return True
        elif callable(eventHandler):
            try:
                if eventHandler(self):
                    return True
            except Exception, inst:
                l.exception(str(inst))

        return False

    def onEntryAdded(self):
        l.info("A %s" % self.path)

        self._stamp = rightNow

        if self._scanner.onEntryAdded:
            self.onEntryEvent(self._scanner.onEntryAdded)
        return True

    def onEntryChanged(self, contentsChanged = False):
        l.info("%s %s" % (contentsChanged and "M" or "T", self.path))

        self._stamp = rightNow

        if self._scanner.onEntryChanged:
            self.onEntryEvent(self._scanner.onEntryChanged)
        return True

    def onEntryRemoved(self):
        l.info("R %s" % self.path)

        if self._scanner.onEntryRemoved:
            self.onEntryEvent(self._scanner.onEntryRemoved)
        return True

    def onEntryPastLimit(self, age):
        l.info("O %s (%.1f days old)" % (self.path, age))

        if self._scanner.onEntryPastLimit:
            self.onEntryEvent(self._scanner.onEntryPastLimit)

    def remove(self):
        """Remove a file or directory safely.

        The main point of this routine is three-fold:

        1. If the --secure option has been chosen, shell out to the `srm'
           command to perform the deletion of files. Directories are delete in
           the normal way (using os.rmdir).

        2. If --secure is not chosen, the Python functions os.remove and
           os.rmdir are used to remove files and directories.

        3. If --sudo-ok was chosen and the Python functions -- or `srm' --
           fail, try "sudo rm", "sudo rmdir" or "sudo srm": whichever is
           appropriate to what we're trying to do.

        4. If at last the file or directory could not be removed, print a
           notice to standard error. Cron will pick this up and send it to the
           administrator account in e-mail.

        5. If the deletion succeeded, remove the entry from the state database,
           mark the database as dirty, and return True so that we know to prune
           empty directories at the end of this run."""

        fileRemoved = False

        if isfile(self.path) or islink(self.path):
            secure = self.secure
            try:
                if secure:
                    if not run('/bin/srm -f', self.path, self.dryrun):
                        l.warning("Could not securely remove '%s'" % self)
                        raise Exception()
                else:
                    l.debug("Calling: cleanup.delfile('%s')" % self.path)
                    if not self.dryrun:
                        delfile(self.path)
            except:
                if self.sudo:
                    try:
                        if secure:
                            run('sudo /bin/srm -f', self.path, self.dryrun)
                        else:
                            run('sudo /bin/rm -f', self.path, self.dryrun)
                    except:
                        l.error("Error deleting file with sudo: %s" % self)

            if self.dryrun or not lexists(self.path):
                fileRemoved = True
            else:
                l.error("Could not remove file: %s\n" % self)

        elif lexists(self.path):
            try:
                l.debug("Calling: cleanup.deltree('%s')" % self.path)
                if not self.dryrun:
                    deltree(self.path)
            except:
                if self.sudo:
                    try:
                        run('sudo /bin/rm -fr', self.path, self.dryrun)
                    except:
                        l.error("Error deleting directory with sudo: %s" % self)

            if not self.dryrun and lexists(self.path):
                l.error("Could not remove dir: %s\n" % self.path)

        return fileRemoved

    def trash(self):
        if islink(self.path):
            self.remove()
            return True

        elif exists(self.path):
            base    = basename(self.path)
            target  = base
            ftarget = join(expanduser("~/.Trash"), target)
            index   = 1

            while lexists(ftarget):
                target = "%s-%d" % (base, index)
                index += 1
                ftarget = join(expanduser("~/.Trash"), target)

            try:
                l.debug("Calling: os.rename('%s', '%s')" % (self.path, ftarget))
                if not self.dryrun:
                    os.rename(self.path, ftarget)
            except:
                if self.sudo:
                    try:
                        run('sudo /bin/mv %%s "%s"' % ftarget,
                            self.path, self.dryrun)
                    except:
                        l.error("Error moving file with sudo: %s" % self)

            if self.dryrun or not lexists(self.path):
                return True
            else:
                l.error("Could not trash file: %s\n" % self)

        return False

    def __getstate__(self):
        x = self.timestamp; assert x
        self._prevStamp = deepcopy(x)

        if self._scanner.check:
            x = self.info
            if x:
                self._prevInfo = deepcopy(x)
                self._info = None

        odict = self.__dict__.copy() # copy the dict since we change it
        del odict['_scanner']

        return odict

    def __setstate__(self, info):
        self.__dict__.update(info) # update attributes
        self._info = None


def bytestring(amount):
    if amount < 1000:
        return "%d bytes" % amount
    elif amount < 1000 * 1000:
        return "%d KiB" % (amount / 1000)
    elif amount < 1000 * 1000 * 1000:
        return "%.1f MiB" % (amount / (1000.0 * 1000.0))
    elif amount < 1000 * 1000 * 1000 * 1000:
        return "%.2f GiB" % (amount / (1000.0 * 1000.0 * 1000.0))

class DirScanner(object):
    _dbMtime    = None
    _entries    = None
    _shadow     = None
    _dirty      = False
    _oldest     = 0
    _entryClass = Entry

    @property
    def entries(self):
        return self._entries

    def __init__(self,
                 directory         = None,
                 ages              = False, # this is a very odd option
                 atime             = False,
                 cacheAttrs        = False,
                 check             = False,
                 checkWindow       = None,
                 database          = '.files.dat',
                 days              = -1.0,
                 depth             = -1,
                 dryrun            = False,
                 ignoreFiles       = None,
                 maxSize           = None,
                 minimalScan       = False,
                 mtime             = False,
                 onEntryAdded      = None,
                 onEntryChanged    = None,
                 onEntryRemoved    = None,
                 onEntryPastLimit  = None,
                 pruneDirs         = False,
                 secure            = False,
                 sort              = False,
                 sudo              = False,
                 tempDirectory     = None,
                 useChecksum       = False,
                 useChecksumAlways = False):

        # Check the validity of all arguments and their types (if applicable)

        if not directory:
            msg = "`directory' must be a valid directory"
            l.exception(msg); raise InvalidArgumentException(msg)

        d = expanduser(directory)
        if d != directory:
            l.info("Expanded directory '%s' to '%s'" % (directory, d))
            directory = d

        if not isdir(directory):
            msg = "Directory '%s' is not a valid directory" % directory
            l.exception(msg); raise InvalidArgumentException(msg)

        if not os.access(directory, os.R_OK | os.X_OK):
            msg = "Directory '%s' is not readable or not searchable" % directory
            l.exception(msg); raise InvalidArgumentException(msg)

        if not ignoreFiles:
            l.debug("Initializing `ignoreFiles' to []")
            ignoreFiles = ['^\.files\.dat$', '^\.DS_Store$', '^\.localized$']

        if not isinstance(ignoreFiles, list):
            msg = "`ignoreFiles' must be of list type"
            l.exception(msg); raise InvalidArgumentException(msg)

        if not database:
            database = '.files.dat'
            l.debug("Setting database name to '%s'" % database)

        if not isinstance(database, str):
            msg = "`database' must be of string type"
            l.exception(msg); raise InvalidArgumentException(msg)

        if os.sep not in database:
            database = join(directory, database)
            l.debug("Expanding `database' to '%s'" % database)

        if minimalScan and depth != 0:
            l.warning("Using minimalScan when depth != 0 may cause problems")

        self.ages              = ages
        self.atime             = atime
        self.cacheAttrs        = cacheAttrs
        self.check             = check
        self.checkWindow       = checkWindow
        self.database          = database
        self.days              = days
        self.depth             = depth
        self.directory         = directory
        self.dryrun            = dryrun
        self.ignoreFiles       = ignoreFiles
        self.maxSize           = None
        self.minimalScan       = minimalScan
        self.mtime             = mtime
        self.onEntryAdded      = onEntryAdded
        self.onEntryChanged    = onEntryChanged
        self.onEntryRemoved    = onEntryRemoved
        self.onEntryPastLimit  = onEntryPastLimit
        self.pruneDirs         = pruneDirs
        self.secure            = secure
        self.sort              = sort
        self.sudo              = sudo
        self.tempDirectory     = tempDirectory
        self.useChecksum       = useChecksum or useChecksumAlways
        self.useChecksumAlways = useChecksumAlways

        if maxSize:
            if re.match('^[0-9]+$', maxSize):
                self.maxSize = long(maxSize)
            else:
                match = re.match('^([0-9]+)%$', maxSize)
                if match:
                    info = os.statvfs(directory)
                    self.maxSize = long((info.f_frsize * info.f_blocks) *
                                        (float(match.group(1))) / 100.0)
                else:
                    l.error("maxSize parameter is incorrect")

    def loadState(self):
        self._entries = {}
        self._dirty   = False
        self._dbMtime = None

        if not isfile(self.database):
            l.debug("State database '%s' does not exist yet" % self.database)
            return
        elif not os.access(self.database, os.R_OK):
            l.error("No read access to state data in '%s'" % self.database)
            return

        l.info("Loading state data from '%s'" % self.database)

        with open(self.database, 'rb') as fd:
            l.debug("Acquiring shared lock on '%s'..." % self.database)
            flock(fd, LOCK_SH)
            l.debug("Lock acquired")
            try:
                self._entries = cPickle.load(fd)

                # If the state database was created by the older cleanup.py, then
                # upgrade it.  Otherwise, associated each saved entry object with
                # this scanner.

                upgrade = {}
                for path, entry in self._entries.items():
                    if isinstance(entry, datetime):
                        newEntry = self.createEntry(path)
                        newEntry._stamp = entry
                        upgrade[path] = newEntry
                    else:
                        assert isinstance(entry, Entry)
                        entry._scanner = self

                if upgrade:
                    self._entries = upgrade
            finally:
                l.debug("Releasing shared lock on '%s'..." % self.database)
                flock(fd, LOCK_UN)
                l.debug("Lock released")

        l.info("Loaded state data from '%s' (%d entries)" %
               (self.database, len(self._entries.keys())))

        self._dbMtime = datetime.fromtimestamp(os.stat(self.database)[ST_MTIME])

    def saveState(self, tempDirectory = None):
        if not self.database: return
        if not self._dirty: return
        if self.dryrun: return

        databaseDir = dirname(self.database)

        if not exists(databaseDir):
            l.info("Creating state database directory '%s'" % databaseDir)
            os.makedirs(databaseDir)

        if not isdir(databaseDir):
            l.error("Database directory '%s' does not exist" % databaseDir)
            return
        elif not os.access(databaseDir, os.W_OK):
            l.error("Could not write to database directory '%s'" % databaseDir)
            return

        if tempDirectory:
            database = join(tempDirectory, basename(self.database))
        else:
            database = self.database
        l.debug("Writing updated state data to '%s'" % database)

        with open(database, 'wb') as fd:
            l.debug("Acquiring exclusive lock on '%s'..." % database)
            flock(fd, LOCK_EX)
            l.debug("Lock acquired")
            try:
                cPickle.dump(self._entries, fd)
            except:
                delfile(database)
                raise
            finally:
                l.debug("Releasing exclusive lock on '%s'..." % database)
                flock(fd, LOCK_UN)
                l.debug("Lock released")

        self._dirty   = False
        self._dbMtime = datetime.fromtimestamp(os.stat(database)[ST_MTIME])

    def registerEntryClass(self, entryClass):
        if not issubclass(entryClass, Entry):
            msg = "`entryClass' must be a class type derived from dirscan.Entry"
            l.exception(msg); raise InvalidArgumentException(msg)

        self._entryClass = entryClass

    def createEntry(self, path):
        return self._entryClass(self, path)

    def _scanEntry(self, entry):
        "Worker function called for every file in the directory."

        # If we haven't seen this entry before, call `onEntryAdded', which
        # ultimately results in triggering an onEntryAdded event.

        if not self._entries.has_key(entry.path):
            l.debug("Entry '%s' is being seen for the first time" % entry)
            if entry.onEntryAdded():
                self._entries[entry.path] = entry
                self._dirty = True

            assert not self._shadow.has_key(entry.path)

        # Otherwise, if the file changed, or `minimalScan' is False and the
        # timestamp is derived from the file itself (i.e., not just a record of
        # when we first saw it), then trigger an onEntryChanged event.

        elif entry.exists():
            # If the `check' option is True, check whether the modtime of
            # `path' is more recent than the modtime of the state database.

            changed = self.check and entry.contentsHaveChanged()

            if changed or entry.timestampHasChanged():
                l.debug("Entry '%s' %s seems to have changed" %
                        (entry, 'content' if changed else 'timestamp'))
                if entry.onEntryChanged(contentsChanged = changed):
                    self._dirty = True

            # Delete this path from the `shadow' dictionary, since we've
            # now dealt with it.  Any entries that remain in `shadow' at
            # the end will trigger an onEntryRemoved event.

            assert self._shadow.has_key(entry.path)
            del self._shadow[entry.path]

            # If the `days' option is greater than or equal to zero, do an age
            # check. If the file is "older" than `days', trigger an
            # onEntryPastLimit event.

            if self.days >= 0:
                delta = rightNow - entry.timestamp
                age   = float(delta.days) + float(delta.seconds) / 86400.0

                # The `ages' option, if True, means that we are just to print
                # out the ages of all entries -- don't do any deleting or
                # pruning.  Updating the database's state is OK, however, so
                # that subsequent runs of `ages' are correct.

                if self.ages:
                    print "%8.1f %s" % (age, entry)
                    return

                if age > self._oldest:
                    self._oldest = age

                # If the age of the file is greater than `days', trigger the
                # event `onEntryPastLimit'.

                if age >= self.days:
                    l.debug("Entry '%s' is beyond the age limit" % entry)
                    entry.onEntryPastLimit(age)

            # At this point, check whether we were dealing with a directory
            # and if it's now empty. If so, and if the `pruneDirs' option is
            # True, then delete the directory.

            if self.pruneDirs and isdir(entry.path) and \
               not os.listdir(entry.path):
                l.info("Pruning directory '%s'" % entry)
                entry.remove()

        # Has the entry been removed from disk by any of the above actions? If
        # so, report it having been removed right now.

        if not entry.exists() and entry.onEntryRemoved():
            l.debug("Entry '%s' was removed or found missing" % entry)
            if self._entries.has_key(entry.path):
                assert isinstance(self._entries[entry.path], Entry)
                assert self._entries[entry.path] is entry
                del self._entries[entry.path]
            self._dirty = True

    def walkEntries(self, fun):
        if callable(fun):
            for entry in self._entries.values():
                assert isinstance(entry, Entry)
                fun(entry)

    def computeSizes(self):
        size = 0L
        size_map = {}

        for entry in self._entries.values():
            assert isinstance(entry, Entry)
            entry_size = entry.size
            size += entry_size
            if size_map.has_key(entry_size):
                size_map[entry_size].append(entry)
            else:
                size_map[entry_size] = [entry]

        return (size, size_map)

    def _scanEntries(self, path, depth = 0):
        "This is the worker task for scanEntries, called for each directory."

        #l.debug("Scanning %s ..." % path)
        try:
            items = os.listdir(path)
            if self.sort:
                items.sort()
        except:
            l.warning("Could not read directory '%s'" % path)
            return

        for name in items:
            entryPath = join(path, name)

            ignored = False
            for pat in self.ignoreFiles:
                if re.search(pat, name):
                    ignored = True
                    break
            if ignored:
                #l.debug("Ignoring file '%s'" % entryPath)
                if self._entries.has_key(entryPath):
                    l.debug("Entry '%s' removed due to being ignored" % entryPath)
                    del self._entries[entryPath]
                    for key in self._entries.keys():
                        if key.startswith(entryPath + '/'):
                            l.debug("Entry '%s' removed due to being ignored" % key)
                            del self._entries[key]
                    self._dirty = True
                continue

            if self._entries.has_key(entryPath):
                entry = self._entries[entryPath]
            else:
                entry = self.createEntry(entryPath)
                l.debug("Created entry '%s'" % entry)

            # Recurse here so that we work from the bottom of the tree up,
            # which allows us to prune directories as they empty out (if
            # `prune' is True). The pruning is done at the end of `scanEntry'.

            if entry.exists() and entry.isDirectory() and \
               (self.depth < 0 or depth < self.depth) and \
               entry.shouldEnterDirectory():
                self._scanEntries(entryPath, depth + 1)

            self._scanEntry(entry)

            if self._bytesScanned > (10 * 1000 * 1000 * 1000):
                self.saveState(self.tempDirectory)
                self.copyTempDatabase()
                self._bytesScanned = 0

    def copyTempDatabase(self):
        if self.tempDirectory:
            database = join(self.tempDirectory, basename(self.database))
            if isfile(database):
                run('sudo /bin/cp -p %%s "%s"' % self.database,
                    database, self.dryrun)
                delfile(database)

    def scanEntries(self):
        """Scan the given directory, keeping state and acting on any changes.

        The given `directory' will be scanned, and a database kept within it
        whose name is given by `database' -- unless `database' is a relative or
        absolute pathname, in which case the database is kept there. This can
        be useful for scanning volumes which are read-only to the scanning
        process.

        Four triggers are available for acting on changes:

            onEntryAdded
            onEntryChanged
            onEntryRemoved
            onEntryPastLimit

        The first three triggers are always called, when a file or directory is
        first seen in `directory', (optionally) each time its timestamp or
        modtime is seen to change, and when it disappears. Each of these
        triggers may be of two kinds:

        string
          The string is taken to be a command, where every occurrence of %s
          within the string is replaced by the quoted filename, and the string
          is executed. If the `sudo' option is True, the same command will be
          attempted again -- with the command "sudo" prefixed to it -- if for
          any reason it fails.

        callable object
          The object called with the relevant path, and a dictionary of
          "options" which convey options specified by the caller. These are:

            data       The value of `data' passed in
            debug      If we are in debug mode
            dryrun     If this is a dry-run
            sudo       If sudo should be used to retry

            secure     If removes should be done securely

        The last three of these are only passed to the handler
        `onEntryPastLimit'.

        Each handler must return True or False.  If True, the meaning is:

            onEntryAdded      The file should be added to the state database
            onEntryChanged    The file's age should be updated ...
            onEntryRemoved    The file should be removed ...
            onEntryPastLimit  The file was deleted; invoke onEntryRemoved

        If False is returned, the action is not done, and the same event may
        recur on the next run of this function (unless the handler physically
        removed the file, or prevented it from being deleted).

        The trigger `onEntryPastLimit' is special and is only called if the
        option `days' is set to a value zero or higher -- and which may be
        fractional. In this case, the handler is called when aa file entry is
        seen to be "older" than that many days.

        The concept of older depends on how the age of the file is determined:
        if `atime' is True, the file is aged according to its last access time;
        if `mtime' is used, then the file's modification time; if
        `getTimestamp' is a callable Python object, it will be called with the
        pathname of the file; otherwise, the script remembers when it first saw
        the file, and this is used to determine the age.

        If `check' is True, the modtime of all files will be checked on each
        run, and if they are newer than the last time the state database was
        changed, then `onEntryChanged' will be called.  If `useChecksum' is
        also true, then the contents of the file is checksummed on modtime
        change to detect whether the file has really changed.  And if
        `useChecksumAlways' is true, the content is always checked regardless
        of the modtimes.  If `checkWindow' is an integer, and
        `useChecksumAlways' is true, only check file contents if it has been
        that many days since the last check.

        The other case where `onEntryChanged' might be called is if
        `minimalScan' is not used, which causes the timestamps of all files to
        be re-collected on every run. If any stamps change, `onEntryChanged' is
        called. This could be used for aging files based on their last access
        time, while ensuring that the most recent access time is always
        considered when determining the file's age.

        The `depth' option controls how deeply files are scanned. If set to 1,
        then only files and directories in `directory' are reported. If set to
        a number greater than 1, be aware than not only directories *but also
        the files within them* are passed to the event handlers.

        Directory contents may be changed by the event handlers, as each
        directory is scanned only when it is reached. If it disappears during a
        run, this will simply cause onEntryRemoved to be called.

        Lastly, the `alwaysPrune' option will cause empty directories found
        during the scanned to be pruned and `onEntryRemoved' to be called for
        them."""

        # Load the pre-existing state, if any, before scanning. If was already
        # loaded in a previous run, don't load it again.

        if not self._entries:
            self.loadState()

        assert isinstance(self._entries, dict)

        # If a state database did exist, check its last modified time. If more
        # recent than the directory itself, and if `minimalScan' is True, then
        # nothing has changed and we can exit now.

        scandir = True

        if self.minimalScan and self._dbMtime:
            assert isinstance(self._dbMtime, datetime)
            assert isdir(self.directory)
            assert os.access(self.directory, os.R_OK | os.X_OK)

            info     = os.stat(self.directory)
            dirMtime = datetime.fromtimestamp(info[ST_MTIME])

            if self._dbMtime >= dirMtime:
                scandir = False

            l.info("Database mtime %s %s directory %s, %s scan" %
                   (self._dbMtime, scandir and "<" or ">=", dirMtime,
                    scandir and "will" or "will not"))

        # If the directory has not changed, we can simply scan the entries in
        # the database without having to refer to disk. Otherwise, either the
        # directory has had files added or removed, or `minimalScan' is False.

        self._oldest = 0
        self._shadow = self._entries.copy()

        if not scandir:
            for entry in self._entries.values():
                assert isinstance(entry, Entry)
                self._scanEntry(entry)
        else:
            try:
                self._bytesScanned = 0
                self._scanEntries(self.directory)
            finally:
                self.copyTempDatabase()

        # Anything remaining in the `shadow' dictionary are state entries which
        # no longer exist on disk, so we trigger `onEntryRemoved' for each of
        # them, and then remove them from the state database.

        for entry in self._shadow.values():
            if entry.onEntryRemoved():
                if self._entries.has_key(entry.path):
                    l.debug("Removing missing entry at '%s'" % entry)
                    del self._entries[entry.path]
                else:
                    l.warning("Missing entry '%s' not in entries list" % entry)
                self._dirty = True

        # Report what the oldest file seen was, if debugging

        if self._oldest < self.days:
            l.info("No files were beyond the age limit (oldest %.1fd < %.1fd)" %
                   (self._oldest, self.days))

        # Compute the sizes of all files in the directory (if it has changed
        # at all), to see if we're over the overall limit.  If so, first
        # remove files that exceed the limit in and of themselves, and then
        # proceed by using the largest, oldest first.

        if self.maxSize and self._dirty:
            total_size, size_map = self.computeSizes()
            if total_size > self.maxSize:
                l.info("Directory exceeds the maximum size (%s > %s)" %
                       (bytestring(total_size), bytestring(self.maxSize)))

                sizes = size_map.keys()
                sizes.sort()
                sizes.reverse()

                if size_map.has_key(0):
                    l.info("Pruning %d empty entries" % len(size_map[0]))
                    for entry in size_map[0]:
                        safeRemove(entry)
                        self._dirty = True

                for size in sizes:
                    entries = size_map[size]
                    entries.sort(key = attrgetter('timestamp'))
                    for entry in entries:
                        l.info("Purging entry %s to reduce size (saves %s)" %
                               (entry.path, bytestring(size)))

                        safeRemove(entry)
                        total_size -= size
                        self._dirty = True

                        if total_size <= self.maxSize:
                            break

                    if total_size <= self.maxSize:
                        l.info("Directory is now within size limits (%s <= %s)" %
                               (bytestring(total_size), bytestring(self.maxSize)))
                        break
            else:
                l.info("Directory is within size limits (%s <= %s)" %
                       (bytestring(total_size), bytestring(self.maxSize)))

        # If any changes have been made to the state database, write those
        # changes out before exiting.

        self.saveState()


######################################################################
#
# Since this script can also be run from the command-line, employing option
# switches to select behavior using the default DirScanner and Entry classes,
# then here follows the user interaction code for that mode of use.
#

# A big legal disclaimer, since this script rather aggressively deletes things
# when told to...


def showVersion():
    print """
dirscan.py, version 1.0

Copyright (c) 2007-2008, by John Wiegley <johnw@newartisans.com>

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR
ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
(INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE."""


def usage():
    print """Usage: dirscan.py [options]

Where 'options' is one or more of:
    -h, --help            This help screen
    -V, --version         Display this script's version number

    -d, --dir=X           Operate on directory X instead of ~/.Trash
    -D, --depth=X         Only scan X levels; 0 = entries of dir, -1 = recurse
    -b, --database=X      Store state in X (defaults to .files.dat in `dir')
    -o, --sort            Read directories entries in sorted order
    -u, --status          Show concisely what's happening, use -n for read-only
    -w, --days=X          Wait until entries are X days old before deleting
    -s, --sudo            If an operation fails, uses `sudo' to try again
    -S, --secure          Files are securely wiped instead of deleted
    -p, --prune-dirs      Prune empty directories during a scan

    -A, --ages            Displays the ages of entries, but deletes nothing
    -n, --nothing         Don't make any changes to the directory or its state
    -v, --verbose         Show what's being done (or what would be done, if -n)

    -M, --max-size=X      Keep the directory's total size beneath X
    -z, --minimal-scan    Only check directory if files have been added/removed
                           ^ This does not consider subdirectories!

    -m, --mtime           Base file ages on their last modifiied time
    -a, --atime           Base file ages on their last accessed time
    -R, --check           If a file's modtime has changed, reset its age
                           ^ This is only necessary if -m or -a are not used
        --checksum        If modtimes have changed, confirm using SHA1
        --checksum-always Always use SHA1 to detect file modification
        --check-window=X  Only check contents always every X days

        --onadded=X       Execute X when an item is first seen in directory
        --onchanged=X     Execute X when an item is changed in directory
    -F, --onpastlimit=X   Execute X when an item is beyond the age limit
        --onremoved=X     Execute K after an item is removed from directory
                           ^ These four subsitute %s for the full path; don't
                             worry about quoting.  Also, new/changed/removed
                             directories are passed as well as files.  To
                             delete only files: -F "test -f %s && rm -f %s"

Defaults:
    cleanup -d ~/.Trash -b .files.dat -w 7 -D 0 -p

If you have sudo and use the NOACCESS option, I recommend this on OS/X:

    sudo cleanup -d /.Trashes; cleanup -s

If you have 'appscript' installed, you can mark files for secure
deletion using a Finder comment.  If the tag were @private, then say:

    cleanup -T @private

Let's say you want to move downloaded files from ~/Library/Downloads
to /Volumes/Archive after a stay of 3 days.  Here's a command you
might run (maybe hourly) to achieve this:

    cleanup -w 3 -p -d ~/Library/Downloads -m \\
            -F 'mv %s /Volumes/Archive' -K '@pending'

Broken down piece by piece:

    -w 3    # Wait for 3 days until a file is acted upon
    -p      # Clean up empty directories and dangling links
            # NOTE: this is done automatically if -F is not used
    -d ...  # Sets the directory to scan to: ~/Library/Downloads
    -m      # Base entry ages on their modification time.  This is
            # helpful with downloads because their modtime is exactly
            # when they got stored in the downloads dir
    -F ...  # Set the command to run when a file is out-of-date.  The
            # string %s in the command is replaced with the quoted
            # filename.
    -K ...  # If any file is tagged with a Finder comment containing
            # @pending, it will not be moved from the Downloads
            # directory.  I use this for items I have yet to look at,
            # but for which I haven't time."""


def processOptions(argv):
    "Process the command-line options."
    longOpts = [
        'ages',                         # -A
        'atime',                        # -a
        'check',                        # -R
        'check-window=',
        'database=',                    # -b
        'days=',                        # -w
        'depth=',                       # -D
        'directory=',                   # -d
        'dryrun',                       # -n
        'help',                         # -h
        'mtime',                        # -m
        'onadded=',
        'onchanged=',
        'onpastlimit=',                 # -F
        'onremoved=',
        'prune-dirs',                   # -p
        'minimal-scan',                 # -z
        'secure',                       # -S
        'sort',                         # -o
        'status',                       # -u
        'sudo',                         # -s
        'checksum',
        'checksum-always',
        'verbose',                      # -v
        'version' ]                     # -V

    try:
        opts = getopt(argv, 'AaRb:w:D:d:nhmF:pzST:ousvV', longOpts)[0]
    except GetoptError:
        usage()
        sys.exit(2)

    options = {
        'directory':        expanduser('~/.Trash'),
        'depth':            0,
        'days':             7,
        'onEntryPastLimit': safeRemove
    }

    for o, a in opts:
        if o in ('-h', '--help'):
            usage()
            sys.exit(0)
        elif o in ('-V', '--version'):
            showVersion()
            sys.exit(0)

        elif o in ('-A', '--ages'):
            options['ages']            = True
        elif o in ('-a', '--atime'):
            options['atime']           = True
        elif o in ('-C', '--cache-attrs'):
            options['cacheAttrs']      = True
        elif o in ('-R', '--check'):
            options['check']           = True
            options['minimalScan']     = False
        elif o in ('--check-window'):
            options['checkWindow']     = int(a)
        elif o in ('-b', '--database'):
            options['database']        = a
        elif o in ('-w', '--days'):
            options['days']            = float(a)
            options['database']        = a
        elif o in ('-D', '--depth'):
            options['depth']           = int(a)
        elif o in ('-d', '--directory'):
            options['directory']       = expanduser(a)
        elif o in ('-n', '--dryrun'):
            options['dryrun']          = True
        elif o in ('-m', '--mtime'):
            options['mtime']           = True
        elif o in ('--onadded'):
            options['onEntryAdded']     = a
        elif o in ('--onchanged'):
            options['onEntryChanged']   = a
        elif o in ('-F', '--onpastlimit'):
            options['onEntryPastLimit'] = a
        elif o in ('--onremoved'):
            options['onEntryRemoved']   = a
        elif o in ('-p', '--prune-dirs'):
            options['pruneDirs']       = True
        elif o in ('-z', '--minimal-scan'):
            options['minimalScan']     = True
        elif o in ('-M', '--max-size'):
            options['maxSize']         = a
        elif o in ('-S', '--secure'):
            options['secure']          = True
        elif o in ('-o', '--sort'):
            options['sort']            = True
        elif o in ('-u', '--status'):
            l.basicConfig(level = l.INFO, format = '%(message)s')
        elif o in ('--checksum'):
            options['useChecksum']     = True
        elif o in ('--checksum-always'):
            options['useChecksum']       = True
            options['useChecksumAlways'] = True
        elif o in ('-s', '--sudo'):
            options['sudo']            = True
        elif o in ('-v', '--verbose'):
            l.basicConfig(level = l.DEBUG,
                          format = '[%(levelname)s] %(message)s')

    return options


if __name__ == '__main__':
    if len(sys.argv) == 1:
        usage()
        sys.exit(2)

    assert len(sys.argv) > 1
    userOptions = processOptions(sys.argv[1:])

    if not isdir(userOptions['directory']):
        sys.stderr.write("The directory '%s' does not exist" %
                         userOptions['directory'])
        sys.exit(1)

    scanner = DirScanner(**userOptions)
    scanner.scanEntries()

# dirscan.py ends here
