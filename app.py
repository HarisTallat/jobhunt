"""
JobHunt — ek MONOLITHIC app. Ek hi server API bhi deta hai aur UI bhi.
(Koi alag frontend/backend service nahi.)

Run:
    pip install -r requirements.txt
    python app.py                 # ya: uvicorn app:app --reload
    kholo -> http://localhost:8000

Flow: ~30 techniques se jobs -> vector DB (ChromaDB) -> semantic search + resume match.
Sab local + free, koi paid token nahi.
"""
import io
import os
import re
import threading
from collections import Counter
from datetime import datetime

import uvicorn
from fastapi import Body, Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pypdf import PdfReader

import db_users
from techniques import (REGISTRY, default_techniques, live_techniques,
                        run_selected, set_context)
from vectordb import VectorDB

app = FastAPI(title="JobHunt")
db = VectorDB()
db_users.init()
db_users.ensure_default()          # default account: demo@jobhunt.local / demo123
INDEX = os.path.join(os.path.dirname(__file__), "index.html")


def current_user(authorization: str = Header(default="")):
    token = authorization.replace("Bearer ", "").strip()
    u = db_users.user_for_token(token)
    if not u:
        raise HTTPException(status_code=401, detail="Login required")
    return u


# Admin password -> destructive actions (clear DB) ise ke bina nahi chalte.
# Badalne ke liye:  export ADMIN_PASSWORD=yourpass   (default: admin123)
ADMIN_PW = os.getenv("ADMIN_PASSWORD", "admin123")


def _check_admin(pw):
    if (pw or "") != ADMIN_PW:
        raise HTTPException(status_code=403, detail="Wrong admin password")


def _do_refresh(keys, query=""):
    jobs = run_selected(keys, query)
    added = db.upsert(jobs)
    return {"fetched": len(jobs), "added": added, "stored_total": db.count()}


SENIORITY_MATCH = [("intern", "Intern"), ("principal", "Principal"), ("staff", "Staff"),
                   ("lead", "Lead"), ("senior", "Senior"), ("junior", "Junior"),
                   ("director", "Director"), ("head ", "Head")]

SPEC_KW = {
    "AI / ML": ["machine learning", "deep learning", " ml ", " ml,", " ai ", " ai,",
                "artificial intelligence", "nlp", "llm", "ml engineer", "data scientist", "pytorch", "tensorflow"],
    "Backend": ["backend", "back-end", "back end", " api ", "server-side", "django",
                "fastapi", "node.js", "nodejs", "spring", "rails", "microservice", "golang"],
    "Frontend": ["frontend", "front-end", "front end", "react", "vue", "angular",
                 "svelte", "next.js", " ui ", " ui/", "css", "web developer"],
    "Full Stack": ["full stack", "full-stack", "fullstack"],
    "DevOps / Cloud": ["devops", " sre", "site reliability", "kubernetes", "docker",
                       "terraform", "aws", "gcp", "azure", "platform engineer", "infrastructure"],
    "Mobile": ["mobile", " ios", "android", "flutter", "react native", "swift", "kotlin"],
    "Data": ["data engineer", "data analyst", "analytics", " etl", " sql", "big data", "warehouse"],
    "QA / Test": ["quality assurance", "sdet", "automation engineer", " qa "],
    "Security": ["security engineer", "infosec", "cybersecurity", "appsec"],
}


def _job_seniority(title):
    t = (title or "").lower()
    for kw, lab in SENIORITY_MATCH:
        if kw in t:
            return lab
    return "Mid-level"


def _sal(r):
    v = (r.get("salary_max") or 0) or (r.get("salary_min") or 0)
    return v if 10000 <= v <= 1000000 else 0   # sane range -> mis-parsed outliers ignore


def _sort_rows(rows, sort):
    if sort == "newest":
        return sorted(rows, key=lambda r: r.get("date", ""), reverse=True)
    if sort == "salary":
        return sorted(rows, key=_sal, reverse=True)
    if sort == "match":
        return sorted(rows, key=lambda r: r.get("match", 0), reverse=True)
    return rows


