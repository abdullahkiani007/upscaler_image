#!/usr/bin/env bash

set -e

SNAPSHOT_FILE=snapshot.json

comfy node restore-snapshot "$SNAPSHOT_FILE" --pip-non-url
