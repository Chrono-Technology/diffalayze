import json
import gzip
import subprocess
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
REPO_DIR = BASE_DIR / "winbindex"
DATA_DIR = REPO_DIR / "data" / "by_filename_compressed"


def _reclone_repo(repo_dir: Path, repo_url: str, branch: str):
    import shutil
    shutil.rmtree(repo_dir, ignore_errors=True)
    subprocess.run([
        "git", "clone", "--branch", branch, "--single-branch",
        repo_url, str(repo_dir)
    ], check=True)


def ensure_winbindex_repo(repo_url="https://github.com/m417z/winbindex.git", branch="gh-pages"):
    if not REPO_DIR.exists():
        print("[*] Cloning winbindex repo (this may take some time)")
        subprocess.run([
            "git", "clone", "--branch", branch, "--single-branch",
            repo_url, str(REPO_DIR)
        ], check=True)
        return

    if not (REPO_DIR / ".git").is_dir():
        print("[!] winbindex directory exists but is not a valid Git repo. Re-cloning...")
        _reclone_repo(REPO_DIR, repo_url, branch)
        return

    try:
        subprocess.run(["git", "-C", str(REPO_DIR), "checkout", branch], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["git", "-C", str(REPO_DIR), "pull", "origin", branch], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        print("[!] Git pull failed. Repository may be corrupt. Re-cloning...")
        _reclone_repo(REPO_DIR, repo_url, branch)


def generate_url(filename: str, timestamp: int, virtual_size: int) -> str:
    timestamp_hex = f"{timestamp:X}"
    size_hex = f"{virtual_size:X}"
    return f"https://msdl.microsoft.com/download/symbols/{filename}/{timestamp_hex}{size_hex}/{filename}"


def get_latest_symbol_urls(filename: str, dbfile: str, windows_version: str, count: int = 2):
    json_gz_path = DATA_DIR / dbfile

    with gzip.open(json_gz_path, "rt", encoding="utf-8") as f:
        data = json.load(f)

    versions = []
    for sha256, entry in data.items():
        file_info = entry.get("fileInfo", {})
        timestamp = file_info.get("timestamp")
        virtual_size = file_info.get("virtualSize")
        win_versions = entry.get("windowsVersions", {})

        if timestamp and virtual_size and windows_version in win_versions:
            versions.append({
                "timestamp": timestamp,
                "virtual_size": virtual_size,
                "sha256": sha256,
                "filename": filename
            })

    versions = sorted(versions, key=lambda v: v["timestamp"], reverse=True)

    if not versions:
        raise ValueError(f"[!] No versions for {windows_version} found")

    return [
        {
            "sha256": v["sha256"],
            "timestamp": v["timestamp"],
            "virtual_size": v["virtual_size"],
            "url": generate_url(v["filename"], v["timestamp"], v["virtual_size"]),
        }
        for v in versions[:count]
    ]

