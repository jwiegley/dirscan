#!/usr/bin/env python

import dirscan

import os
import time
import unittest
import logging as l

from os.path import isfile, isdir, join

msgBuffer    = ""
respondTruly = True


class Entry(dirscan.Entry):
    def __init__(self, theScanner, path):
        dirscan.Entry.__init__(self, theScanner, path)

    def onEntryAdded(self):
        global msgBuffer
        if respondTruly:
            msgBuffer += "A %s\n" % self.path
        return respondTruly

    def onEntryChanged(self, contentsChanged = False):
        global msgBuffer
        if respondTruly:
            msgBuffer += "%s %s\n" % ('M' if contentsChanged else 'm', self.path)
        return respondTruly

    def onEntryRemoved(self):
        global msgBuffer
        if respondTruly:
            msgBuffer += "R %s\n" % self.path
        return respondTruly

    def onEntryPastLimit(self, age):
        global msgBuffer
        assert age >= 0
        msgBuffer += "O %s\n" % self.path


class DirScannerTestCase(unittest.TestCase):
    def setUp(self):
        global msgBuffer
        msgBuffer = ""

        self.testdir = '/tmp/DirScannerTest'

        if isdir(self.testdir):
            dirscan.deltree(self.testdir)

        os.makedirs(self.testdir)
        assert isdir(self.testdir)

        if False:
            l.basicConfig(level = l.DEBUG,
                          format = '[%(levelname)s] %(message)s')
        self.scanner = dirscan.DirScanner(self.testdir, sort = True,
                                          check = True)
        self.scanner.registerEntryClass(Entry)

    def tearDown(self):
        if isdir(self.testdir):
            dirscan.deltree(self.testdir)
        del self.scanner


    def scanEntries(self, response = True):
        global msgBuffer, respondTruly

        msgBuffer    = ""
        respondTruly = response

        self.scanner.scanEntries()


    def testFileAdded(self):
        fd = open(join(self.testdir, 'hello'), 'w')
        fd.write('Hello, world!\n')
        fd.close()

        self.scanEntries()
        self.assert_(isfile(self.scanner.database))
        self.assertEqual(msgBuffer, "A %s/hello\n" % self.testdir)

        fd = open(join(self.testdir, 'goodbye'), 'w')
        fd.write('Goodbye, world!\n')
        fd.close()

        self.scanEntries()
        self.assertEqual(msgBuffer, "A %s/goodbye\n" % self.testdir)

    def testFileChanged(self):
        fd = open(join(self.testdir, 'hello'), 'w')
        fd.write('Hello, world!\n')
        fd.close()

        self.scanEntries()
        self.assert_(isfile(self.scanner.database))
        self.assertEqual(msgBuffer, "A %s/hello\n" % self.testdir)

        time.sleep(1)
        fd = open(join(self.testdir, 'hello'), 'w')
        fd.write('Goodbye, world!\n')
        fd.close()

        self.scanEntries()
        self.assertEqual(msgBuffer, "M %s/hello\n" % self.testdir)


    def testFileRemoved(self):
        fd = open(join(self.testdir, 'hello'), 'w')
        fd.write('Hello, world!\n')
        fd.close()

        self.scanEntries()
        self.assert_(isfile(self.scanner.database))
        self.assertEqual(msgBuffer, "A %s/hello\n" % self.testdir)

        dirscan.delfile(join(self.testdir, 'hello'))

        self.scanEntries()
        self.assertEqual(msgBuffer, "R %s/hello\n" % self.testdir)


    def testFilePastLimit(self):
        fd = open(join(self.testdir, 'hello'), 'w')
        fd.write('Hello, world!\n')
        fd.close()

        self.scanEntries()
        self.assert_(isfile(self.scanner.database))
        self.assertEqual(msgBuffer, "A %s/hello\n" % self.testdir)

        days = self.scanner.days
        try:
            self.scanner.days = 0
            self.scanEntries()
        finally:
            self.scanner.days = days

        self.assertEqual(msgBuffer, "O %s/hello\n" % self.testdir)


    def testFileAddedFail(self):
        fd = open(join(self.testdir, 'hello'), 'w')
        fd.write('Hello, world!\n')
        fd.close()

        self.scanEntries(False)
        self.assert_(not isfile(self.scanner.database))
        self.assertEqual(msgBuffer, "")

        self.scanEntries()
        self.assert_(isfile(self.scanner.database))
        self.assertEqual(msgBuffer, "A %s/hello\n" % self.testdir)

        fd = open(join(self.testdir, 'goodbye'), 'w')
        fd.write('Goodbye, world!\n')
        fd.close()

        self.scanEntries(False)
        self.assert_(isfile(self.scanner.database))
        self.assertEqual(msgBuffer, "")

        self.scanEntries()
        self.assertEqual(msgBuffer, "A %s/goodbye\n" % self.testdir)


    def testFileChangedFail(self):
        fd = open(join(self.testdir, 'hello'), 'w')
        fd.write('Hello, world!\n')
        fd.close()

        self.scanEntries()
        self.assert_(isfile(self.scanner.database))
        self.assertEqual(msgBuffer, "A %s/hello\n" % self.testdir)

        time.sleep(1)
        fd = open(join(self.testdir, 'hello'), 'w')
        fd.write('Goodbye, world!\n')
        fd.close()

        self.scanEntries(False)
        self.assertEqual(msgBuffer, "")

        self.scanEntries()
        self.assertEqual(msgBuffer, "M %s/hello\n" % self.testdir)


    def testFileRemovedFail(self):
        fd = open(join(self.testdir, 'hello'), 'w')
        fd.write('Hello, world!\n')
        fd.close()

        self.scanEntries()
        self.assert_(isfile(self.scanner.database))
        self.assertEqual(msgBuffer, "A %s/hello\n" % self.testdir)

        dirscan.delfile(join(self.testdir, 'hello'))

        self.scanEntries(False)
        self.assertEqual(msgBuffer, "")
        self.scanEntries()
        self.assertEqual(msgBuffer, "R %s/hello\n" % self.testdir)


def suite():
    return unittest.TestLoader().loadTestsFromTestCase(DirScannerTestCase)

if __name__ == '__main__':
    unittest.main()
