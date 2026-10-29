"""Compare businesses side by side on what their BBB pages show.

    python bbb_compare.py --search "moving company" "Phoenix, AZ" --top 3
    python bbb_compare.py --urls <profile url> <profile url> --out compare.csv

For each business: one complaints page (it carries the full profile too)
and one reviews page, 20 credits per business. The search, if used, is
1 credit.

Columns worth reading together:
  complaints_3y vs reviews_total   volume of each channel
  resolved_share_pct               resolved / (answered + resolved)
  recent_stars vs stars_avg        last 10 reviews against the lifetime mean
  hidden                           complaints counted but not displayed

Needs bbb_client.py in the same folder and SCRAPINGBEE_API_KEY set.
"""

import argparse
import csv
import json
from collections import Counter

from bbb_client import BBBClient


def summarise(client, url):
    meta, complaints = client.complaints(url, pages=1)
    profile = meta["profile"]
    rmeta, reviews = client.reviews(url, pages=1)

    status = meta.get("by_status") or {}
    answered, resolved = status.get("answered", 0), status.get("resolved", 0)
    stars = [r.stars for r in reviews if r.stars]
    top_type = Counter(meta.get("by_type") or {}).most_common(1)
    return {
        "name": profile.name,
        "bbb_rating": profile.bbb_rating,
        "accredited": profile.accredited,
        "accredited_since": profile.accredited_since,
        "city": profile.city,
        "state": profile.state,
        "complaints_3y": profile.complaints_3y,
        "complaints_found": meta.get("found"),
        "hidden": meta.get("hidden"),
        "resolved_share_pct": round(100 * resolved / (answered + resolved)) if answered + resolved else "",
        "top_complaint_type": top_type[0][0] if top_type else "",
        "latest_complaint": complaints[0].filed if complaints else "",
        "reviews_total": profile.reviews_total,
        "stars_avg": profile.review_stars_avg,
        "recent_stars": round(sum(stars) / len(stars), 2) if stars else "",
        "recent_reviews_with_reply": sum(bool(r.business_response) for r in reviews),
        "latest_review": reviews[0].date if reviews else "",
        "url": profile.url,
    }


def main():
    ap = argparse.ArgumentParser(description="BBB side by side comparison")
    ap.add_argument("--search", nargs=2, metavar=("TEXT", "LOCATION"))
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument("--urls", nargs="*", default=[])
    ap.add_argument("--out", default="bbb_compare.csv")
    ap.add_argument("--json")
    a = ap.parse_args()

    client = BBBClient()
    urls = list(a.urls)
    if a.search:
        _, hits = client.search(*a.search)
        urls += [h.profile_url for h in hits[: a.top]]
    if not urls:
        ap.error("give --urls or --search")

    rows = []
    for url in urls:
        print(f"reading {url}")
        rows.append(summarise(client, url))

    with open(a.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, indent=2)

    for r in rows:
        print(f"  {r['name'][:30]:30} {r['bbb_rating']:3} complaints {r['complaints_3y']:>5} "
              f"resolved {r['resolved_share_pct']}%  stars {r['stars_avg']} (recent {r['recent_stars']})")
    print(f"{len(rows)} businesses, {client.credits} credits, wrote {a.out}")


if __name__ == "__main__":
    main()
