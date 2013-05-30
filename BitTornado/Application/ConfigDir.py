"""Manage application-specific configuration and caches
"""

import BitTornado
import sys
import os
import time
import shutil
from binascii import hexlify, unhexlify
from .inifile import ini_write, ini_read
from BitTornado.Meta.Info import MetaInfo
from .CreateIcons import GetIcons, CreateIcon
from .parseargs import defaultargs

try:
    OLDICONPATH = os.path.dirname(os.path.realpath(sys.argv[0]))
except AttributeError:
    OLDICONPATH = os.path.abspath(os.path.dirname(sys.argv[0]))

OLDICONPATH = os.path.join(OLDICONPATH, 'icons')

DIRNAME = '.' + BitTornado.product_name


class ConfigDir(object):
    """Class for managing configuration data, icons and caches"""

    def __init__(self, config_type=None):
        # Figure out a sensible application data location
        for envvar in ('APPDATA', 'HOME', 'HOMEPATH', 'USERPROFILE'):
            appdata = os.environ.get(envvar)
            if appdata:
                break
        else:
            appdata = os.path.expanduser('~')
            if not os.path.isdir(appdata):
                appdata = os.path.abspath(os.path.dirname(sys.argv[0]))

        # Config directory is ~/.BitTornado or equivalent
        dir_root = os.path.join(appdata, DIRNAME)

        # Create directory or fail loudly
        if not os.path.isdir(dir_root):
            os.mkdir(dir_root, 0o700)

        # Create subdirectories if missing, and reference with self.dir_*
        for attr in ('icons', 'torrentcache', 'datacache', 'piececache'):
            path = os.path.join(dir_root, attr)
            if not os.path.isdir(path):
                os.mkdir(path)
            setattr(self, 'dir_' + attr, path)

        # Try copying icons or generate from CreateIcons
        for icon in GetIcons():
            old_icon = os.path.join(OLDICONPATH, icon)
            new_icon = os.path.join(self.dir_icons, icon)
            if not (os.path.exists(new_icon) or
                    shutil.copyfile(old_icon, new_icon)):
                CreateIcon(icon, self.dir_icons)

        # Allow caller-specific config and state data
        ext = '' if config_type is None else ('.' + config_type)

        self.configfile = os.path.join(dir_root, 'config' + ext + '.ini')
        self.statefile = os.path.join(dir_root, 'state' + ext)

        self.torrentDataBuffer = {}
        self.config = {}

    ###### CONFIG HANDLING ######
    def setDefaults(self, defaults, ignore=()):
        """Set config to default arguments, with option to ignore arguments"""
        self.config = defaultargs(defaults)
        for key in ignore:
            self.config.pop(key, None)

    def checkConfig(self):
        """True if configfile exists"""
        return os.path.exists(self.configfile)

    def loadConfig(self):
        """Read configuration file and update local config dictionary"""
        newconfig = ini_read(self.configfile).get('')

        if not newconfig:
            return self.config

        # Track which keys aren't seen in config file
        configkeys = set(self.config)

        for key, val in newconfig.items():
            if key in self.config:
                try:
                    if isinstance(self.config[key], str):
                        self.config[key] = val
                    elif isinstance(self.config[key], (int, long)):
                        self.config[key] = long(val)
                    elif isinstance(self.config[key], float):
                        self.config[key] = float(val)
                    configkeys.discard(key)
                except ValueError:
                    pass

        if configkeys:  # Unsaved keys or invalid types prompt re-saving
            self.saveConfig()
        return self.config

    def saveConfig(self, new_config=None):
        """Save config dictionary to config file"""
        if new_config:
            for key, val in new_config.items():
                if key in self.config:
                    self.config[key] = val
        return ini_write(self.configfile, self.config, 'Generated by {}/{}\n{}'
                         ''.format(BitTornado.product_name,
                                   BitTornado.version_short,
                                   time.strftime('%x %X')))

    def getConfig(self):
        """Return config dictionary"""
        return self.config

    ###### TORRENT HANDLING ######
    def getTorrents(self):
        """Retrieve set of torrents in torrent cache"""
        return set(unhexlify(os.path.basename(torrent).split('.')[0])
                   for torrent in os.listdir(self.dir_torrentcache))

    def getTorrentVariations(self, torrent):
        """Retrieve set of versions of a given torrent"""
        torrent = hexlify(torrent)
        variations = []
        for fname in map(os.path.basename, os.listdir(self.dir_torrentcache)):
            if fname[:len(torrent)] == torrent:
                torrent, _dot, version = torrent.partition('.')
                variations.append(int(version or '0'))
        return sorted(variations)

    def getTorrent(self, torrent, version=-1):
        """Return the contents of a torrent file

        If version is -1 (default), get the most recent.
        If version is specified and > -1, retrieve specified version."""
        torrent = hexlify(torrent)
        fname = os.path.join(self.dir_torrentcache, torrent)

        if version == -1:
            version = max(self.getTorrentVariations(torrent))
        if version:
            fname += '.' + str(version)

        try:
            return MetaInfo.read(fname)
        except (IOError, ValueError):
            return None

    def writeTorrent(self, data, torrent, version=-1):
        """Write data to a torrent file

        If no version is provided, create a new version"""
        torrent = hexlify(torrent)
        fname = os.path.join(self.dir_torrentcache, torrent)

        if version == -1:
            try:
                version = max(self.getTorrentVariations(torrent)) + 1
            except ValueError:
                version = 0
        if version:
            fname += '.' + str(version)
        try:
            data.write(fname)
        except (IOError, TypeError, KeyError):
            return None

        return version

    ###### TORRENT DATA HANDLING ######
    def getTorrentData(self, torrent):
        """Read a torrent data file from cache"""
        if torrent in self.torrentDataBuffer:
            return self.torrentDataBuffer[torrent]
        fname = os.path.join(self.dir_datacache, hexlify(torrent))
        if not os.path.exists(fname):
            return None
        try:
            data = MetaInfo.read(fname)
        except (IOError, ValueError):
            data = None
        self.torrentDataBuffer[fname] = data
        return data

    def writeTorrentData(self, torrent, data):
        """Add a torrent data file to cache"""
        self.torrentDataBuffer[torrent] = data
        fname = os.path.join(self.dir_datacache, hexlify(torrent))
        try:
            data.write(fname)
            return True
        except (IOError, TypeError, KeyError):
            self.deleteTorrentData(torrent)
            return False

    def deleteTorrentData(self, torrent):
        """Remove a torrent data file from cache"""
        self.torrentDataBuffer.pop(torrent, None)
        try:
            os.remove(os.path.join(self.dir_datacache, hexlify(torrent)))
        except OSError:
            pass

    def getPieceDir(self, torrent):
        """Get torrent-specific piece cache directory"""
        return os.path.join(self.dir_piececache, hexlify(torrent))

    ###### EXPIRATION HANDLING ######
    def deleteOldCacheData(self, days, still_active=(), delete_torrents=False):
        """Remove cache data after a given number of days inactive"""
        if not days:
            return
        exptime = time.time() - (days * 24 * 3600)
        names = {}
        times = {}

        for torrent in os.listdir(self.dir_torrentcache):
            path = os.path.join(self.dir_torrentcache, torrent)
            torrent = unhexlify(os.path.basename(torrent).split('.')[0])
            if len(torrent) != 20:
                continue
            if delete_torrents:
                names.setdefault(torrent, []).append(path)
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                mtime = time.time()
            times.setdefault(torrent, []).append(mtime)

        for fname in os.listdir(self.dir_datacache):
            path = os.path.join(self.dir_datacache, fname)
            fname = unhexlify(os.path.basename(fname))
            if len(fname) != 20:
                continue
            names.setdefault(fname, []).append(path)
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                mtime = time.time()
            times.setdefault(fname, []).append(mtime)

        for piece in os.listdir(self.dir_piececache):
            piecepath = os.path.join(self.dir_piececache, piece)
            piece = unhexlify(os.path.basename(piece))
            if len(piece) != 20:
                continue

            for fname in os.listdir(piecepath):
                path = os.path.join(piecepath, fname)
                names.setdefault(piece, []).append(path)
                try:
                    mtime = os.path.getmtime(path)
                except OSError:
                    mtime = time.time()
                times.setdefault(piece, []).append(mtime)
            names.setdefault(piece, []).append(piecepath)

        for obj, mtime in times.items():
            if max(mtime) < exptime and obj not in still_active:
                for fname in names[obj]:
                    try:
                        os.remove(fname)
                    except OSError:
                        try:
                            os.removedirs(fname)
                        except OSError:
                            pass

    def deleteOldTorrents(self, days, still_active=()):
        """Synonym for deleteOldCacheData with delete_torrents set"""
        self.deleteOldCacheData(days, still_active, True)

    ###### OTHER ######
    def getIconDir(self):
        """Return application specific icon directory"""
        return self.dir_icons