def _filter(rows, location="", remote=0, jobtypes="", sources="", mode="",
            seniority="", spec="", posted=0, min_salary=0):
    loc = (location or "").lower().strip()
    jts = [t for t in (jobtypes or "").split(",") if t]
    srcs = [s.lower() for s in (sources or "").split(",") if s]
    mode = (mode or "").lower().strip()
    posted = int(posted or 0)
    min_salary = float(min_salary or 0)
    spec_kws = SPEC_KW.get(spec, []) if spec else []
    today = datetime.now().date()
    out = []
    for r in rows:
        hay = (r.get("location", "") + " " + r.get("title", "")).lower()
        if loc and loc not in hay:
            continue
        if int(remote or 0) and not r.get("remote"):
            continue
        if mode:
            wtext = (r.get("location", "") + " " + r.get("title", "") + " " + r.get("desc", "")).lower()
            is_hybrid = "hybrid" in wtext
            if mode == "hybrid" and not is_hybrid:
                continue
            if mode == "remote" and (is_hybrid or not r.get("remote")):
                continue
            if mode == "onsite" and (is_hybrid or r.get("remote")):
                continue
        blob = " ".join([r.get("job_type", ""), " ".join(r.get("tags", [])),
                         r.get("title", ""), r.get("desc", "")]).lower()
        if jts and not any(t.lower() in blob for t in jts):
            continue
        if srcs and not any(s in r.get("source", "").lower() for s in srcs):
            continue
        if seniority and _job_seniority(r.get("title", "")) != seniority:
            continue
        if spec_kws:
            st = " " + (r.get("title", "") + " " + " ".join(r.get("tags") or [])).lower() + " "
            if not any(kw in st for kw in spec_kws):
                continue
        if posted:
            d = (r.get("date") or "").strip()[:10]
            recent = False
            if re.match(r"^\d{4}-\d{2}-\d{2}$", d):
                try:
                    recent = (today - datetime.strptime(d, "%Y-%m-%d").date()).days <= posted
                except Exception:
                    recent = False
            if not recent:
                continue
        if min_salary and _sal(r) < min_salary:
            continue
        out.append(r)
    return out


# ------------------------------- API -----------------------------------------

@app.get("/api/techniques")
def techniques():
    return [t.info() for t in REGISTRY]


@app.get("/api/stats")
def stats():
    return {"total_jobs": db.count(), "techniques": len(REGISTRY),
            "live": len(live_techniques())}


