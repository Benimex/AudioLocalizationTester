"""Resolve data/asset dirs for both source runs and PyInstaller onefile builds.

When frozen, writable data (DB, user WAVs, EQ profiles) lives next to the .exe,
while read-only bundled assets are unpacked to sys._MEIPASS. From source, both
collapse to the project directory, so behaviour is unchanged.
"""
import os
import sys

if getattr(sys, "frozen", False):
    BASE = os.path.dirname(os.path.abspath(sys.executable))
    BUNDLE = sys._MEIPASS
else:
    BASE = BUNDLE = os.path.dirname(os.path.abspath(__file__))

STATIC_DIR = os.path.join(BUNDLE, "static")     # shipped UI, read-only
EQ_DIR = os.path.join(BASE, "eq")               # user-editable EQ profiles
STIMULI_DIR = os.path.join(BASE, "stimuli")     # user-added WAV stimuli
DB_PATH = os.path.join(BASE, "localization.db")
