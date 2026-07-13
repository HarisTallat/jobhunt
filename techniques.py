"""
~30 job-finding techniques as plug-ins.

Har technique ek chhota function hai jo query leta hai aur jobs ki list deta hai.
- live=True  -> abhi free chalti hai (koi API key / token nahi).
- needs_key  -> free key chahiye (jaise Adzuna) -> country-wise search.
- scraper    -> LinkedIn/Indeed etc. (Apify token) -> phase 2.

Naya source add karna = niche ek function + REGISTRY mein ek line. Bas.
"""
import math
import os
import json
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

from models import make_job

UA = {"User-Agent": "JobHunt/2.0"}

# Refresh ke waqt UI se location yahan set hoti hai (JobSpy scrapers use karte hain).
_CTX = {"location": ""}


def set_context(location=""):
    _CTX["location"] = (location or "").strip()


def _clean(v):
    """pandas/JobSpy ke NaN aur None ko saaf string mein badalta hai."""
    if v is None:
        return ""
    try:
        if isinstance(v, float) and math.isnan(v):
            return ""
    except Exception:
        pass
    return str(v)


def _get(url, timeout=15):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _json(url, timeout=15):
    return json.loads(_get(url, timeout))


def _rss(url, source, remote=True, timeout=15):
    root = ET.fromstring(_get(url, timeout))
    out = []
    for it in root.iter("item"):
        def t(tag):
            e = it.find(tag)
            return e.text if e is not None else ""
        title = t("title")
        company = ""
        if ": " in title:                       # "Company: Job title" pattern
            company, _, title = title.partition(": ")
        out.append(make_job(source, title.strip(), company.strip(), "", remote,
                            [c.text for c in it.findall("category")], "",
                            t("link"), t("pubDate"), t("description")))
    return out


# --------------------------- FREE APIs (live) ---------------------------------

def remotive(q):
    url = "https://remotive.com/api/remote-jobs?limit=80"
    if q:
        url += "&search=" + urllib.parse.quote(q)
    return [make_job("Remotive", j.get("title"), j.get("company_name"),
            j.get("candidate_required_location"), True, j.get("tags"),
            j.get("job_type"), j.get("url"), j.get("publication_date"),
            j.get("description")) for j in _json(url).get("jobs", [])]


def arbeitnow(q):
    d = _json("https://www.arbeitnow.com/api/job-board-api")
    return [make_job("Arbeitnow", j.get("title"), j.get("company_name"),
            j.get("location"), j.get("remote"), j.get("tags"),
            ", ".join(j.get("job_types") or []), j.get("url"),
            j.get("created_at"), j.get("description")) for j in d.get("data", [])]


def jobicy(q):
    url = "https://jobicy.com/api/v2/remote-jobs?count=50"
    if q:
        url += "&tag=" + urllib.parse.quote(q)
    return [make_job("Jobicy", j.get("jobTitle"), j.get("companyName"),
            j.get("jobGeo"), True, j.get("jobIndustry"),
            ", ".join(j.get("jobType") or []), j.get("url"), j.get("pubDate"),
            j.get("jobExcerpt")) for j in _json(url).get("jobs", [])]


def muse(q):
    d = _json("https://www.themuse.com/api/public/jobs?page=1")
    out = []
    for j in d.get("results", []):
        locs = ", ".join(l.get("name", "") for l in (j.get("locations") or []))
        cats = [c.get("name", "") for c in (j.get("categories") or [])]
        out.append(make_job("The Muse", j.get("name"),
                            (j.get("company") or {}).get("name"), locs,
                            "remote" in locs.lower(), cats, j.get("type"),
                            (j.get("refs") or {}).get("landing_page"),
                            j.get("publication_date"), j.get("contents")))
    return out


def remoteok(q):
    out = []
    for j in _json("https://remoteok.com/api"):
        if not isinstance(j, dict) or not j.get("position"):
            continue
        out.append(make_job("RemoteOK", j.get("position"), j.get("company"),
                            j.get("location") or "Remote", True, j.get("tags"),
                            "", j.get("url"), j.get("date"), j.get("description")))
    return out


