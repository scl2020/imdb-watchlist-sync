#!/usr/bin/env python3
"""Mirror one public IMDb watchlist into JSON and CSV (no credentials needed).

Uses IMDb's public-web GraphQL endpoint; this is unofficial and can change or
be blocked. Never replaces an existing good snapshot with a partial response.
"""

import csv
import io
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROFILE_ID = os.environ.get("IMDB_PROFILE_ID", "p.pxpvlyl52ptzto5nuczrkyaiha")
WATCHLIST_URL = f"https://www.imdb.com/user/{PROFILE_ID}/watchlist/"
ENDPOINTS = ("https://caching.graphql.imdb.com/", "https://api.graphql.imdb.com/")
PAGE_SIZE = 250
MAX_PAGES = 60
MIN_INITIAL_ITEMS = int(os.environ.get("MIN_INITIAL_ITEMS", "1000"))
MAX_DROP_FRACTION = float(os.environ.get("MAX_DROP_FRACTION", "0.20"))
ROOT = Path(__file__).resolve().parent.parent
JSON_PATH = ROOT / "movies.json"
CSV_PATH = ROOT / "movies.csv"

HEADERS = {
    "Accept": "application/graphql-response+json, application/json",
    "Content-Type": "application/json",
    "Origin": "https://www.imdb.com",
    "Referer": "https://www.imdb.com/",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
    "x-imdb-client-name": "imdb-web-next",
    "x-imdb-user-language": "en-US",
}

RESOLVE_QUERY = """query ResolveProfile($profileId: ID!) {
  userProfile(input: {profileId: $profileId}) { userId }
}"""

LIST_QUERY = """query WatchListPage($urConst: ID!, $first: Int!, $after: String) {
  predefinedList(classType: WATCH_LIST, userId: $urConst) {
    id
    titleListItemSearch(first: $first, after: $after) {
      total
      pageInfo { hasNextPage endCursor }
      edges {
        listItem: title {
          id
          titleText { text }
          titleType { text }
          releaseYear { year }
          ratingsSummary { aggregateRating }
          titleGenres { genres { genre { text } } }
          runtime { seconds }
          plot { plotText { plainText } }
        }
      }
    }
  }
}"""


def graph(query, variables):
    """POST an IMDb query, bounded retries on transient failures."""
    body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    error = None
    for endpoint in ENDPOINTS:
        for attempt in range(3):
            try:
                req = Request(endpoint, body, HEADERS, method="POST")
                with urlopen(req, timeout=35) as response:
                    payload = json.load(response)
                if payload.get("errors"):
                    raise RuntimeError(f"IMDb GraphQL errors: {str(payload['errors'])[:600]}")
                if not isinstance(payload.get("data"), dict):
                    raise RuntimeError("IMDb GraphQL returned no data")
                return payload["data"]
            except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
                error = exc
                code = getattr(exc, "code", None)
                if code in (400, 401, 403, 404) or attempt == 2:
                    print(f"IMDb endpoint {endpoint} failed: {exc}", file=sys.stderr)
                    break
                time.sleep(2**attempt)
    raise RuntimeError(f"IMDb is inaccessible; preserving existing files. Last error: {error}")


def resolve_profile(profile_id):
    if not re.fullmatch(r"p\.[a-z0-9]+", profile_id):
        raise ValueError("Expected an IMDb profile id starting with 'p.'")
    result = graph(RESOLVE_QUERY, {"profileId": profile_id})
    user_id = (result.get("userProfile") or {}).get("userId")
    if not isinstance(user_id, str) or not re.fullmatch(r"ur\d+", user_id):
        raise RuntimeError("Could not resolve public IMDb profile. Is the watchlist public?")
    return user_id


def normalize_title(node):
    if not isinstance(node, dict):
        raise ValueError("IMDb returned an invalid title node")
    imdb_id = node.get("id")
    title = (node.get("titleText") or {}).get("text")
    if not isinstance(imdb_id, str) or not re.fullmatch(r"tt\d+", imdb_id) or not title:
        raise ValueError(f"IMDb returned an incomplete title node: {str(node)[:140]}")
    genres = []
    for g in (node.get("titleGenres") or {}).get("genres") or []:
        label = ((g or {}).get("genre") or {}).get("text")
        if label and label not in genres:
            genres.append(label)
    seconds = (node.get("runtime") or {}).get("seconds")
    return {
        "imdb_id": imdb_id,
        "title": title,
        "year": (node.get("releaseYear") or {}).get("year"),
        "type": (node.get("titleType") or {}).get("text"),
        "imdb_rating": (node.get("ratingsSummary") or {}).get("aggregateRating"),
        "genres": genres,
        "runtime_minutes": round(seconds / 60) if isinstance(seconds, (int, float)) else None,
        "plot": ((node.get("plot") or {}).get("plotText") or {}).get("plainText"),
        "imdb_url": f"https://www.imdb.com/title/{imdb_id}/",
    }


