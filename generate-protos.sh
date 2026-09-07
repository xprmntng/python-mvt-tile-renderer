#!/bin/bash -e

# Download JS dependencies if not already installed
if [[ ! -d node_modules/ ]] ; then
    npm install
fi

# Download MVT .proto spec
if [[ ! -f proto/vector_tile.proto ]] ; then
    mkdir -p proto/
    pushd proto/
    curl -O https://raw.githubusercontent.com/mapbox/vector-tile-spec/refs/heads/master/2.1/vector_tile.proto
    popd
fi

# Generate Python code based on the .proto downloaded. Output paths are defined in buf.gen.yaml
npx buf generate
