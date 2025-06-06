import os
from tqdm import tqdm
import requests
import os
from tqdm import tqdm
import requests
import tarfile

RAW_DATA_PATH = 'meta_acc_predictor/data'

def download_file(url, filename):
    """
    Helper method handling downloading large files from `url` 
    to `filename`. Returns a pointer to `filename`.
    """
    chunkSize = 1024
    r = requests.get(url, stream=True)
    with open(filename, 'wb') as f:
        pbar = tqdm( unit="B", total=int(r.headers['Content-Length']))
        for chunk in r.iter_content(chunk_size=chunkSize):
            if chunk:  # filter out keep-alive new chunks
                pbar.update(len(chunk))
                f.write(chunk)
    return filename

def download_pets():
    dir_path = os.path.join(RAW_DATA_PATH, 'pets')
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)

    full_name = os.path.join(dir_path, 'test15.pth')
    if not os.path.exists(full_name):
        print(f"Downloading {full_name}\n")
        download_file(
            'https://www.dropbox.com/s/kzmrwyyk5iaugv0/test15.pth?dl=1', full_name)
        print("Downloading done.\n")
    else:
        print(f"{full_name} has already been downloaded. Did not download twice.\n")

    full_name = os.path.join(dir_path, 'train85.pth')
    if not os.path.exists(full_name):
        print(f"Downloading {full_name}\n")
        download_file(
            'https://www.dropbox.com/s/w7mikpztkamnw9s/train85.pth?dl=1', full_name)
        print("Downloading done.\n")
    else:
        print(f"{full_name} has already been downloaded. Did not download twice.\n")

def download_aircraft():
    dir_path = RAW_DATA_PATH
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)
    file_name = os.path.join(dir_path, 'fgvc-aircraft-2013b.tar.gz')

    if not os.path.exists(file_name):
        print(f"Downloading {file_name}\n")
        download_file(
            'http://www.robots.ox.ac.uk/~vgg/data/fgvc-aircraft/archives/fgvc-aircraft-2013b.tar.gz',
            file_name)
        print("\nDownloading done.\n")
    else:
        print("fgvc-aircraft-2013b.tar.gz has already been downloaded. Did not download twice.\n")

    untar_file_name = os.path.join(dir_path, 'aircraft')
    if not os.path.exists(untar_file_name):
        tarname = file_name
        print("Untarring: {}".format(tarname))
        tar = tarfile.open(tarname)
        tar.extractall(untar_file_name)
        tar.close()
    else:
        print(f"{untar_file_name} folder already exists. Did not untarring twice\n")
    os.remove(file_name)

if __name__ == "__main__":
    download_pets()
    download_aircraft()