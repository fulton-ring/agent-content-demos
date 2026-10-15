"""A requests session that retries dropped connections and server errors."""

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def session() -> requests.Session:
    retry = Retry(total=5, backoff_factor=2, status_forcelist=(502, 503, 504), allowed_methods=None)
    client = requests.Session()
    client.mount("https://", HTTPAdapter(max_retries=retry))
    return client
