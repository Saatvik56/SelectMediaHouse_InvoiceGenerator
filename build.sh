#!/usr/bin/env bash
# exit on error
set -o errexit

# Install Python dependencies
pip install -r requirements.txt

# Install ONLY the Chromium browser for Playwright
playwright install chromium