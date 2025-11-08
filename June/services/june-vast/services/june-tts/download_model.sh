#!/usr/bin/env bash
set -euo pipefail

mkdir -p checkpoints references
echo "Downloading OpenAudio S1 mini checkpoint..."
hf download fishaudio/openaudio-s1-mini --local-dir checkpoints/openaudio-s1-mini
echo "Done."
