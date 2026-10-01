from leadgen import cleaning


def rec(name, address, phone=None, place_id=None):
    return {"name": name, "address": address, "phone": phone,
            "place_id": place_id, "website": None, "review_count": 0}


# ---------- normalisation ----------

def test_clean_phone_formats():
    assert cleaning.clean_phone("+91 98190 29131") == "+919819029131"
    assert cleaning.clean_phone("098190 29131") == "+919819029131"
    assert cleaning.clean_phone("98190 29131") == "+919819029131"


def test_clean_phone_keeps_toll_free():
    assert cleaning.clean_phone("1800 266 7667") == "+9118002667667"


def test_clean_phone_rejects_junk():
    assert cleaning.clean_phone("12345") is None
    assert cleaning.clean_phone("") is None
    assert cleaning.clean_phone(None) is None


def test_phone_type():
    assert cleaning.phone_type("+919819029131") == "mobile"
    assert cleaning.phone_type("+912226031100") == "landline"
    assert cleaning.phone_type("+9118002667667") == "toll_free"
    assert cleaning.phone_type(None) is None


def test_strip_invisible_removes_zero_width_characters():
    assert cleaning.strip_invisible("Spartan\u200b Cowork") == "Spartan Cowork"
    assert cleaning.strip_invisible(None) is None


def test_display_name_cuts_seo_suffix_and_fixes_caps():
    assert cleaning.display_name("SPARTAN COWORK - BEST CO-WORKING SPACE IN MUMBAI") == "Spartan Cowork"
    assert cleaning.display_name("Awfis Coworking") == "Awfis Coworking"


def test_clean_url():
    assert cleaning.clean_url("WWW.Example.com/") == "https://example.com"
    assert cleaning.clean_url("https://www.foo.com/path/") == "https://foo.com/path"
    assert cleaning.clean_url(None) is None


# ---------- dedupe: things that SHOULD merge ----------

def test_same_phone_same_name_same_building_merges():
    a = rec("Spartan Cowork", "301, Sunrise Tower, Link Road, Andheri West, Mumbai 400053",
            "+91 98200 11111", "p1")
    b = rec("Spartan Cowork", "Sunrise Tower, Link Road, Andheri, Mumbai 400053",
            "+91 98200 11111", "p2")
    out = cleaning.dedupe([a, b])
    assert len(out) == 1 and out[0]["merged_records"] == 2


def test_same_place_id_merges_and_fills_missing_phone():
    a = rec("Foo Hub", "1 Some Building, Mumbai", None, "same")
    b = rec("Foo Hub", "1 Some Building, Mumbai", "+91 98200 11111", "same")
    out = cleaning.dedupe([a, b])
    assert len(out) == 1
    assert out[0]["phone"] == "+919820011111"


# ---------- dedupe: things that must NOT merge ----------

def test_chain_branches_with_different_phones_stay_separate():
    a = rec("The Executive Centre",
            "Level 6 & 7, Maker Maxity, 4, North Ave, BKC, Bandra East, Mumbai 400051",
            "+91 22 6666 1111", "p1")
    b = rec("The Executive Centre",
            "Level 3, The Capital, Plot C-70, G Block, BKC, Bandra East, Mumbai 400051",
            "+91 22 7777 2222", "p2")
    assert len(cleaning.dedupe([a, b])) == 2


def test_same_name_different_buildings_stay_separate():
    a = rec("WeWork", "Raheja Platinum, Andheri Kurla Road, Andheri East, Mumbai 400059")
    b = rec("WeWork", "Oberoi Garden City, Commerz, Goregaon East, Mumbai 400063")
    assert len(cleaning.dedupe([a, b])) == 2


def test_shared_toll_free_number_alone_does_not_merge():
    a = rec("WeWork", "Raheja Platinum, Andheri Kurla Road, Andheri East, Mumbai 400059", "1800 123 999000")
    b = rec("WeWork", "Oberoi Garden City, Commerz, Goregaon East, Mumbai 400063", "1800 123 999000")
    assert len(cleaning.dedupe([a, b])) == 2


# ---------- completeness and ids ----------

def test_is_complete_rule():
    assert cleaning.is_complete({"company_name": "X", "phone": "+919999999999"})
    assert cleaning.is_complete({"company_name": "X", "email": "a@x.com"})
    assert not cleaning.is_complete({"company_name": "X"})
    assert not cleaning.is_complete({"phone": "+919999999999"})


def test_lead_id_is_stable_across_runs():
    r = rec("Foo Hub", "1 Some Building, Mumbai", None, "pid-1")
    first = cleaning.dedupe([r])[0]["lead_id"]
    second = cleaning.dedupe([r])[0]["lead_id"]
    assert first == second and first.startswith("L")