def workingnomads(q):
    d = _json("https://www.workingnomads.com/api/exposed_jobs/")
    rows = d if isinstance(d, list) else d.get("jobs", [])
    return [make_job("Working Nomads", j.get("title"), j.get("company_name"),
            j.get("location") or "Remote", True, (j.get("tags") or "").split(","),
            j.get("category_name"), j.get("url"), j.get("pub_date"),
            j.get("description")) for j in rows][:80]


def himalayas(q):
    d = _json("https://himalayas.app/jobs/api?limit=50")
    out = []
    for j in d.get("jobs", []):
        loc = ", ".join(j.get("locationRestrictions") or []) or "Remote"
        out.append(make_job("Himalayas", j.get("title"), j.get("companyName"),
                            loc, True, j.get("categories"),
                            ", ".join(j.get("employmentType") or []),
                            j.get("applicationLink") or j.get("url"),
                            j.get("pubDate"), j.get("description") or j.get("excerpt")))
    return out


def weworkremotely(q):
    return _rss("https://weworkremotely.com/remote-jobs.rss", "We Work Remotely")


def jobspresso(q):
    return _rss("https://jobspresso.co/remote-work/feed/", "Jobspresso")


def hn_whoishiring(q):
    s = _json("https://hn.algolia.com/api/v1/search_by_date?query=%22Ask%20HN:"
              "%20Who%20is%20hiring%22&tags=story&hitsPerPage=1")
    hits = s.get("hits", [])
    if not hits:
        return []
    item = _json("https://hn.algolia.com/api/v1/items/%s" % hits[0]["objectID"])
    out = []
    for c in (item.get("children") or [])[:80]:
        txt = c.get("text") or ""
        if not txt:
            continue
        from models import clean_html
        clean = clean_html(txt)
        title = clean.split("|")[0][:110].strip()
        out.append(make_job("HN Who's Hiring", title, "",
                            "Remote" if "remote" in clean.lower() else "",
                            "remote" in clean.lower(), [], "",
                            "https://news.ycombinator.com/item?id=%s" % c.get("id"),
                            c.get("created_at"), clean))
    return out


def reddit_forhire(q):
    d = _json("https://www.reddit.com/r/forhire/new.json?limit=70")
    out = []
    for c in d.get("data", {}).get("children", []):
        p = c["data"]
        title = p.get("title", "")
        if "[hiring]" not in title.lower():
            continue
        clean = title.replace("[Hiring]", "").replace("[HIRING]", "").strip()
        out.append(make_job("Reddit r/forhire", clean, "", "",
                            "remote" in title.lower(), [], "",
                            "https://reddit.com" + p.get("permalink", ""),
                            p.get("created_utc"), p.get("selftext", "")))
    return out


# --------------------------- ATS DIRECT (live, no key) ------------------------
# Company careers pages ka clean JSON. Seed handles diye hain; aur add kar sakte ho.

GREENHOUSE = ["stripe", "airbnb", "gitlab", "databricks", "figma", "discord",
              "robinhood", "coinbase", "brex", "instacart", "doordash", "samsara"]
LEVER = ["leadgenius", "match", "spotify", "nubank"]
ASHBY = ["ramp", "linear", "posthog", "vercel"]
RECRUITEE = ["recruitee"]
SMARTREC = ["smartrecruiters", "bosch"]


def ats_greenhouse(q):
    out = []
    for h in GREENHOUSE:
        try:
            d = _json("https://boards-api.greenhouse.io/v1/boards/%s/jobs" % h, 10)
            for j in d.get("jobs", []):
                loc = (j.get("location") or {}).get("name", "")
                out.append(make_job("Greenhouse", j.get("title"), h.title(), loc,
                                    "remote" in loc.lower(), [], "",
                                    j.get("absolute_url"), j.get("updated_at"), ""))
        except Exception:
            pass
    return out


