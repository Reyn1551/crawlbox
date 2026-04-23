"""HTML ke teks bersih."""
import re
from bs4 import BeautifulSoup, Tag
NOISE = ["script","style","noscript","nav","footer","aside","header","[role='navigation']","[role='banner']",".ad",".ads","#cookie-banner",".sidebar",".modal","iframe","svg","img"]
def extract_clean_text(soup):
    clean = BeautifulSoup(str(soup), "html.parser")
    for sel in NOISE:
        for el in clean.select(sel): el.decompose()
    return re.sub(r"\s+", " ", (clean.find("body") or clean).get_text(separator=" ", strip=True)).strip()
def extract_main_content(soup):
    for sel in ["main","article","[role='main']",".content","#content"]:
        el = soup.select_one(sel)
        if el and isinstance(el, Tag): return extract_clean_text(BeautifulSoup(str(el), "html.parser"))
    return extract_clean_text(soup)