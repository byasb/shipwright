from shipwright.validators import validate


def test_good_metadata_passes():
    v = validate({
        "name": "SnipStash: Clipboard Manager",
        "subtitle": "Snippets, Paste & Text Vault",
        "keywords": "copy,history,shortcut,note,code,link,widget,share,template,quick,save,organize,tag,search,pin,url",
        "description": "Keep everything you copy. Pay once.",
    })
    assert v.ok, v.problems


def test_catches_every_rule():
    v = validate({
        "name": "Best Clipboard App Ever Made For Everyone",  # >30, 'app', 'best'
        "subtitle": "Clipboard & Snippets",  # repeats 'clipboard', short fill
        "keywords": "clipboard, snippets,paste,apple,copy,copies",  # space, brand, plural, repeat
        "description": "Only $4.99!",
    })
    joined = " ".join(v.problems)
    assert not v.ok
    for needle in ["limit 30", "repeated across name and subtitle", "NO spaces",
                   "brand words", "plural", "hardcoded price", "'app'"]:
        assert needle in joined, f"missing: {needle}\n{joined}"


def test_notify_report_and_graceful_skip(monkeypatch):
    # ponytail: one check that fails if the report or the no-config path breaks
    from shipwright import notify
    job = {"id": "j1", "app_id": "6803901837", "build_id": "b", "dry_run": True, "state": "prepared",
           "stages": {"preflight": {"status": "done", "output": {"verdict": "PASS", "report": "ok"}},
                      "submit": {"status": "done", "output": {"submitted": False, "reason": "withheld"}}}}
    body = notify._report(job)
    assert "PASS" in body and "withheld" in body and "6803901837" in body
    for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASS", "NOTIFY_EMAIL"):
        monkeypatch.delenv(k, raising=False)
    assert notify.job_complete(job) is False


def test_replay_store_and_asc(tmp_path):
    # ponytail: one check across the replay seam — dotted updates, ArrayUnion, fixture lookup, redaction
    import json
    from google.cloud import firestore
    from shipwright import replay

    db = replay.MemoryFirestore()
    doc = db.collection("jobs").document("j1")
    doc.set({"stages": {"intake": {"status": "pending"}}})
    doc.update({"stages.intake.status": "done", "events": firestore.ArrayUnion([{"msg": "a"}])})
    doc.update({"events": firestore.ArrayUnion([{"msg": "b"}])})
    d = doc.get().to_dict()
    assert d["stages"]["intake"]["status"] == "done" and [e["msg"] for e in d["events"]] == ["a", "b"]

    fx = tmp_path / "f.json"
    fx.write_text(json.dumps({"app_facts": {"name": "X"}, "build_id": "b1", "gets": {
        "GET /v1/apps/1?limit=10": {"data": [{"id": "44a53643-1738-43ea-ac1d-f5ea877519de"}]}}}))
    asc = replay.ReplayASC(fx)
    assert asc.build_id == "b1"
    assert asc.get("/v1/apps/1", limit=10)["data"][0]["id"].startswith("44a53643")  # UUID survives
    assert asc.get("/v1/apps/1")["data"]  # bare-path fallback
    w = asc.post("/x", {"a": 1}, app_id="6803901837")
    assert w["dry_run"] is True

    red = replay._redact({"contactPhone": "+91 98765", "id": "44a53643-1738", "nested": [{"contactEmail": "a@b.c"}]})
    assert red["contactPhone"] == "[redacted]" and red["id"] == "44a53643-1738" and red["nested"][0]["contactEmail"] == "[redacted]"
