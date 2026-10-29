# Better Business Bureau API

<p align="center">
  <a href="https://www.scrapingbee.com/">
    <img src="REPLACE_WITH_SCREENSHOT_URL" alt="better-business-bureau-api" />
  </a>
</p>

[![checks](https://github.com/ScrapingBee/better-business-bureau-api/workflows/checks/badge.svg)](https://github.com/ScrapingBee/better-business-bureau-api/actions)
[![license](https://img.shields.io/github/license/ScrapingBee/better-business-bureau-api.svg)](LICENSE)

This README is a list of the questions we had while building a [Better Business Bureau API](https://www.scrapingbee.com/scrapers/better-business-bureau-api/) client on [ScrapingBee](https://www.scrapingbee.com/), each answered with what bbb.org returned on 2026-10-29 and the code that reads it. It covers search, the business profile, the letter grade, accreditation, complaints and customer reviews, all from public pages that anyone can open without an account. The code lives in [`examples/`](examples/).

## Where does bbb.org keep the data?

In one JSON object per page. Search, profile, complaints and reviews pages all end with a script that sets `window.__PRELOADED_STATE__`, and the server writes it in full, so no JavaScript rendering is needed. On a profile page it looks like this (trimmed):

```js
window.__PRELOADED_STATE__ = {"user": {...}, "page": {...}, "businessProfile": {
  "bbbId": "0875", "businessId": "23004916",
  "rating": {"bbbRating": "A+", "ratingReasonNotRated": null, "ratingReasons": []},
  "accreditationInformation": {"status": 0, "isAccredited": true, "countryCode": 2},
  "reviewsComplaintsSummary": {"averageOfReviewStarRatings": 3.61, "reviewsTotal": 2672,
     "complaintsTotal": 1575, "totalClosedComplaintsPastThreeYears": 1575,
     "totalClosedComplaintsPastTwelveMonths": 380, ...},
  "dates": {"accredited": "2020-08-10T00:00:00", "bbbFileOpened": "1999-03-01T00:00:00",
            "businessStart": "1998-07-14T00:00:00", ...}, ...}}
```

A JSON-LD block on the profile repeats the headline facts as schema.org properties, which is useful as a cross check when you parse the state object:

```json
"additionalProperty": [
  {"@type": "PropertyValue", "value": "BBB Accredited Business", "name": "BBB Accreditation"},
  {"@type": "PropertyValue", "value": "A+", "name": "BBB Rating"},
  {"@type": "PropertyValue", "value": "1", "name": "BBB Complaints Filed in Last 3 Years"},
  {"@type": "PropertyValue", "value": "2", "name": "BBB Customer Reviews"}]
```

Reading the state object in Python:

```python
STATE = re.compile(r"window\.__PRELOADED_STATE__\s*=\s*")
m = STATE.search(page_source)
data, _ = json.JSONDecoder().raw_decode(page_source[m.end():])
profile = data["businessProfile"]
```

`raw_decode` stops at the end of the object and ignores whatever script follows it.

## Which ScrapingBee settings does each page need, and what do they cost?

| Page | Plain request (1 credit) | Premium proxy, no JS (10 credits) |
|---|---|---|
| `/search?find_text=...&find_loc=...` | 200, every time we tried | not needed |
| `/us/<st>/<city>/profile/<category>/<slug>` | 403 from BBB, unbilled 500 from ScrapingBee | 200 |
| `.../complaints?page=N` | not tried after the profile result | 200 |
| `.../customer-reviews?page=N` | not tried after the profile result | 200 |

Auto Mode (`mode=auto`, `max_cost=25`) on a profile landed on the same answer: `spb-cost: 10`, but it took 34 seconds to climb there. The client in [`examples/bbb_client.py`](examples/bbb_client.py) sends search on the plain tier and profile pages straight to premium, and steps up a tier on a 500 if one ever appears:

```python
TIERS = [
    {"render_js": "false"},                           # 1 credit
    {"render_js": "false", "premium_proxy": "true"},  # 10 credits
]
```

`render_js` must be set to `false` explicitly. It defaults to true on ScrapingBee and would add JavaScript cost to pages that do not need it.

## How do I search BBB and how far can I page?

15 businesses a page, and BBB stops at page 15. A search for roofing near Austin, TX reported 6,458 results:

```json
{"page": 15, "pageSize": 15, "totalPages": 15, "totalResults": 6458}
```

Page 16 came back empty: `"page": 16, "totalPages": 0, "totalResults": 0, "results": []`. So one query yields at most 225 businesses. To cover a category, split by city or zip and run more queries.

Two quirks in the result list. Business names come with the search highlight still in them, `"businessName": "Stevan Buren <em>Roofing</em>, Windows, and Flooring"`, which the client strips. And a business with several addresses can show up more than once on the same page, each time with a different address id in `id`. On "two men and a truck" near Phoenix, 13 results were 9 businesses. The client dedupes on `(bbbId, businessId)`.

```
$ python examples/bbb_client.py search "moving company" "Phoenix, AZ" --pages 2 --csv movers.csv
897 results, 15 pages reachable, 28 read, 2 credits
  A+  ACC Thomas Logistics LLC                     Phoenix, AZ
  A+  ACC Alex Moving & Storage Co                 Phoenix, AZ
  A+  ACC Atlasta Moving Company                   Phoenix, AZ
  A+  ACC NonStop Moving                           Phoenix, AZ
```

The `city` on a search hit is the address that matched your location. Alex Moving & Storage shows Phoenix in the result, while its profile URL lives under `/us/ca/anaheim/`.

## What does the BBB API give me for one business profile?

```
$ python examples/bbb_client.py profile /us/tx/carrollton/profile/moving-and-storage-companies/all-my-sons-moving-storage-0875-23004916
{
  "name": "All My Sons Moving & Storage",
  "other_names": "All My Sons Moving & Storage of Dallas, LLC; All My Sons Moving & Storage, Inc; ...",
  "bbb_rating": "A+",
  "accredited": true,
  "accredited_since": "2020-08-10",
  "business_started": "1998-07-14",
  "bbb_file_opened": "1999-03-01",
  "categories": "Moving and Storage Companies; Moving Companies; Moving Services; Long Distance Movers; ...",
  "city": "Carrollton",
  "state": "TX",
  "local_bbb": "BBB serving North Central Texas",
  "reviews_total": 2672,
  "review_stars_avg": 3.61,
  "complaints_3y": 1575,
  "complaints_closed_12m": 380,
  "out_of_business": false,
  ...
}
10 credits
```

`other_names` held 74 registered names for that one profile, one LLC per metro area. If you match businesses across sources, match on these as well as on the primary name.

The state also carries the business email address in an obfuscated form. The client does not collect it.

## How is the letter grade different from the star rating?

They are separate numbers from separate inputs, and BBB says so in the data. A small roofing contractor's profile carried this in `rating.ratingReasons`:

> "Customer Reviews are not used in the calculation of the BBB Letter Grade Rating."

That is how All My Sons can hold an A+ grade with a 3.61 star review average and 1,575 complaints in three years. Store `bbb_rating` and `review_stars_avg` as two columns and never derive one from the other. A business BBB has not graded shows `"bbbRating": "NR"` on its profile and an empty `rating` in search results; one of the Phoenix movers we compared was in that state.

## How do I read accreditation?

Three places agree with each other:

* `accreditationInformation.isAccredited` on the profile (`true` or `false`)
* `dates.accredited` for the start date; `dates.accreditationRevoked` exists too and was null on every profile we read
* `bbbMember` on each search hit

Every one of the 28 movers on the first two search pages was accredited, and so were all 29 roofers in the Node run below. We did not test how the default "Best Match" sort treats accreditation, so do not read the share of accredited businesses in a category off its first pages.

## How do I get complaints, and how many does the page show?

Ten per page, newest first, via `?page=N`:

```
$ python examples/bbb_client.py complaints <profile url> --pages 2 --csv complaints.csv
{"found": 1531, "hidden": 44, "by_status": {"answered": 1326, "resolved": 249}, "by_type": {"serviceorrepair": 1055, "productissues": 200, "order": 111, "salesadvertising": 97, "billingissues": 55, "customerservice": 36, "delivery": 21}}
  2026-10-02 Resolved   Order Issues                 replies 2  On May 12, 2026, All My Sons Moving & Storage of *
  2026-09-28 Resolved   Service or Repair Issues     replies 2  I hired *********** moving on June 12th to move my
  2026-09-25 Answered   Service or Repair Issues     replies 1  My wife and I used this company last year for a mo
20 complaints read, 20 credits
```

Things to know before you count anything:

* The headline total and the list differ. 1,575 complaints in the summary, `numFound: 1531` in the list, and `numHidden: 44`. Report which number you use.
* The counts are for closed complaints. The summary field is literally `totalClosedComplaintsPastThreeYears`, and the newest complaint on the list was filed on 2 October while the newest review was from 26 October. Open complaints do not show up here.
* `filters.status` and `filters.type` give you the full breakdown for the profile in one request, no paging needed.
* BBB masks names and other details inside the text with asterisks before publishing. Keep them; do not try to fill them back in.

Each complaint has a thread of replies, typed `business` or `consumer`:

```json
{"type": "Service or Repair Issues", "status": "Resolved", "id": "0875_23004916_25286018",
 "date": {"day": "16", "month": "09", "year": "2026"},
 "text": "I had a move scheduled for midday on Wednesday September 9th. ...",
 "responses": [{"type": "consumer", "date": {"day": "26", "month": "09", "year": "2026"},
                "text": "I have reached a resolution with all my sons and received proper compensation. ..."}]}
```

The client keeps the reply count, the number of business replies and who wrote last.

## Is there a BBB reviews API route, and how do customer reviews come back?

The `/customer-reviews` page, ten reviews a page, sorted `reviewDate desc, id desc`:

```
$ python examples/bbb_client.py reviews <profile url> --pages 2 --csv reviews.csv
{"numFound": 2672, "pageSize": 10, "totalPages": 268, "sort": "reviewDate desc, id desc"}
  2026-10-26 4* Callie C   Once the movers arrived, everything was great! It took just
  2026-10-26 5* Bridget B  I had a great experience with ************ My movers arrive
  2026-10-24 5* Jason J    ***** ******* and ****** arrived on time and wasted no time
20 reviews read, 20 credits
```

The pager reports 268 pages for that business; we read pages 1 and 2, and the full history would be 2,680 credits. Each item has the star rating, the reviewer's first name and initial, the date, the text and `businessResponseText` when the company replied:

```json
{"reviewStarRating": 5, "displayName": "Lee C", "id": "0875_23004916_4699228",
 "date": {"day": "22", "month": "10", "year": "2026"},
 "text": "The 2 movers that showed up were very prompt very thorough and very efficient ...",
 "businessResponseText": null, "hasExtendedText": false, ...}
```

## Can I compare several businesses in one run?

[`examples/bbb_compare.py`](examples/bbb_compare.py) reads page 1 of complaints (which includes the whole profile) and page 1 of reviews for each business, 20 credits each:

```
$ python examples/bbb_compare.py --urls <all my sons> <two men and a truck, mesa> <two men and a truck, phoenix west valley>
  All My Sons Moving & Storage   A+  complaints  1575 resolved 16%  stars 3.61 (recent 4.5)
  Two Men And A Truck            A+  complaints     0 resolved %  stars 3 (recent 3.0)
  Two Men and a Truck Phoenix-We NR  complaints     0 resolved %  stars 1 (recent 1.0)
3 businesses, 60 credits, wrote bbb_compare.csv
```

`resolved` is resolved over answered plus resolved, from the status filter counts. `recent` is the mean of the last ten reviews. For All My Sons the last ten averaged 4.5 against a lifetime 3.61, which is the kind of gap that column exists to show.

## What about Node.js?

[`examples/bbb_search.js`](examples/bbb_search.js) writes search results as CSV, deduped the same way, with Node 18's built in `fetch`:

```
$ node examples/bbb_search.js "roofing" "Austin, TX" 2 > roofers.csv
page 1: 1 credit(s)
6458 results, 15 pages served
page 2: 1 credit(s)
29 unique businesses
```

## Does BBB have its own API, and why scrape instead?

It does. BBB runs a developer program at `developer.bbb.org`. Its page says access requires approval, each request is vetted, and complaint and review data obtained through it is for internal use only and may not be displayed publicly. If that program fits your use, apply there.

This repo is for the other case: reading what any visitor sees on bbb.org, for a handful of businesses or for monitoring, without an approval step. The same caution about republishing applies. Complaint and review text belongs to the people who wrote it, and names, even partly masked, are personal data.

## What is off limits?

Anything behind a login: business accounts, filing or answering a complaint, leaving a review, the "Email this business" form. ScrapingBee's terms rule out scraping under login credentials, and none of the code here signs in or submits a form. It only issues GET requests for public pages.

## What does a typical job cost?

| Job | Credits |
|---|---|
| One search page (15 businesses) | 1 |
| Every reachable page of one search (225 businesses) | 15 |
| One profile | 10 |
| Ten complaints or ten reviews | 10 |
| Compare three businesses | 60 |
| Every review of a business with 2,672 reviews | 2,680 |

New accounts get 1,000 free credits. Plans: [pricing](https://www.scrapingbee.com/pricing/). Parameters used here: [HTML API documentation](https://www.scrapingbee.com/documentation/), [data extraction rules](https://www.scrapingbee.com/documentation/data-extraction/) if you prefer CSS selectors to the state object, [JavaScript scenarios](https://www.scrapingbee.com/documentation/js-scenario/).

Other review and directory endpoints: [Yellow Pages scraper API](https://www.scrapingbee.com/scrapers/yellow-pages-scraper-api/), [Google reviews API](https://www.scrapingbee.com/scrapers/google-reviews-results-api/), [review API](https://www.scrapingbee.com/scrapers/review-api/), [G2 API](https://www.scrapingbee.com/scrapers/g2-api/), [Capterra API](https://www.scrapingbee.com/scrapers/capterra-api/), [Tripadvisor API](https://www.scrapingbee.com/scrapers/tripadvisor-api/), [Houzz API](https://www.scrapingbee.com/scrapers/houzz-api/).

## FAQ: what else do developers ask?

**Is there a free BBB API?**
Not an open one. BBB's developer program needs approval. Reading public bbb.org pages through ScrapingBee costs 1 credit per search page and 10 per profile, complaints or reviews page, and new accounts start with 1,000 free credits.

**How do I get BBB reviews for a business as CSV?**
`python examples/bbb_client.py reviews <profile url> --pages 5 --csv reviews.csv` gives you the newest 50. Raise `--pages` up to `totalPages` for all of them.

**Can I get the BBB rating for a list of companies?**
Search each name with its city (1 credit) and read `rating` and `bbbMember` from the hit. Open the profile (10 credits) only when you need the grade reasons, dates or complaint counts.

**Why does my BBB scraper get a 403?**
Profile pages refused a plain request in our test. Use `premium_proxy=true`. The 403 reaches you as a ScrapingBee 500, which is not billed.

**Does this work for Canadian businesses?**
The state object and URL pattern were only checked on US profiles (`/us/...`). BBB also lists Canadian businesses, but nothing here was tested against them.

## License

MIT. See [LICENSE](LICENSE).
