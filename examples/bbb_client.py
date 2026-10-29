"""BBB business profiles, ratings, complaints and reviews through ScrapingBee.

Measured on 2026-10-29 against public www.bbb.org pages:

* Every page type embeds its data as window.__PRELOADED_STATE__, a JSON
  object written by the server. No JavaScript rendering is needed.
* /search answered a plain request: 1 credit.
* /profile/... pages (overview, /complaints, /customer-reviews) returned
  403 to plain requests (ScrapingBee turns that into an unbilled 500) and
  200 on premium proxies: 10 credits. fetch() steps up a tier only on a
  500, so a 403 costs time, not credits. Profile calls start on premium
  because the plain tier never worked for them in testing.

Set SCRAPINGBEE_API_KEY in your environment before running.
"""

import argparse
import csv
import html
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, fields
from urllib.parse import urlencode

import requests

API = "https://app.scrapingbee.com/api/v1/"
BBB = "https://www.bbb.org"
STATE = re.compile(r"window\.__PRELOADED_STATE__\s*=\s*")
TAGS = re.compile(r"<[^>]+>")

TIERS = [
    {"render_js": "false"},                           # 1 credit
    {"render_js": "false", "premium_proxy": "true"},  # 10 credits
]


def _text(value):
    return re.sub(r"\s+", " ", html.unescape(TAGS.sub(" ", value or ""))).strip()


def _date(d):
    if not d:
        return ""
    return f"{d.get('year')}-{d.get('month')}-{d.get('day')}"


@dataclass
class SearchHit:
    business_id: str
    bbb_id: str
    name: str
    category: str
    rating: str              # letter grade; empty when BBB shows none
    accredited: bool         # bbbMember
    city: str
    state: str
    phone: str
    local_bbb: str
    profile_url: str


@dataclass
class Profile:
    name: str
    other_names: str
    bbb_rating: str
    rating_notes: str
    accredited: bool
    accredited_since: str
    business_started: str
    bbb_file_opened: str
    categories: str
    street: str
    city: str
    state: str
    zip: str
    phone: str
    website: str
    local_bbb: str
    reviews_total: int
    review_stars_avg: float
    complaints_3y: int
    complaints_closed_12m: int
    out_of_business: bool
    url: str


@dataclass
class Complaint:
    complaint_id: str
    filed: str
    type: str
    status: str              # Answered, Resolved, Unanswered ...
    text: str
    replies: int
    business_replies: int
    last_reply_by: str       # business or consumer
    last_reply_date: str


@dataclass
class Review:
    review_id: str
    date: str
    stars: int
    author: str              # first name and initial, as BBB shows it
    text: str
    business_response: str


