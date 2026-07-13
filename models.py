"""Common job shape + helpers. Har source ka data yahan ek jaisa ban jaata hai."""
import hashlib
import re


def clean_html(s: str) -> str:
    return re.sub(r"<[^>]+>", " ", s or "").replace("&nbsp;", " ").strip()


def make_job(source, title, company, location, remote, tags, job_type, url, date, desc,
             salary_min=0, salary_max=0):
    title = (title or "").strip()
    company = (company or "").strip()
    jid = hashlib.sha1(f"{source}|{title}|{company}".lower().encode()).hexdigest()[:16]
    tags = [str(t).strip() for t in (tags or []) if t and str(t).strip()][:10]
    desc = clean_html(desc)[:600]
    location = (location or "").strip()
    text = " ".join([title, title, company, location, " ".join(tags), desc]).strip()
    return {
        "id": jid,
        "source": source,
        "title": title,
        "company": company,
        "location": location,
        "remote": bool(remote),
        "tags": tags,
        "job_type": (job_type or "").strip(),
        "url": url or "",
        "date": str(date or "")[:10],
        "desc": desc,
        "salary_min": float(salary_min or 0),
        "salary_max": float(salary_max or 0),
        "_text": text,
    }
