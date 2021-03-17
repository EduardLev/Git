#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import binascii
from datetime import datetime
import errno
import hashlib
import random
import string
import struct
import sys
import os
import pathlib
import zlib

parser = argparse.ArgumentParser(description='Process pit commands')
subparsers = parser.add_subparsers(title="Commands", dest="command")
subparsers.required = True
init_parser = subparsers.add_parser("init", help="Initialize a new repository")
init_parser.add_argument("path", metavar="directory", nargs="?",
                         default=".", help="Path for the new repository")
commit_parser = subparsers.add_parser("commit")


def init(args):
    # Get path from args otherwise CWD, add .git to it.
    # Question: Is this the correct way to do this?
    root_path = os.path.abspath(args.path)
    git_path = os.path.join(root_path, ".git")

    try:
        # Make the .git directory
        pathlib.Path(git_path).mkdir()

        # Make .git/objects and .git/refs
        for path in ["objects", "refs"]:
            pathlib.Path(os.path.join(git_path, path)).mkdir()
    except OSError as exc:
        # Question: How to handle Errno:EACCESS?
        sys.stderr.write("Unable to initialize git paths")
        sys.exit(1)

    sys.stdout.write(f"Initialized empty Pit repository in {root_path}")
    sys.exit(0)

def commit(args):
    root_path = os.path.abspath(os.getcwd()) #cwd
    git_path = os.path.join(root_path, ".git") #cwd/.git
    db_path = os.path.join(git_path, "objects") #cwd/.git/objects

    workspace = Workspace(root_path)
    database = Database(db_path)

    entries = []
    for file in workspace.list_files():
        data = workspace.read_file(file) # returns file contents in bytes
        blob = Blob(data) # creates the file that will be stored blob 6data...
        database.store(blob) # stores directory under .git/objects/12/34343...

        # file is the filename (pit.py) and blob.id is the hash
        entries.append(Entry(file, blob.id))

    tree = Tree(entries)
    database.store(tree)

    name = os.environ['GIT_AUTHOR_NAME']
    email = os.environ['GIT_AUTHOR_EMAIL']
    author = Author(name, email, datetime.now())
    message = sys.stdin.readline()

    commit = Commit(tree.id, author, message)
    database.store(commit)

    head_path = os.path.join(git_path, "HEAD")
    with open(head_path, "a+") as file:
        file.write(commit.id)

    print(f"[(root-commit) {commit.id}] {message}")

# Read arguments and delegate to the correct function
def main(argv=sys.argv[1:]):  # sys.argv[0] is the name of the file
    args = parser.parse_args(argv)

    if args.command == "init":
        init(args) # delegate to init function
    if args.command == "commit":
        commit(args) # delegate to commit function

class Author(object):
    def __init__(self, name, email, time):
        self.name = name
        self.email = email
        self.time = time

    def serialize(self):
        timestamp = datetime.strftime(self.time, "%s %z")
        return f"{self.name} {self.email} {timestamp}"

class Blob(object):
    """Responsible for creating blobs from files."""
    type = b'blob'

    def __init__(self, data):
        # the data stored here is the bytes of the file that was read
        self.data = data
        self.id = ""

    def serialize(self):
        # returns bytes of file read
        return self.data

class Commit(object):
    """Responsible for generating a commit"""
    type = b'commit'

    def __init__(self, tree, author, message):
        self.tree = tree
        self.author = author
        self.message = message

    def serialize(self):
        lines = [
            f"tree {self.tree}",
            f"author {self.author.serialize()}",
            f"committer {self.author.serialize()}",
            "",
            self.message
        ]

        return str.encode("\n".join(lines))

class Tree(object):
    MODE = b'100644'
    type = b'tree'

    def __init__(self, entries):
        self.entries = entries

    def serialize(self):
        entries = []
        for entry in sorted(self.entries, key=lambda x:x.name):
            output = Tree.MODE  # First line of tree is the mode of the blob
            output += b' '       # Followed by a space
            output += entry.name.encode() # Followed by its "name"
            output += b'\x00'
            output += bytearray.fromhex(entry.id)
            entries.append(output)

        return b"".join(entries)

class Workspace(object):
    """Responsible for files in the working tree."""

    def __init__(self, pathname):
        # pathname = current working directory. cwd
        super(Workspace, self).__init__()
        self.pathname = pathname #cwd

    def list_files(self):
        """Returns source files in the working tree"""
        # pathname is the current working directory, so this list files in there
        return sorted([f for f in os.listdir(self.pathname) if not f.endswith('.git') if not f.endswith('.DS_Store')])

    def read_file(self, path):
        # returns contents of file as bytes
        with open(os.path.join(path), "rb") as file:
            return file.read()

class Database(object):
    """Responsible for storing blobs on disk, manages files in .git/objects"""
    # initialized with pathname = cwd/.git/objects
    def __init__(self, pathname):
        self.pathname = pathname

    def store(self, object):
        data = object.serialize() # gets the bytes data of blob

        # in bytes, blob 120(null byte)data
        content = object.type + b' ' + str(len(data)).encode() + b'\x00' + data

        # Get the sha1 hash _after_ writing blob + length + data
        # set the objects "id" property to this hash.
        # This should work for both blobs and trees
        object.id = hashlib.sha1(content).hexdigest()

        # Given the hash and the bytes content, save this in a directory.
        self.write_object(object.id, content)

    def write_object(self, id, content):
        # cwd/.git/objects/12/34567.....
        object_path = os.path.join(self.pathname, id[:2], id[2:])

        # cwd/.git/objects/12
        dirname = os.path.dirname(object_path)

        # cwd/.git/objects/12/tmp_obj_348394asdkljfs...
        temp_path = os.path.join(dirname, self.generate_temp_name())

        try:
            f = open(temp_path, 'a+b')
        except IOError as e:
            if e.errno == errno.ENOENT:
                os.mkdir(dirname) # if there is no parent directory, make it.
                f = open(temp_path, 'a+b') # try opening the temp file again

        compressed = zlib.compress(content)
        f.write(compressed)
        f.close()
        os.rename(temp_path, object_path)

    def generate_temp_name(self):
        return "tmp_obj_" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

class Entry:
    def __init__(self, name, id):
        self.name = name
        self.id = id

def utf8len(s):
    return len(s.encode('utf-8'))

main()