class BBBClient:
    def __init__(self, api_key=None, retries=2, log=print):
        key = api_key or os.environ.get("SCRAPINGBEE_API_KEY")
        if not key:
            sys.exit("Set SCRAPINGBEE_API_KEY first.")
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {key}"
        self.retries = retries
        self.log = log
        self.credits = 0

    def fetch(self, url, start_tier=0):
        """Walk up TIERS on unbilled 500s. Returns the parsed page state."""
        for tier in TIERS[start_tier:]:
            for attempt in range(self.retries):
                r = self.session.get(API, params={"url": url, **tier}, timeout=120)
                self.credits += int(r.headers.get("spb-cost") or 0)
                if r.status_code == 200:
                    m = STATE.search(r.text)
                    if m:
                        state, _ = json.JSONDecoder().raw_decode(r.text[m.end():])
                        return state
                    self.log("  200 without __PRELOADED_STATE__, retrying")
                elif r.status_code != 500:
                    r.raise_for_status()
                time.sleep(2)
            self.log(f"  tier {tier} failed, stepping up")
        raise RuntimeError(f"no data for {url}")

    # -- search --------------------------------------------------------
    def search(self, text, location, page=1):
        """15 results per page. BBB stops paging at 15 pages (225 results)
        even when totalResults is in the thousands, so narrow the query or
        the location instead of paging further."""
        q = {"find_country": "USA", "find_text": text, "find_loc": location, "page": page}
        state = self.fetch(f"{BBB}/search?{urlencode(q)}")
        sr = state["searchResult"]
        hits, seen = [], set()
        for r in sr.get("results") or []:
            # A business with several addresses can appear more than once on
            # the same page, each time with a different address id in r["id"].
            key = (r.get("bbbId"), r.get("businessId"))
            if key in seen:
                continue
            seen.add(key)
            hits.append(SearchHit(
                business_id=r.get("businessId", ""),
                bbb_id=r.get("bbbId", ""),
                name=_text(r.get("businessName")),  # strips the <em> highlight
                category=r.get("tobText", ""),
                rating=r.get("rating") or "",
                accredited=bool(r.get("bbbMember")),
                city=r.get("city", ""),
                state=r.get("state", ""),
                phone=(r.get("phone") or [""])[0],
                local_bbb=r.get("bbbName", ""),
                profile_url=BBB + r["reportUrl"],
            ))
        meta = {k: sr.get(k) for k in ("page", "pageSize", "totalPages", "totalResults")}
        meta["duplicates_dropped"] = len(sr.get("results") or []) - len(hits)
        return meta, hits

    # -- profile pages -------------------------------------------------
    @staticmethod
    def _base(url):
        if url.startswith("/"):
            url = BBB + url                     # accept a bare profile path
        return re.sub(r"/(complaints|customer-reviews)(\?.*)?$", "", url.rstrip("/"))

    def profile(self, url):
        bp = self.fetch(self._base(url), start_tier=1)["businessProfile"]
        return self._profile(bp)

    def _profile(self, bp):
        loc = (bp.get("location") or {}).get("postalAddress") or {}
        summ = bp.get("reviewsComplaintsSummary") or {}
        rating = bp.get("rating") or {}
        dates = bp.get("dates") or {}
        acc = bp.get("accreditationInformation") or {}
        names = bp.get("names") or {}
        return Profile(
            name=names.get("primary", ""),
            other_names="; ".join(names.get("altBusinessNames") or []),
            bbb_rating=rating.get("bbbRating") or "",
            rating_notes=" | ".join(rating.get("ratingReasons") or []),
            accredited=bool(acc.get("isAccredited")),
            accredited_since=(dates.get("accredited") or "")[:10],
            business_started=(dates.get("businessStart") or "")[:10],
            bbb_file_opened=(dates.get("bbbFileOpened") or "")[:10],
            categories="; ".join(c["title"] for c in (bp.get("categories") or {}).get("links", [])),
            street=loc.get("addressLine1") or "",
            city=loc.get("city") or "",
            state=loc.get("stateCode") or "",
            zip=loc.get("zipCode") or "",
            phone=(bp.get("contactInformation") or {}).get("phoneNumber") or "",
            website=(bp.get("urls") or {}).get("primary") or "",
            local_bbb=(bp.get("localBbbData") or {}).get("name", ""),
            reviews_total=summ.get("reviewsTotal") or 0,
            review_stars_avg=summ.get("averageOfReviewStarRatings"),
            complaints_3y=summ.get("complaintsTotal") or 0,
            complaints_closed_12m=summ.get("totalClosedComplaintsPastTwelveMonths") or 0,
            out_of_business=bool((bp.get("orgDetails") or {}).get("isOutOfBusiness")),
            url=BBB + (bp.get("urls") or {}).get("profile", ""),
        )

    def complaints(self, url, pages=1):
        """10 complaints per page, newest first. Returns (meta, [Complaint])."""
        out, meta = [], {}
        for page in range(1, pages + 1):
            bp = self.fetch(f"{self._base(url)}/complaints?page={page}", start_tier=1)["businessProfile"]
            cc = bp.get("customerComplaints") or {}
            if page == 1:
                meta = {
                    "found": cc.get("numFound"),
                    "hidden": cc.get("numHidden"),
                    "by_status": {f["slug"]: f["count"] for f in (cc.get("filters") or {}).get("status", [])},
                    "by_type": {f["slug"]: f["count"] for f in (cc.get("filters") or {}).get("type", [])},
                    "profile": self._profile(bp),
                }
            items = cc.get("items") or []
            for c in items:
                replies = c.get("responses") or []
                last = replies[-1] if replies else {}
                out.append(Complaint(
                    complaint_id=c.get("id", ""),
                    filed=_date(c.get("date")),
                    type=c.get("type", ""),
                    status=c.get("status", ""),
                    text=_text(c.get("text")),
                    replies=len(replies),
                    business_replies=sum(r.get("type") == "business" for r in replies),
                    last_reply_by=last.get("type", ""),
                    last_reply_date=_date(last.get("date")),
                ))
            if len(items) < 10:
                break
        return meta, out

    def reviews(self, url, pages=1):
        """10 reviews per page, newest first. Returns (meta, [Review])."""
        out, meta = [], {}
        for page in range(1, pages + 1):
            bp = self.fetch(f"{self._base(url)}/customer-reviews?page={page}", start_tier=1)["businessProfile"]
            cr = bp.get("customerReviews") or {}
            if page == 1:
                meta = {k: cr.get(k) for k in ("numFound", "pageSize", "totalPages", "sort")}
            items = cr.get("items") or []
            for r in items:
                out.append(Review(
                    review_id=r.get("id", ""),
                    date=_date(r.get("date")),
                    stars=r.get("reviewStarRating"),
                    author=r.get("displayName", ""),
                    text=_text(r.get("text")),
                    business_response=_text(r.get("businessResponseText")),
                ))
            if page >= (cr.get("totalPages") or 0):
                break
        return meta, out