def ats_lever(q):
    out = []
    for h in LEVER:
        try:
            for j in _json("https://api.lever.co/v0/postings/%s?mode=json" % h, 10):
                cat = j.get("categories") or {}
                out.append(make_job("Lever", j.get("text"), h.title(),
                                    cat.get("location", ""),
                                    "remote" in (cat.get("location", "") or "").lower(),
                                    [cat.get("team", "")], cat.get("commitment", ""),
                                    j.get("hostedUrl"), j.get("createdAt"),
                                    j.get("descriptionPlain")))
        except Exception:
            pass
    return out


def ats_ashby(q):
    out = []
    for h in ASHBY:
        try:
            d = _json("https://api.ashbyhq.com/posting-api/job-board/%s" % h, 10)
            for j in d.get("jobs", []):
                loc = j.get("location", "")
                out.append(make_job("Ashby", j.get("title"), h.title(), loc,
                                    "remote" in loc.lower(), [j.get("department", "")],
                                    j.get("employmentType", ""), j.get("jobUrl"),
                                    j.get("publishedDate"), ""))
        except Exception:
            pass
    return out


def ats_recruitee(q):
    out = []
    for h in RECRUITEE:
        try:
            d = _json("https://%s.recruitee.com/api/offers/" % h, 10)
            for j in d.get("offers", []):
                out.append(make_job("Recruitee", j.get("title"), h.title(),
                                    j.get("location", ""),
                                    "remote" in (j.get("location", "") or "").lower(),
                                    [j.get("department", "")], j.get("employment_type_code", ""),
                                    j.get("careers_url"), j.get("published_at"),
                                    j.get("description")))
        except Exception:
            pass
    return out


def ats_smartrecruiters(q):
    out = []
    for h in SMARTREC:
        try:
            d = _json("https://api.smartrecruiters.com/v1/companies/%s/postings" % h, 10)
            for j in d.get("content", []):
                loc = j.get("location") or {}
                city = ", ".join(x for x in [loc.get("city"), loc.get("country")] if x)
                out.append(make_job("SmartRecruiters", j.get("name"), h.title(), city,
                                    bool(loc.get("remote")), [], "",
                                    "https://jobs.smartrecruiters.com/%s/%s" % (h, j.get("id")),
                                    j.get("releasedDate"), ""))
        except Exception:
            pass
    return out


# --------------------------- NEEDS FREE KEY -----------------------------------

