#!/usr/bin/env bash
set -euo pipefail
# Consolidate enhanced files into canonical names safely
pushd "$(dirname "$0")" >/dev/null

cp -f config_enhanced.py config.py
cp -f main_enhanced.py main.py
cp -f requirements_enhanced.txt requirements.txt
cp -f whisper_service_enhanced.py whisper_service.py
cp -f Dockerfile.new Dockerfile
cp -f README_enhanced.md README.md

# fix imports if any reference *_enhanced
sed -i.bak 's/from config_enhanced import config/from config import config/g' whisper_service.py || true
sed -i.bak 's/from whisper_service_enhanced import whisper_service/from whisper_service import whisper_service/g' main.py || true
rm -f *.bak

# cleanup enhanced duplicates
rm -f config_enhanced.py main_enhanced.py requirements_enhanced.txt \
      whisper_service_enhanced.py Dockerfile.new README_enhanced.md

echo "Consolidation complete"
