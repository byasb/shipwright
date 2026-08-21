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
