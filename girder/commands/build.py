#!/usr/bin/env python
# -*- coding: utf-8 -*-

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

import json
import os
from subprocess import check_call

import click

from girder.constants import STATIC_PREFIX, STATIC_ROOT_DIR
from girder.plugin import allPlugins, getPlugin

_GIRDER_STAGING_MARKER = '.girder-staging'

# TODO: add build assets to an npm package (or the python package)
_GIRDER_BUILD_ASSETS_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..'))


@click.command()
@click.option('--staging', type=click.Path(file_okay=False, writable=True, resolve_path=True),
              default=os.path.join(STATIC_PREFIX, 'staging'),
              help='Path to a staging area.')
def build(staging):
    _generateStagingArea(staging)

    check_call(['npm', 'install'], cwd=staging)
    check_call(['npx', '-n', '--preserve-symlinks', 'grunt', '--static-path=%s' % STATIC_ROOT_DIR],
               cwd=staging)


def _checkStagingPath(staging):
    try:
        os.makedirs(staging)
    except OSError:  # directory already exists
        pass
    listdir = os.listdir(staging)
    if listdir and _GIRDER_STAGING_MARKER not in listdir:
        raise Exception('Staging directory is not empty')

    with open(os.path.join(staging, _GIRDER_STAGING_MARKER), 'w') as f:
        f.write('')


def _generateStagingArea(staging):
    _checkStagingPath(staging)
    for baseName in ['grunt_tasks', 'Gruntfile.js']:
        target = os.path.join(staging, baseName)
        if os.path.exists(target):
            os.unlink(target)
        os.symlink(os.path.join(_GIRDER_BUILD_ASSETS_PATH, baseName), target)
    _generatePackageJSON(staging, os.path.join(_GIRDER_BUILD_ASSETS_PATH, 'package.json'))

    # copy swagger page source (TODO: make this better)
    source = os.path.join(_GIRDER_BUILD_ASSETS_PATH, 'clients', 'web', 'static',
                          'girder-swagger.js')
    target = os.path.join(staging, 'girder-swagger.js')
    if os.path.exists(target):
        os.unlink(target)
    os.symlink(source, target)


def _collectPluginDependencies():
    packages = {}
    for pluginName in allPlugins():
        plugin = getPlugin(pluginName)
        packages.update(plugin.npmPackages())
    return packages


def _generatePackageJSON(staging, source):
    # TODO: use a template string
    with open(source, 'r') as f:
        sourceJSON = json.load(f)
    deps = sourceJSON['dependencies']
    deps['girder'] = 'file:%s' % os.path.join(
        _GIRDER_BUILD_ASSETS_PATH, 'clients', 'web', 'src')
    plugins = _collectPluginDependencies()
    deps.update(plugins)
    sourceJSON['girder'] = {
        'plugins': list(plugins.keys())
    }
    with open(os.path.join(staging, 'package.json'), 'w') as f:
        json.dump(sourceJSON, f)


if __name__ == '__main__':
    build()
