import urllib.request
from utils import winbindexer
from pathlib import Path


dbfile = "mrxsmb.sys.json.gz"
filename = "mrxsmb.sys"
windows_version = "11-24H2"

SCRIPT_DIR = Path(__file__).parent
tracking_file = SCRIPT_DIR / "version.log"


def download_file(url: str, dest: Path):
    try:
        urllib.request.urlretrieve(url, dest)
    except Exception as e:
        raise RuntimeError(f"[!] Download error: {e}")


def check_and_download():
    try:
        winbindexer.ensure_winbindex_repo()
        results = winbindexer.get_latest_symbol_urls(filename, dbfile, windows_version)

        if len(results) < 2:
            raise ValueError("[!] Could not find two version")

        new_version_url = results[0]["url"]
        old_version_url = results[1]["url"]

        if tracking_file.exists():
            last_known = tracking_file.read_text(encoding="utf-8").strip()
            if last_known == new_version_url:
                return False

        old_path = SCRIPT_DIR / f"old.{filename}"
        new_path = SCRIPT_DIR / f"new.{filename}"

        download_file(old_version_url, old_path)
        download_file(new_version_url, new_path)

        tracking_file.write_text(new_version_url + "\n", encoding="utf-8")

        return str(old_path), str(new_path)

    except (FileNotFoundError, ValueError, RuntimeError) as e:
        print(f"[!] Error: {e}")
        return "", ""