def adzuna(q):
    """Country-wise search (Pakistan, US, UK, +many). Free key -> env mein daalo:
    ADZUNA_APP_ID, ADZUNA_APP_KEY  (https://developer.adzuna.com)."""
    app_id = os.getenv("ADZUNA_APP_ID")
    app_key = os.getenv("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        return []
    country = os.getenv("ADZUNA_COUNTRY", "gb")   # gb, us, in, ... (pk supported)
    url = ("https://api.adzuna.com/v1/api/jobs/%s/search/1?app_id=%s&app_key=%s"
           "&results_per_page=50&what=%s" % (country, app_id, app_key,
                                             urllib.parse.quote(q or "developer")))
    d = _json(url)
    return [make_job("Adzuna", j.get("title"), (j.get("company") or {}).get("display_name"),
            (j.get("location") or {}).get("display_name"), False, [],
            j.get("contract_time", ""), j.get("redirect_url"), j.get("created"),
            j.get("description"), salary_min=j.get("salary_min") or 0,
            salary_max=j.get("salary_max") or 0) for j in d.get("results", [])]


# --------------------------- SCRAPERS via JobSpy ------------------------------
# python-jobspy: LinkedIn/Indeed/Glassdoor/Google/ZipRecruiter/Bayt/Naukri/BDJobs
# ko FREE scrape karta hai (koi Apify token nahi). heavy=True -> thoda slow.
# Location UI se aati hai (_CTX). Pakistan ke liye location="Karachi, Pakistan"
# aur env JOBSPY_COUNTRY=pakistan set karo.

def _jobspy(sites, label, q):
    from jobspy import scrape_jobs                 # lazy import (optional heavy dep)
    loc = _CTX.get("location") or ""
    kw = {"site_name": sites, "search_term": q or "developer",
          "results_wanted": int(os.getenv("JOBSPY_RESULTS", "1000")), "hours_old": 336,
          "description_format": "markdown", "verbose": 0}
    if loc:
        kw["location"] = loc
    if sites == ["google"]:
        kw["google_search_term"] = (q or "developer") + " jobs" + (
            " near " + loc if loc else "")
    country = os.getenv("JOBSPY_COUNTRY", "").strip()
    if country:
        kw["country_indeed"] = country
    df = scrape_jobs(**kw)
    if df is None or len(df) == 0:
        return []
    df.columns = [str(c).lower() for c in df.columns]
    imult = {"yearly": 1, "annual": 1, "year": 1, "monthly": 12, "month": 12,
             "weekly": 52, "week": 52, "daily": 260, "day": 260, "hourly": 2080, "hour": 2080}
    out = []
    for r in df.to_dict("records"):
        loc_val = _clean(r.get("location")) or ", ".join(
            x for x in [_clean(r.get("city")), _clean(r.get("state")),
                        _clean(r.get("country"))] if x)
        remote = str(r.get("is_remote")).lower() in ("true", "1")
        mult = imult.get(str(r.get("interval") or "").lower(), 1)

        def _num(v):
            try:
                f = float(v)
                return f * mult if f == f else 0   # f==f skips NaN
            except Exception:
                return 0
        out.append(make_job(label, _clean(r.get("title")), _clean(r.get("company")),
                            loc_val, remote, [], _clean(r.get("job_type")),
                            _clean(r.get("job_url")), _clean(r.get("date_posted")),
                            _clean(r.get("description")),
                            salary_min=_num(r.get("min_amount")), salary_max=_num(r.get("max_amount"))))
    return out


def jobspy_linkedin(q): return _jobspy(["linkedin"], "LinkedIn", q)
def jobspy_indeed(q): return _jobspy(["indeed"], "Indeed", q)
def jobspy_glassdoor(q): return _jobspy(["glassdoor"], "Glassdoor", q)
def jobspy_ziprecruiter(q): return _jobspy(["zip_recruiter"], "ZipRecruiter", q)
def jobspy_google(q): return _jobspy(["google"], "Google Jobs", q)
def jobspy_bayt(q): return _jobspy(["bayt"], "Bayt", q)
def jobspy_naukri(q): return _jobspy(["naukri"], "Naukri", q)
def jobspy_bdjobs(q): return _jobspy(["bdjobs"], "BDJobs", q)


# --------------------------- REGISTRY -----------------------------------------

class Technique:
    def __init__(self, key, label, category, fn=None, live=True, needs_key=False,
                 heavy=False, note=""):
        self.key, self.label, self.category = key, label, category
        self.fn, self.live, self.needs_key = fn, live, needs_key
        self.heavy, self.note = heavy, note

    def info(self):
        return {"key": self.key, "label": self.label, "category": self.category,
                "live": self.live, "needs_key": self.needs_key,
                "heavy": self.heavy, "note": self.note}


REGISTRY = [
    # Free live APIs / remote boards / community  (16)
    Technique("remotive", "Remotive", "Free API", remotive),
    Technique("arbeitnow", "Arbeitnow", "Free API", arbeitnow),
    Technique("jobicy", "Jobicy", "Remote board", jobicy),
    Technique("muse", "The Muse", "Free API", muse),
    Technique("remoteok", "RemoteOK", "Remote board", remoteok),
    Technique("workingnomads", "Working Nomads", "Remote board", workingnomads),
    Technique("himalayas", "Himalayas", "Remote board", himalayas),
    Technique("weworkremotely", "We Work Remotely", "Remote board", weworkremotely),
    Technique("jobspresso", "Jobspresso", "Remote board", jobspresso),
    Technique("hn", "HN Who's Hiring", "Community", hn_whoishiring),
    Technique("reddit", "Reddit r/forhire", "Community", reddit_forhire),
    Technique("greenhouse", "Greenhouse (ATS)", "ATS direct", ats_greenhouse),
    Technique("lever", "Lever (ATS)", "ATS direct", ats_lever),
    Technique("ashby", "Ashby (ATS)", "ATS direct", ats_ashby),
    Technique("recruitee", "Recruitee (ATS)", "ATS direct", ats_recruitee),
    Technique("smartrecruiters", "SmartRecruiters (ATS)", "ATS direct", ats_smartrecruiters),
    # ATS needing company handles (3)
    Technique("workable", "Workable (ATS)", "ATS direct", live=False,
              note="Add company handles to enable"),
    Technique("personio", "Personio (ATS)", "ATS direct", live=False,
              note="Add company handles to enable"),
    Technique("breezy", "Breezy HR (ATS)", "ATS direct", live=False,
              note="Add company handles to enable"),
    # Free key needed (5)  -> country-wise
    Technique("adzuna", "Adzuna (country-wise)", "Needs API key", adzuna,
              live=False, needs_key=True, note="Free key -> Pakistan/US/UK/India etc."),
    Technique("jooble", "Jooble", "Needs API key", live=False, needs_key=True,
              note="Free key -> 70+ countries"),
    Technique("usajobs", "USAJobs (US gov)", "Needs API key", live=False, needs_key=True,
              note="Free key -> US government jobs"),
    Technique("findwork", "Findwork.dev", "Needs API key", live=False, needs_key=True,
              note="Free token"),
    Technique("careerjet", "Careerjet", "Needs API key", live=False, needs_key=True,
              note="Free affiliate key"),
    # Scrapers via JobSpy (FREE, live) -> heavy = thoda slow (scraping)
    Technique("linkedin", "LinkedIn", "Scraper (JobSpy)", jobspy_linkedin, heavy=True,
              note="Add a location for better results"),
    Technique("indeed", "Indeed", "Scraper (JobSpy)", jobspy_indeed, heavy=True,
              note="Set env JOBSPY_COUNTRY=pakistan/usa…"),
    Technique("glassdoor", "Glassdoor", "Scraper (JobSpy)", jobspy_glassdoor, heavy=True),
    Technique("ziprecruiter", "ZipRecruiter", "Scraper (JobSpy)", jobspy_ziprecruiter, heavy=True),
    Technique("google", "Google Jobs", "Scraper (JobSpy)", jobspy_google, heavy=True),
    Technique("bayt", "Bayt (Gulf/MENA)", "Scraper (JobSpy)", jobspy_bayt, heavy=True),
    Technique("naukri", "Naukri (India)", "Scraper (JobSpy)", jobspy_naukri, heavy=True),
    Technique("bdjobs", "BDJobs (Bangladesh)", "Scraper (JobSpy)", jobspy_bdjobs, heavy=True),
    Technique("rozee", "Rozee.pk (Pakistan)", "Scraper (custom)", live=False,
              note="Not in JobSpy -> custom scraper (phase 2)"),
]

TMAP = {t.key: t for t in REGISTRY}


def live_techniques():
    return [t for t in REGISTRY if t.live and t.fn]


def default_techniques():
    # Auto-refresh / default -> live but heavy (LinkedIn etc.) NAHI. Tez rehta hai.
    return [t for t in REGISTRY if t.live and t.fn and not t.heavy]


def _safe(t, q):
    try:
        return t.fn(q) or []
    except Exception:
        return []


def run_selected(keys, query=""):
    chosen = [TMAP[k] for k in keys if k in TMAP and TMAP[k].live and TMAP[k].fn]
    if not chosen:
        chosen = default_techniques()
    out = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        for res in ex.map(lambda t: _safe(t, query), chosen):
            out.extend(res)
    dedup = {}
    for j in out:
        if j["title"]:
            dedup[j["id"]] = j
    return list(dedup.values())
