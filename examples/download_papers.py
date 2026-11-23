"""Download draft PDFs of papers whose sources restrict redistribution."""
import urllib.request
from pathlib import Path

PAPERS = Path(__file__).resolve().parent / "papers"

# NBER working papers may not be redistributed, so they are downloaded
# on demand instead of committed. FRBSF and other Fed working papers
# are freely distributable with attribution and can be committed directly.
URLS = {
    "nakamura_steinsson_w24603.pdf": "https://www.nber.org/system/files/working_papers/w24603/w24603.pdf",
    "bauer_bernanke_milstein_jep2023.pdf": "https://www.michaeldbauer.com/files/bbm_risk.pdf",
}


def run():
    PAPERS.mkdir(parents=True, exist_ok=True)
    for name, url in URLS.items():
        dest = PAPERS / name
        if dest.exists():
            print(f"exists: {dest.name}")
            continue
        urllib.request.urlretrieve(url, dest)
        data = dest.read_bytes()
        if not data.startswith(b"%PDF"):
            dest.unlink()
            raise AssertionError(f"{url} did not return a PDF")
        print(f"wrote {dest.name} ({len(data) // 1024} KB)")


if __name__ == "__main__":
    run()
