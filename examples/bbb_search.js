// BBB search results as CSV on stdout. Node 18+ (global fetch).
//
//   node bbb_search.js "roofing" "Austin, TX" 3 > roofers.csv
//
// 1 credit per results page (plain request, no JavaScript). BBB serves at
// most 15 pages of 15, so the third argument is capped at 15.
// Set SCRAPINGBEE_API_KEY first.

const API = "https://app.scrapingbee.com/api/v1/";
const KEY = process.env.SCRAPINGBEE_API_KEY;
if (!KEY) {
  console.error("Set SCRAPINGBEE_API_KEY first.");
  process.exit(1);
}

function preloadedState(html) {
  const marker = "window.__PRELOADED_STATE__";
  const start = html.indexOf("{", html.indexOf(marker));
  let depth = 0, inStr = false, esc = false;
  for (let i = start; i < html.length; i++) {
    const c = html[i];
    if (inStr) {
      if (esc) esc = false;
      else if (c === "\\") esc = true;
      else if (c === '"') inStr = false;
    } else if (c === '"') inStr = true;
    else if (c === "{") depth++;
    else if (c === "}" && --depth === 0) return JSON.parse(html.slice(start, i + 1));
  }
  throw new Error("__PRELOADED_STATE__ not found");
}

async function searchPage(text, loc, page) {
  const target = "https://www.bbb.org/search?" + new URLSearchParams({
    find_country: "USA", find_text: text, find_loc: loc, page: String(page),
  });
  for (let attempt = 1; attempt <= 3; attempt++) {
    const res = await fetch(API + "?" + new URLSearchParams({ url: target, render_js: "false" }), {
      headers: { Authorization: `Bearer ${KEY}` },
    });
    if (res.status === 200) {
      console.error(`page ${page}: ${res.headers.get("spb-cost")} credit(s)`);
      return preloadedState(await res.text()).searchResult;
    }
    console.error(`page ${page}: HTTP ${res.status}, attempt ${attempt}`);
  }
  throw new Error("search failed");
}

const csvCell = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
const strip = (s) => String(s || "").replace(/<[^>]+>/g, "");

async function main() {
  const [text, loc, pagesArg = "1"] = process.argv.slice(2);
  if (!text || !loc) {
    console.error('usage: node bbb_search.js "<what>" "<City, ST>" [pages]');
    process.exit(2);
  }
  const pages = Math.min(Number(pagesArg), 15);
  const seen = new Set();
  console.log(["name", "rating", "accredited", "category", "city", "state", "phone", "profile_url"].join(","));
  for (let p = 1; p <= pages; p++) {
    const sr = await searchPage(text, loc, p);
    for (const r of sr.results || []) {
      const key = `${r.bbbId}-${r.businessId}`;
      if (seen.has(key)) continue;
      seen.add(key);
      console.log([strip(r.businessName), r.rating, r.bbbMember, r.tobText, r.city, r.state,
        (r.phone || [])[0], "https://www.bbb.org" + r.reportUrl].map(csvCell).join(","));
    }
    if (p === 1) console.error(`${sr.totalResults} results, ${sr.totalPages} pages served`);
    if (p >= sr.totalPages) break;
  }
  console.error(`${seen.size} unique businesses`);
}

main().catch((e) => {
  console.error(e.message);
  process.exit(1);
});
