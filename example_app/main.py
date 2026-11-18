"""The application that is frozen in the benchmark.

It is never run.
It only imports a number of popular pure-Python packages so that PyInstaller has a realistically large import graph to analyze.
"""

import asyncio
import email.mime.multipart
import http.server
import json
import logging.config
import sqlite3
import xml.etree.ElementTree

import django
import docutils.core
import jinja2
import pygments.lexers
import requests
import rich.console
import sqlalchemy.orm
