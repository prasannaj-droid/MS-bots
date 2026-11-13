"""Azure DevOps actions: work items and wiki pages.

Dry-run is the default: nothing leaves the machine; each action is written as
JSON / Markdown under ./dry_run_output so you can see exactly what would be sent.
Live mode needs MUSK_ADO_LIVE=1 and ADO_PAT, and sends real REST calls.
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API_VERSION = "7.1"
VALID_TYPES = {"User Story", "Task", "Bug", "Feature", "Epic", "Issue", "Product Backlog Item"}


class AdoClient:
    def __init__(self, org: str | None = None, project: str | None = None, wiki: str | None = None,
                 pat: str | None = None, live: bool | None = None, out_dir: Path | None = None):
        self.org = org or os.getenv("ADO_ORG", "milestone-devops")
        self.project = project or os.getenv("ADO_PROJECT", "Asgard")
        self.wiki = wiki or os.getenv("ADO_WIKI", f"{self.project}.wiki")
        self.area_path = os.getenv("ADO_AREA_PATH")  # optional
        self.pat = pat or os.getenv("ADO_PAT")
        self.live = live if live is not None else os.getenv("MUSK_ADO_LIVE") == "1"
        if self.live and not self.pat:
            raise RuntimeError("MUSK_ADO_LIVE=1 needs ADO_PAT to be set.")
        self.out_dir = out_dir or Path.cwd() / "dry_run_output"
        self.base = f"https://dev.azure.com/{urllib.parse.quote(self.org)}/{urllib.parse.quote(self.project)}"

    # ---------- work items ----------
    def create_work_items(self, items: list[dict]) -> list[dict]:
        results = []
        for item in items:
            wtype = item.get("type", "User Story")
            if wtype not in VALID_TYPES:
                wtype = "User Story"
            patch = [
                {"op": "add", "path": "/fields/System.Title", "value": item["title"][:255]},
                {"op": "add", "path": "/fields/System.Description", "value": item.get("description", "")},
            ]
            if item.get("tags"):
                patch.append({"op": "add", "path": "/fields/System.Tags", "value": "; ".join(item["tags"])})
            if self.area_path:
                patch.append({"op": "add", "path": "/fields/System.AreaPath", "value": self.area_path})
            if item.get("acceptance_criteria"):
                patch.append({"op": "add", "path": "/fields/Microsoft.VSTS.Common.AcceptanceCriteria",
                              "value": item["acceptance_criteria"]})
            url = f"{self.base}/_apis/wit/workitems/${urllib.parse.quote(wtype)}?api-version={API_VERSION}"
            if self.live:
                resp = self._send("POST", url, patch, "application/json-patch+json")
                results.append({"id": resp.get("id"), "type": wtype, "title": item["title"],
                                "url": resp.get("_links", {}).get("html", {}).get("href", "")})
            else:
                path = self._dry_write("workitem", {"method": "POST", "url": url, "body": patch}, item["title"])
                results.append({"id": None, "type": wtype, "title": item["title"],
                                "dry_run": True, "saved_to": str(path)})
        return results

    # ---------- wiki ----------
    def create_wiki_page(self, path: str, content: str) -> dict:
        path = "/" + path.strip("/")
        url = (f"{self.base}/_apis/wiki/wikis/{urllib.parse.quote(self.wiki)}/pages"
               f"?path={urllib.parse.quote(path)}&api-version={API_VERSION}")
        if self.live:
            # PUT without If-Match creates a new page; it fails if the page exists (no silent overwrite).
            resp = self._send("PUT", url, {"content": content}, "application/json")
            return {"path": path, "url": resp.get("remoteUrl", "")}
        saved = self._dry_write("wiki", {"method": "PUT", "url": url, "body": {"content": content}}, path)
        md = saved.with_suffix(".md")
        md.write_text(content, encoding="utf-8")
        return {"path": path, "dry_run": True, "saved_to": str(md)}

    # ---------- plumbing ----------
    def _send(self, method: str, url: str, body, content_type: str) -> dict:
        token = base64.b64encode(f":{self.pat}".encode()).decode()
        req = urllib.request.Request(url, method=method, data=json.dumps(body).encode(),
                                     headers={"Authorization": f"Basic {token}", "Content-Type": content_type})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"ADO {method} failed ({e.code}): {e.read().decode()[:500]}") from e

    def _dry_write(self, kind: str, payload: dict, label: str) -> Path:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:50] or kind
        path = self.out_dir / f"{int(time.time() * 1000)}-{kind}-{slug}.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path