def write_csv(rows, path):
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=[f.name for f in fields(rows[0])])
        w.writeheader()
        w.writerows(asdict(r) for r in rows)


def main():
    ap = argparse.ArgumentParser(description="Public BBB pages via ScrapingBee")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search")
    s.add_argument("text")
    s.add_argument("location", help='e.g. "Phoenix, AZ"')
    s.add_argument("--pages", type=int, default=1)
    s.add_argument("--csv")
    for name in ("profile", "complaints", "reviews"):
        p = sub.add_parser(name)
        p.add_argument("url", help="a bbb.org profile URL, or its path from /us/...")
        p.add_argument("--pages", type=int, default=1)
        p.add_argument("--csv")
    a = ap.parse_args()
    c = BBBClient()

    if a.cmd == "search":
        rows = []
        for page in range(1, a.pages + 1):
            meta, hits = c.search(a.text, a.location, page)
            rows += hits
            if page >= (meta["totalPages"] or 0):
                break
        print(f"{meta['totalResults']} results, {meta['totalPages']} pages reachable, "
              f"{len(rows)} read, {c.credits} credits")
        for h in rows[:10]:
            print(f"  {h.rating or '-':3} {'ACC' if h.accredited else '   '} {h.name[:40]:40} {h.city}, {h.state}")
        if a.csv:
            write_csv(rows, a.csv)
    elif a.cmd == "profile":
        print(json.dumps(asdict(c.profile(a.url)), indent=2))
        print(f"{c.credits} credits")
    elif a.cmd == "complaints":
        meta, rows = c.complaints(a.url, a.pages)
        meta.pop("profile")
        print(json.dumps(meta))
        for r in rows[:6]:
            print(f"  {r.filed} {r.status:10} {r.type[:28]:28} replies {r.replies}  {r.text[:50]}")
        print(f"{len(rows)} complaints read, {c.credits} credits")
        if a.csv:
            write_csv(rows, a.csv)
    else:
        meta, rows = c.reviews(a.url, a.pages)
        print(json.dumps(meta))
        for r in rows[:6]:
            print(f"  {r.date} {r.stars}* {r.author:10} {r.text[:60]}")
        print(f"{len(rows)} reviews read, {c.credits} credits")
        if a.csv:
            write_csv(rows, a.csv)


if __name__ == "__main__":
    main()