@app.get("/api/analytics")
def analytics():
    rows = db.all_jobs()
    total = len(rows)
    remote = onsite = hybrid = 0
    for r in rows:
        wtext = (r.get("location", "") + " " + r.get("title", "") + " " + r.get("desc", "")).lower()
        if "hybrid" in wtext:
            hybrid += 1
        elif r.get("remote"):
            remote += 1
        else:
            onsite += 1
    src = Counter(r.get("source", "?") for r in rows)
    tags = Counter()
    for r in rows:
        for t in (r.get("tags") or []):
            t = (t or "").strip().lower()
            if len(t) > 1:
                tags[t] += 1
    locs = Counter()
    for r in rows:
        loc = (r.get("location") or "").strip()
        if loc and loc.lower() != "n/a":
            locs[loc[:26]] += 1
    comps = Counter(r["company"].strip() for r in rows if r.get("company", "").strip())

    seniority, roles, jtypes, by_day, fresh7 = Counter(), Counter(), Counter(), Counter(), 0
    recency, loc_remote, salaries = Counter(), Counter(), []
    today = datetime.now().date()
    SEN = [("intern", "Intern"), ("principal", "Principal"), ("staff", "Staff"),
           ("lead", "Lead"), ("senior", "Senior"), ("junior", "Junior"),
           ("director", "Director"), ("head ", "Head")]
    ROL = [("engineer", "Engineer"), ("developer", "Developer"), ("designer", "Designer"),
           ("scientist", "Data / ML"), ("data ", "Data / ML"), ("analyst", "Analyst"),
           ("devops", "DevOps"), ("architect", "Architect"), ("product", "Product"),
           ("manager", "Manager"), ("marketing", "Marketing"), ("sales", "Sales")]
    for r in rows:
        t = (r.get("title") or "").lower()
        for kw, lab in SEN:
            if kw in t:
                seniority[lab] += 1
                break
        else:
            seniority["Mid-level"] += 1
        for kw, lab in ROL:
            if kw in t:
                roles[lab] += 1
                break
        jt = (r.get("job_type") or "").lower()
        if "intern" in jt or "intern" in t:
            jtypes["Internship"] += 1
        elif "contract" in jt or "contract" in t:
            jtypes["Contract"] += 1
        elif "part" in jt:
            jtypes["Part-time"] += 1
        else:
            jtypes["Full-time"] += 1
        d = (r.get("date") or "").strip()[:10]
        if re.match(r"^\d{4}-\d{2}-\d{2}$", d):
            by_day[d] += 1
            try:
                days = (today - datetime.strptime(d, "%Y-%m-%d").date()).days
                if days <= 0:
                    recency["Today"] += 1
                elif days <= 7:
                    recency["2-7 days"] += 1
                elif days <= 30:
                    recency["8-30 days"] += 1
                else:
                    recency["30+ days"] += 1
                if 0 <= days <= 7:
                    fresh7 += 1
            except Exception:
                pass
        lc = (r.get("location") or "").strip()[:26]
        if lc and lc.lower() != "n/a" and r.get("remote"):
            loc_remote[lc] += 1
        smn, smx = r.get("salary_min") or 0, r.get("salary_max") or 0
        smid = (smn + smx) / 2 if smn and smx else (smx or smn)
        if 10000 <= smid <= 1000000:            # sane range -> outliers/mis-parse drop
            salaries.append((smn, smx))

    combos = Counter()
    for r in rows:
        tg = sorted(set((x or "").strip().lower() for x in (r.get("tags") or [])
                        if x and len(str(x).strip()) > 1))[:6]
        for i in range(len(tg)):
            for j in range(i + 1, len(tg)):
                combos[tg[i] + " + " + tg[j]] += 1

    # Kaunsa software-engineer specialization sabse zyada demand mein hai
    SPECS = [
        ("AI / ML", ["machine learning", "deep learning", " ml ", " ml,", " ai ", " ai,",
                     "artificial intelligence", "nlp", "llm", "ml engineer", "data scientist", "pytorch", "tensorflow"]),
        ("Backend", ["backend", "back-end", "back end", " api ", "server-side", "django",
                     "fastapi", "node.js", "nodejs", "spring", "rails", "microservice", "golang"]),
        ("Frontend", ["frontend", "front-end", "front end", "react", "vue", "angular",
                      "svelte", "next.js", " ui ", " ui/", "css", "web developer"]),
        ("Full Stack", ["full stack", "full-stack", "fullstack"]),
        ("DevOps / Cloud", ["devops", " sre", "site reliability", "kubernetes", "docker",
                            "terraform", "aws", "gcp", "azure", "platform engineer", "infrastructure"]),
        ("Mobile", ["mobile", " ios", "android", "flutter", "react native", "swift", "kotlin"]),
        ("Data", ["data engineer", "data analyst", "analytics", " etl", " sql", "big data", "warehouse"]),
        ("QA / Test", ["quality assurance", "sdet", "automation engineer", " qa "]),
        ("Security", ["security engineer", "infosec", "cybersecurity", "appsec"]),
    ]
    tech = Counter()
    for r in rows:
        blob = " " + (r.get("title", "") + " " + " ".join(r.get("tags") or []) +
                      " " + r.get("desc", "")).lower() + " "
        for spec, kws in SPECS:
            if any(kw in blob for kw in kws):
                tech[spec] += 1

    def _mid(mn, mx):
        return (mn + mx) / 2 if mn and mx else (mx or mn)
    sal_ranges = Counter()
    for mn, mx in salaries:
        v = _mid(mn, mx)
        b = ("<$50k" if v < 50000 else "$50-100k" if v < 100000 else "$100-150k"
             if v < 150000 else "$150-200k" if v < 200000 else "$200k+")
        sal_ranges[b] += 1
    sr_order = ["<$50k", "$50-100k", "$100-150k", "$150-200k", "$200k+"]
    mids = sorted(_mid(mn, mx) for mn, mx in salaries)
    median_salary = round(mids[len(mids) // 2]) if mids else 0

    return {
        "total": total, "remote": remote, "onsite": onsite, "hybrid": hybrid,
        "companies": len(comps), "locations": len(locs), "source_count": len(src),
        "fresh7": fresh7,
        "sources": src.most_common(8),
        "top_tags": tags.most_common(12),
        "top_locations": locs.most_common(8),
        "top_companies": comps.most_common(8),
        "seniority": seniority.most_common(),
        "roles": roles.most_common(8),
        "tech_demand": tech.most_common(),
        "job_types": [[k, jtypes[k]] for k in ["Full-time", "Contract", "Part-time", "Internship"] if jtypes[k]],
        "over_time": sorted(by_day.items())[-12:],
        "recency": [[k, recency[k]] for k in ["Today", "2-7 days", "8-30 days", "30+ days"] if recency[k]],
        "skill_combos": combos.most_common(10),
        "remote_by_loc": [[l, loc_remote.get(l, 0), c] for l, c in locs.most_common(6)],
        "salary_count": len(salaries),
        "avg_salary": median_salary,
        "salary_ranges": [[k, sal_ranges[k]] for k in sr_order if sal_ranges[k]],
    }


@app.post("/api/refresh")
def refresh(payload: dict = Body(default={})):
    set_context(location=payload.get("location", ""))
    keys = payload.get("techniques") or [t.key for t in default_techniques()]
    return _do_refresh(keys, payload.get("q", ""))


@app.get("/api/search")
def search(q: str = "", location: str = "", remote: str = "", jobtypes: str = "",
           sources: str = "", mode: str = "", seniority: str = "", spec: str = "",
           posted: int = 0, min_salary: float = 0, sort: str = "", limit: int = 60):
    rows = _filter(db.search(q, 5000), location, remote, jobtypes, sources, mode,
                   seniority, spec, posted, min_salary)
    return _sort_rows(rows, sort)[:limit]


@app.post("/api/match")
def match(payload: dict = Body(...)):
    rows = db.search(payload.get("resume", ""), 600)
    rows = _filter(rows, payload.get("location", ""), payload.get("remote", 0),
                   payload.get("jobtypes", ""), payload.get("sources", ""),
                   payload.get("mode", ""), payload.get("seniority", ""), payload.get("spec", ""),
                   payload.get("posted", 0), payload.get("min_salary", 0))
    rows = _sort_rows(rows, payload.get("sort", ""))
    return rows[:int(payload.get("limit", 60))]


# ------------------------------- AUTH ----------------------------------------

@app.post("/api/auth/signup")
def signup(payload: dict = Body(...)):
    try:
        token, email = db_users.signup(payload.get("email", ""), payload.get("password", ""))
        return {"token": token, "email": email}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/auth/login")
def login(payload: dict = Body(...)):
    try:
        token, email = db_users.login(payload.get("email", ""), payload.get("password", ""))
        return {"token": token, "email": email}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/auth/me")
def me(user: dict = Depends(current_user)):
    return {"email": user["email"]}


@app.post("/api/auth/logout")
def logout(authorization: str = Header(default="")):
    db_users.logout(authorization.replace("Bearer ", "").strip())
    return {"ok": True}


# ------------------------------- SAVED JOBS (login) --------------------------

@app.get("/api/saved")
def saved_list(user: dict = Depends(current_user)):
    return db_users.list_saved(user["id"])


@app.post("/api/saved")
def saved_add(payload: dict = Body(...), user: dict = Depends(current_user)):
    db_users.save_job(user["id"], payload.get("job") or payload)
    return {"ok": True, "count": len(db_users.list_saved(user["id"]))}


@app.delete("/api/saved/{job_id}")
def saved_del(job_id: str, user: dict = Depends(current_user)):
    db_users.unsave_job(user["id"], job_id)
    return {"ok": True}


# ------------------------------- ADMIN (password) ----------------------------

@app.post("/api/admin/verify")
def admin_verify(payload: dict = Body(...), user: dict = Depends(current_user)):
    return {"ok": (payload.get("password", "") == ADMIN_PW)}


@app.post("/api/admin/clear")
def admin_clear(payload: dict = Body(...), user: dict = Depends(current_user)):
    _check_admin(payload.get("password", ""))
    reason = (payload.get("reason", "") or "no reason").strip()
    n = db.clear()
    print(f"[ADMIN] {user['email']} cleared {n} jobs. Reason: {reason}")
    return {"cleared": n, "total": db.count(), "reason": reason}


@app.post("/api/admin/rebuild")
def admin_rebuild(payload: dict = Body(...), user: dict = Depends(current_user)):
    _check_admin(payload.get("password", ""))
    reason = (payload.get("reason", "") or "rebuild").strip()
    cleared = db.clear()
    print(f"[ADMIN] {user['email']} rebuild: cleared {cleared}. Reason: {reason}")
    res = _do_refresh([t.key for t in default_techniques()], payload.get("q", ""))
    return {"cleared": cleared, **res}


# ------------------------------- RESUME (ATS score) --------------------------

def _pdf_text(data):
    reader = PdfReader(io.BytesIO(data))
    return "\n".join((p.extract_text() or "") for p in reader.pages)


@app.post("/api/resume/upload")
async def resume_upload(file: UploadFile = File(...), user: dict = Depends(current_user)):
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Please upload a PDF file")
    data = await file.read()
    try:
        text = _pdf_text(data)
    except Exception:
        raise HTTPException(status_code=400, detail="Could not read the PDF")
    if len(text.strip()) < 20:
        raise HTTPException(status_code=400, detail="No text found in the PDF (is it a scanned image?)")
    db_users.set_resume(user["id"], text, file.filename)
    jobs = db.search(text, 600)[:80]     # ATS score = semantic match %
    return {"filename": file.filename, "chars": len(text), "preview": text[:260], "jobs": jobs}


@app.get("/api/resume")
def resume_get(user: dict = Depends(current_user)):
    text, fname = db_users.get_resume(user["id"])
    return {"has": bool(text), "filename": fname, "chars": len(text or ""), "preview": (text or "")[:260]}


@app.get("/api/resume/match")
def resume_match(limit: int = 80, user: dict = Depends(current_user)):
    text, _ = db_users.get_resume(user["id"])
    return db.search(text, 600)[:limit] if text else []


@app.get("/api/resume/insights")
def resume_insights(user: dict = Depends(current_user)):
    text, _ = db_users.get_resume(user["id"])
    if not text:
        return {"has": False}
    rtokens = set(re.findall(r"[a-z0-9+#.]+", text.lower()))
    rows = db.all_jobs()
    tags = Counter()
    for r in rows:
        for tg in (r.get("tags") or []):
            tg = (tg or "").strip().lower()
            if len(tg) > 1:
                tags[tg] += 1
    gap = [[t, n] for t, n in tags.most_common(45)
           if not any(w in rtokens for w in t.split())][:10]
    ranked = db.search(text, 600)
    dist, comp = Counter(), Counter()
    for j in ranked:
        m = j.get("match", 0)
        b = ("80-100%" if m >= 80 else "60-79%" if m >= 60 else
             "40-59%" if m >= 40 else "20-39%" if m >= 20 else "0-19%")
        dist[b] += 1
        if m >= 50 and j.get("company"):
            comp[j["company"]] += 1
    order = ["80-100%", "60-79%", "40-59%", "20-39%", "0-19%"]
    return {
        "has": True,
        "skill_gap": gap,
        "ats_distribution": [[k, dist[k]] for k in order if dist[k]],
        "best_companies": comp.most_common(8),
        "strong": dist["80-100%"] + dist["60-79%"],
    }


# ------------------------------- UI (same server) ----------------------------

@app.get("/")
def index():
    # no-store -> browser hamesha fresh HTML/JS le (purana cache na atke)
    return FileResponse(INDEX, headers={"Cache-Control": "no-store, max-age=0"})


@app.on_event("startup")
def _warmup():
    # DB khaali ho to background mein pehli baar jobs bhar do.
    if db.count() == 0:
        threading.Thread(
            target=lambda: _do_refresh([t.key for t in default_techniques()]),
            daemon=True).start()


if __name__ == "__main__":
    print("JobHunt -> http://localhost:8000")
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=False)
