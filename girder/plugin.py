###############################################################################
#  Copyright Kitware Inc.
#
#  Licensed under the Apache License, Version 2.0 ( the "License" );
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
###############################################################################

"""
This module defines functions for registering, loading, and querying girder plugins.
"""

import distutils.dist
from functools import wraps
import os
from pkg_resources import iter_entry_points
import traceback

import six

from girder import logprint


NAMESPACE = 'girder.plugin'
_pluginRegistry = None
_pluginFailureInfo = {}
_pluginLoadOrder = []
_pluginWebroots = {}


def getPluginWebroots():
    global _pluginWebroots
    return _pluginWebroots


def registerPluginWebroot(webroot, name):
    """
    Adds a webroot to the global registry for plugins based on
    the plugin name.
    """
    global _pluginWebroots

    _pluginWebroots[name] = webroot


def _wrapPluginLoad(func):
    """Wrap a plugin load method to provide logging and ensure it is loaded only once."""
    @wraps(func)
    def wrapper(self, *args, **kwargs):

        if not getattr(self, '_loaded', False):
            # This block is executed on the first call to the function.
            # The return value of the call (or exception raised) is saved
            # as attributes on the wrapper for future invocations.
            self._loaded = True
            self._exception = None
            self._return = None

            try:
                result = func(self, *args, **kwargs)
            except Exception as e:
                # If any errors occur in loading the plugin, log the information, and
                # store failure information that can be queried through the api.
                self._exception = e
                logprint.exception('Failed to load plugin %s' % self.name)
                _pluginFailureInfo[self.name] = {
                    'traceback': traceback.format_exc()
                }
                raise

            _pluginLoadOrder.append(self.name)
            self._return = result
            self._success = True
            logprint.success('Loaded plugin "%s"' % self.name)

        elif self._exception:
            # If the plugin failed on the first invocation, reraise the original exception.
            raise self._exception

        return self._return

    return wrapper


class _PluginMeta(type):
    """
    This is a metaclass applied to the ``GirderPlugin`` descriptor class.  It
    exists to automatically wrap subclass load methods.
    """
    def __new__(meta, classname, bases, classdict):
        if 'load' in classdict:
            classdict['load'] = _wrapPluginLoad(classdict['load'])
        return type.__new__(meta, classname, bases, classdict)


@six.add_metaclass(_PluginMeta)
class GirderPlugin(object):
    """
    This is a base class for describing a girder plugin.  A plugin is registered by adding
    an entrypoint under the namespace ``girder.plugin``.  This entrypoint should return a
    class derived from this class.

    Example ::
        class Cats(GirderPlugin):

            def load(self, info):
                # load dependent plugins
                girder.plugin.getPlugin('pets').load(info)

                import rest  # register new rest endpoints, etc.
    """
    #: The name of the web client package on npm.
    NPM_PACKAGE_NAME = None

    #: The version of the web client package to use.  Accepts any npm version identifier.
    NPM_PACKAGE_VERSION = '*'

    #: The path of the plugin's web client source code.  This path is given relative to the python
    #: package.  This property is used to link the web client source into the staging area while
    #: building in development mode.  In production environments, the package is always fetched
    #: from npm.
    CLIENT_SOURCE_PATH = 'web_client'

    def __init__(self, entrypoint):
        self._name = entrypoint.name
        self._loaded = False
        self._dist = entrypoint.dist
        self._metadata = _readPackageMetadata(self._dist)

    def npmPackages(self):
        """Return a dictionary of npm packages -> versions for building the plugin client.

        By default, this dictionary will be assembled from the class properties, but plugins can
        customize the behaivor for advanced usage.  For development, this function will replace the
        version string with a ``file:...`` reference so npm will use the local source.
        """
        if not self.NPM_PACKAGE_NAME:
            return {}

        version = self.NPM_PACKAGE_VERSION
        clientDir = os.path.abspath(os.path.join(self._dist.location, self.CLIENT_SOURCE_PATH))

        # There isn't a great way to determine if this is an editable install of the python
        # package.  As an alternative, we check if the web source directory exists.  This will
        # also make it possible for plugins to include their client source in the python package
        # if desired; however, it is unclear if that should be a recommended pattern.
        if os.path.isdir(clientDir):
            version = 'file:%s' % clientDir

        return {self.NPM_PACKAGE_NAME: version}

    @property
    def name(self):
        """Return the plugin name defaulting to the entrypoint name."""
        return self._name

    @property
    def description(self):
        """Return the plugin description defaulting to the classes docstring."""
        return self._metadata.description

    @property
    def url(self):
        """Return a url reference to the plugin (usually a readthedocs page)."""
        return self._metadata.url

    @property
    def version(self):
        """Return the version of the plugin automatically determined from setup.py."""
        return self._metadata.version

    @property
    def loaded(self):
        """Return true if this plugin has been loaded."""
        return getattr(self, '_success', False)

    def load(self, info):
        raise NotImplementedError('Plugins must define a load method')


def _readPackageMetadata(distribution):
    """Get a metadata object associated with a python package."""
    metadata_string = distribution.get_metadata(distribution.PKG_INFO)
    metadata = distutils.dist.DistributionMetadata()
    metadata.read_pkg_file(six.StringIO(metadata_string))
    return metadata


def _getPluginRegistry():
    """Return a dictionary containing all detected plugins.

    This function will discover plugins registered via entrypoints and return
    a mapping of plugin name -> plugin definition.  The result is memoized
    because iteration through entrypoints is a slow operation.
    """
    global _pluginRegistry
    if _pluginRegistry is not None:
        return _pluginRegistry

    _pluginRegistry = {}
    for entryPoint in iter_entry_points(NAMESPACE):
        pluginClass = entryPoint.load()
        plugin = pluginClass(entryPoint)
        _pluginRegistry[plugin.name] = plugin
    return _pluginRegistry


def getPlugin(name):
    """Return a plugin configuration object or None if the plugin is not found."""
    registry = _getPluginRegistry()
    return registry.get(name)


def getPluginFailureInfo():
    """Return an object containing plugin failure information."""
    return _pluginFailureInfo


def loadPlugins(names, info):
    """Load a list of plugins with the given app info object.

    This method will try to load **all** plugins in the provided list.  If
    an error occurs, it will be logged and the next plugin will be loaded.  A
    list of successfully loaded plugins will be returned.
    """
    loadedPlugins = []
    for name in names:
        pluginObject = getPlugin(name)

        if pluginObject is None:
            logprint.error('Plugin %s is not installed' % name)
            continue

        try:
            pluginObject.load(info)
        except Exception:
            continue
        loadedPlugins.append(name)

    return loadedPlugins


def allPlugins():
    """Return a list of all detected plugins."""
    return list(_getPluginRegistry().keys())


def loadedPlugins():
    """Return a list of successfully loaded plugins."""
    return _pluginLoadOrder[:]
