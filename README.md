# 🔍 JobHunt — full job search portal (monolith)

Poori internet ki jobs ek jagah. **~30 techniques** se jobs aati hain, ek
**vector DB** mein jati hain, aur tumhare **resume** se "sabse close" jobs upar
aa jati hain. Sab **local + free** — koi paid token nahi.

> **Monolith:** ek hi project, ek hi server (API + UI dono). Koi micro-service,
> koi alag frontend server, koi npm/build nahi.

## Tech
| Layer | Tech |
|---|---|
| Server | Python + **FastAPI** (ek process) |
| Vector DB | **ChromaDB** (local, free embeddings) |
| UI | **React + Material UI** — CDN se, built-in components (koi CSS/build nahi) |
| Sources | ~30 techniques (free APIs, ATS, community, +key/scraper wale) |

## Chalao (ek command)
```bash
cd job-portal
./run.sh
```
…ya haath se:
```bash
pip install -r requirements.txt
python app.py
```
Kholo 👉 **http://localhost:8000**

Pehli baar jobs khud-b-khud background mein aa jati hain. Thoda ruk kar
**Search jobs** dabao (ya **↻ Internet se laao**).

## ~30 techniques
- **Live (free, abhi chalti):** Remotive, Arbeitnow, Jobicy, The Muse, RemoteOK,
  Working Nomads, Himalayas, We Work Remotely, Jobspresso, HN Who's Hiring,
  Reddit r/forhire + ATS: Greenhouse, Lever, Ashby, Recruitee, SmartRecruiters.
- **Free key chahiye (country-wise):** Adzuna (Pakistan/US/UK/India…), Jooble,
  USAJobs, Findwork, Careerjet.
- **Scraper (JobSpy — FREE, live):** LinkedIn, Indeed, Glassdoor, ZipRecruiter,
  Google Jobs, Bayt (Gulf), Naukri (India), BDJobs (Bangladesh). UI mein "scrape"
  badge = thoda slow. Pakistan ke liye location + `JOBSPY_COUNTRY=pakistan`.
  (Rozee.pk custom scraper phase 2.)

### Adzuna (Pakistan/country-wise) on karna
`https://developer.adzuna.com` se free key lo, phir chalane se pehle:
```bash
export ADZUNA_APP_ID=xxxx
export ADZUNA_APP_KEY=xxxx
export ADZUNA_COUNTRY=pk        # pk, us, gb, in ...
```

## Files (sab ek folder — monolith)
```
app.py           FastAPI server (API + UI)
techniques.py    ~30 job-finding techniques (plug-ins)
vectordb.py      ChromaDB wrapper (embeddings + semantic search)
models.py        job ka common shape
index.html       React + MUI UI (ek file)
requirements.txt
```

## Naya source add karna
`techniques.py` mein ek function likho jo `make_job(...)` ki list de, aur
`REGISTRY` mein ek line add karo. Bas — dedupe, embeddings, filters, UI sab
automatic. 🧩
