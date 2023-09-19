import re
import zipfile
import csv

import requests
from bs4 import BeautifulSoup
from pyproj import Transformer, transform
from pathlib import Path


URL = "https://operateurs.liain.fr/ipe/"

def search_ipe_file():
    # Scan all available files, grab IPE archive filename
    req = requests.get(URL)
    filename = BeautifulSoup(req.text, 'html.parser').find(href=re.compile("LIAIN_01_SIEA.*PBOOK\\.zip")).string

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
        zip_ref.extractall("/var/log/")


def transform_coordinates(filename):
    file = Path(filename).stem
    transformer = Transformer.from_crs(2154, 4326)
    csv_iter = (row for row in csv.DictReader(open("/var/log/{}.csv".format(file), newline=''), delimiter=';'))
    processed_lines = 0
    with open("/var/log/liain/{}.csv".format(file), 'w', newline='') as csvfile:
        csv_write = csv.writer(csvfile, delimiter=';', quoting=csv.QUOTE_MINIMAL)
        for line in csv_iter:
            try:
                imm_lat, imm_lon = transformer.transform(line.get("CoordonneeImmeubleX"), line.get("CoordonneeImmeubleY"))
                line["localisation_immeuble"] = "{0},{1}".format(imm_lat, imm_lon)
            except TypeError:
                line["localisation_immeuble"] = ""
                pass
            try:
                pm_lat, pm_lon = transformer.transform(line.get("CoordonneePMX"), line.get("CoordonneePMY"))
                line["localisation_pm"] = "{0},{1}".format(pm_lat, pm_lon)
            except TypeError:
                line["localisation_pm"] = ""
                pass
            csv_write.writerow(list(line.values()))
            processed_lines += 1
        print("{} lines were processed".format(processed_lines))



filename = search_ipe_file()
download_file(filename)
unzip_file(filename)
transform_coordinates(filename)
