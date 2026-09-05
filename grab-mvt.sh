#!/bin/bash -e

# Grab a single .mvt file representing a single map tile at a given zoom level and X/Y coordinate

z="$1"
x="$2"
y="$3"

function require_vars {
    for required_variable in "$@" ; do
        if [[ -z "${!required_variable}" ]] ; then
            echo "Usage: ./grab-mvt.sh $@"
            exit 1
        fi
    done
}

require_vars z x y

pmtiles tile https://build.protomaps.com/20260904.pmtiles ${z} ${x} ${y} > "${z}.${x}.${y}.mvt"
