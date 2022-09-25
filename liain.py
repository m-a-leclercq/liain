import re
import zipfile
import csv

import requests
from bs4 import BeautifulSoup
from pyproj import Transformer, transform


URL = "https://operateurs.liain.fr/ipe/"

def search_ipe_file():
    # Scan all available files, grab IPE archive filename
    req = requests.get(URL)
    filename = BeautifulSoup(req.text, 'html.parser').find(href=re.compile("LIAIN_01_SIEA.*")).string

    return filename

def download_file(filename):
    # Downlad the file, return filename for use with other functions
    dl_url = "{0}{1}".format(URL, filename)
    download = requests.get(dl_url, stream=True)

    with open("/var/log/liain/{}".format(filename), 'wb') as fd:
        for chunk in download.iter_content(chunk_size=128):
            fd.write(chunk)

def unzip_file(zip_filename):
    with zipfile.ZipFile("/var/log/liain/{}".format(zip_filename), "r") as zip_ref:
        zip_ref.extractall("/var/log/liain/")

def transform_coordinates(filename):
    csv_iter = (row for row in csv.reader(open(filename, newline=''), delimiter=';'))

filename = search_ipe_file()
download_file(filename)
unzip_file(filename)