def get_watchlist(user_id):
    titles = []
    seen = set()
    cursor = None
    expected_total = None
    for page in range(1, MAX_PAGES + 1):
        response = graph(LIST_QUERY, {"urConst": user_id, "first": PAGE_SIZE, "after": cursor})
        watchlist = response.get("predefinedList")
        if not isinstance(watchlist, dict):
            raise RuntimeError("IMDb watchlist is private, unavailable, or not found")
        search = watchlist.get("titleListItemSearch")
        if not isinstance(search, dict):
            raise RuntimeError("IMDb watchlist response is missing titleListItemSearch")
        total = search.get("total")
        if not isinstance(total, int) or total <= 0:
            raise RuntimeError("IMDb returned an invalid or empty watchlist total")
        if expected_total is None:
            expected_total = total
        elif total != expected_total:
            raise RuntimeError("IMDb list changed while paginating; retry on the next run")
        edges = search.get("edges")
        info = search.get("pageInfo")
        if not isinstance(edges, list) or not isinstance(info, dict):
            raise RuntimeError("IMDb list page was incomplete")
        if not edges:
            raise RuntimeError("IMDb returned an empty page of a nonempty list")
        for edge in edges:
            item = normalize_title((edge or {}).get("listItem"))
            if item["imdb_id"] in seen:
                raise RuntimeError("IMDb returned duplicate titles while paginating")
            seen.add(item["imdb_id"])
            titles.append(item)
        print(f"Page {page}: {len(titles)}/{expected_total} titles")
        if len(titles) > expected_total:
            raise RuntimeError("IMDb returned more titles than expected")
        if not info.get("hasNextPage"):
            if len(titles) != expected_total:
                raise RuntimeError(f"Incomplete IMDb export: got {len(titles)} of {expected_total}")
            return titles
        next_cursor = info.get("endCursor")
        if not next_cursor or next_cursor == cursor:
            raise RuntimeError("IMDb pagination cursor missing or repeated")
        cursor = next_cursor
    raise RuntimeError("Exceeded IMDb page limit; refusing partial export")


def load_existing():
    if not JSON_PATH.exists():
        return None
    try:
        old = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(f"Existing snapshot is invalid; refusing overwrite: {exc}") from exc
    if not isinstance(old, dict) or not isinstance(old.get("items"), list):
        raise RuntimeError("Existing snapshot is missing items; refusing overwrite")
    return old


def check_safety(items, previous):
    if len(items) < MIN_INITIAL_ITEMS:
        raise RuntimeError(f"Only {len(items)} titles retrieved, below safety floor {MIN_INITIAL_ITEMS}")
    if previous:
        old_count = len(previous["items"])
        if old_count and len(items) < old_count * (1 - MAX_DROP_FRACTION):
            raise RuntimeError(f"Suspicious drop from {old_count} to {len(items)}; preserving old snapshot")


def to_csv(items):
    columns = ["imdb_id", "title", "year", "type", "imdb_rating", "genres", "runtime_minutes", "plot", "imdb_url"]
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for item in items:
        writer.writerow({**item, "genres": ", ".join(item["genres"])})
    return buf.getvalue()


def sync():
    old = load_existing()
    user_id = resolve_profile(PROFILE_ID)
    print(f"Resolved IMDb profile to {user_id}")
    items = get_watchlist(user_id)
    check_safety(items, old)
    # Sorting by id avoids committing a change merely because IMDb reorders items.
    items.sort(key=lambda item: item["imdb_id"])
    if old is not None and old["items"] == items and CSV_PATH.exists():
        print(f"No changes: {len(items)} titles; no files modified")
        return
    snapshot = {
        "source": "IMDb public watchlist",
        "watchlist_url": WATCHLIST_URL,
        "count": len(items),
        "updated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "items": items,
    }
    JSON_PATH.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    CSV_PATH.write_text(to_csv(items), encoding="utf-8")
    print(f"Saved {len(items)} titles to {JSON_PATH.name} and {CSV_PATH.name}")


if __name__ == "__main__":
    try:
        sync()
    except Exception as exc:
        print(f"SYNC FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
