"""
Vector database (ChromaDB).

- Jobs scrape hone ke baad yahan store hote hain — title/company/skills/desc ka
  embedding ban jaata hai (local, free — koi API token nahi).
- Search = semantic (meaning se match, sirf keyword se nahi).
- Resume match = resume ka embedding banao, sabse "nazdeek" jobs uthao.
"""
import chromadb


class VectorDB:
    def __init__(self, path="./chroma_db"):
        self.client = chromadb.PersistentClient(path=path)
        # cosine space -> distance 0..2 -> match% nikaalna aasan
        self.col = self.client.get_or_create_collection(
            "jobs", metadata={"hnsw:space": "cosine"})

    def count(self):
        return self.col.count()

    def upsert(self, jobs):
        seen, ids, docs, metas = set(), [], [], []
        for j in jobs:
            if not j.get("title") or not j.get("_text") or j["id"] in seen:
                continue
            seen.add(j["id"])
            ids.append(j["id"])
            docs.append(j["_text"])
            metas.append({
                "title": j["title"], "company": j["company"],
                "location": j["location"], "remote": j["remote"],
                "job_type": j["job_type"], "source": j["source"],
                "url": j["url"], "date": j["date"],
                "tags": ", ".join(j["tags"]), "desc": j["desc"][:400],
                "salary_min": j.get("salary_min", 0), "salary_max": j.get("salary_max", 0),
            })
        for i in range(0, len(ids), 200):                 # batch upsert
            self.col.upsert(ids=ids[i:i + 200], documents=docs[i:i + 200],
                            metadatas=metas[i:i + 200])
        return len(ids)

    def _row(self, jid, meta, dist=None):
        r = dict(meta)
        r["id"] = jid                              # stable id -> save/bookmark ke liye
        r["tags"] = [t for t in (meta.get("tags", "") or "").split(", ") if t]
        if dist is not None:
            r["match"] = max(0, min(100, round((1 - dist) * 100)))
        return r

    def search(self, query, n=250):
        total = self.count()
        if total == 0:
            return []
        if query and query.strip():
            res = self.col.query(query_texts=[query], n_results=min(n, total))
            ids = res.get("ids", [[]])[0]
            metas = res.get("metadatas", [[]])[0]
            dists = res.get("distances", [[]])[0]
            return [self._row(i, m, d) for i, m, d in zip(ids, metas, dists)]
        res = self.col.get(limit=n)
        return [self._row(i, m) for i, m in
                zip(res.get("ids", []), res.get("metadatas", []))]

    def all_jobs(self, limit=6000):
        total = self.count()
        if total == 0:
            return []
        res = self.col.get(limit=min(limit, total))
        return [self._row(i, m) for i, m in
                zip(res.get("ids", []), res.get("metadatas", []))]

    def clear(self):
        """Saari jobs delete kar do (collection dobara khaali bana do). Count return."""
        n = self.count()
        try:
            self.client.delete_collection("jobs")
        except Exception:
            pass
        self.col = self.client.get_or_create_collection(
            "jobs", metadata={"hnsw:space": "cosine"})
        return n
