"""Comparison invariants on explicitly synthetic, independently encoded journals."""
import copy
import hashlib
import json
import struct
import zlib
from check_visual_batch import ROOT, command, encode


def check_comparisons(replay, work, original_memory, original_rows):
    def query(memory, scope="fixture/east", pr=7, ids=None, ok=True):
        return command([replay,"reviews",memory,scope,pr,*(["--compare",*ids] if ids else [])],ok=ok)

    original = {p.name:p.read_bytes() for p in original_memory.iterdir() if p.is_file()}
    index = json.loads(query(original_memory))["reviews"]
    assert len(index)==2 and [x["ordinal"] for x in index]==[1,2]
    ids=[x["observation_id"] for x in index]
    result=json.loads(query(original_memory,ids=ids))
    assert result["before"]["observation"]==original_rows[0]
    assert result["after"]["observation"]==original_rows[1]
    assert result["summary"]["unchanged_clean"]==1
    assert result["files"][1]["transition"]=="not_comparable"  # different visual memory key
    assert result["files"][1]["reasons"]==["policy_changed"]
    assert query(original_memory,ids=ids)==query(original_memory,ids=ids)
    assert json.loads(query(original_memory,"fixture/absent"))["reviews"]==[]
    for scope,pr,pair in [("fixture/west",7,ids),("fixture/east",8,ids),
                          ("fixture/east",7,ids[::-1]),("fixture/east",7,[ids[0],ids[0]]),
                          ("fixture/east",7,[ids[0],"0"*64]),("fixture/east",7,[ids[0],"invalid"])]:
        query(original_memory,scope,pr,pair,ok=False)

    memory=work/"comparison-memory";memory.mkdir()
    journal=memory/("pr-"+hashlib.sha256(b"fixture/east").hexdigest()+"-7.checkpoint")
    fixture=ROOT/"build/review-history-fixture"

    def store(rows):
        data="".join(encode(row)+"\n" for row in rows).encode()
        return command([fixture,journal,"fixture/east",7],data).decode().splitlines()

    def recount(row):
        review=row["evidence"]["review"]; files=review["files"]
        visual=[f for f in files if "visual_request" in f["input"]]
        def concern(f):
            return (f["answer"]["verdict"] if "visual_request" in f["input"] else f["answer"]["choice"]["verdict"])=="CONCERN"
        def counts(fs):
            c=sum(concern(f) for f in fs)
            return dict(reviewed_files=len(fs),concern_files=c,clean_files=len(fs)-c)
        review["summary"]=counts(files)|{"verdict":"CONCERN" if any(map(concern,files)) else "CLEAN"}
        review["visual_summary"]=counts(visual)

    def sample(concern, clock):
        row=copy.deepcopy(original_rows[0])
        for f in row["evidence"]["review"]["files"]:
            a=f["answer"];verdict="CONCERN" if concern else "CLEAN"
            if "visual_request" in f["input"]:
                a.update(verdict=verdict,concern=.731058598 if concern else .268941432,
                         clean=.268941432 if concern else .731058598,
                         logit_a=2 if concern else 1,logit_b=1 if concern else 2,
                         p_a=.731058598 if concern else .268941432,p_b=.268941432 if concern else .731058598,
                         letter="A" if concern else "B")
            else:
                a["choice"]={"verdict":verdict,"probabilities":{"CONCERN":.880797078 if concern else .119202922,"CLEAN":.119202922 if concern else .880797078}}
                view=a["execution"]["file_view"]
                for order in ("concern_first","clean_first"):
                    is_a=concern==(order=="concern_first")
                    view[order].update(logit_a=2 if is_a else 0,logit_b=0 if is_a else 2)
                a["execution"]["reviewed_at"]["millisecond"]=clock
        recount(row)
        return row

    def compare(before,after):
        pair=store([before,after]);checkpoint=journal.read_bytes()
        raw=query(memory,ids=pair); r=json.loads(raw)
        assert r["before"]["observation"]==before and r["after"]["observation"]==after
        assert sum(r["summary"].values())==len(r["files"])
        assert journal.read_bytes()==checkpoint
        return r

    for before,after,state in [(True,False,"concern_to_clean"),(False,True,"clean_to_concern"),
                               (True,True,"unchanged_concern"),(False,False,"unchanged_clean")]:
        r=compare(sample(before,1),sample(after,2))
        assert r["summary"][state]==2 and all(f["transition"]==state and not f["reasons"] for f in r["files"])

    # A newer record at the same head remains a distinct, explicitly selected review.
    before,after=sample(True,10),sample(False,11)
    pair=store([before,after]);pinned=query(memory,ids=pair)
    third=sample(True,12);store([before,after,third])
    assert query(memory,ids=pair)==pinned
    legacy=copy.deepcopy(before);del legacy["evidence"]["review"]
    all_ids=store([before,legacy,after])
    listed=json.loads(query(memory))["reviews"]
    assert [x["ordinal"] for x in listed]==[1,3]
    query(memory,ids=all_ids[:2],ok=False)
    duplicated=store([before,before,after])
    query(memory,ok=False);query(memory,ids=[duplicated[0],duplicated[2]],ok=False)

    # Changed scope of the review: absence and renaming never manufacture CLEAN.
    removed=copy.deepcopy(after);removed["evidence"]["review"]["files"].pop(0);recount(removed)
    r=compare(before,removed)
    assert r["files"][0]["transition"]=="not_reviewed_after" and r["files"][0]["after"] is None
    r=compare(removed,before)
    assert r["summary"]["first_review"]==1
    renamed=copy.deepcopy(after);f=renamed["evidence"]["review"]["files"][0]
    f["file"]=f["input"]["file"]=f["answer"]["scope"]["file"]="renamed.html"
    r=compare(before,renamed)
    assert r["summary"]["not_reviewed_after"]==r["summary"]["first_review"]==1

    # An image can move from a text encoding to a binary visual review.
    def rename_file(f,path):
        f["file"]=f["input"]["file"]=path
        if "scope" in f["answer"]: f["answer"]["scope"]["file"]=path
        else:
            for side in ("before","after"):
                f["answer"]["comparison"][side]["origin"]["source"]["path"]=path
    kind_before=copy.deepcopy(before);rename_file(kind_before["evidence"]["review"]["files"][0],"screen.ppm")
    rename_file(kind_before["evidence"]["review"]["files"][1],"other.ppm")
    kind_after=copy.deepcopy(after);visual=kind_after["evidence"]["review"]["files"][1]
    kind_after["evidence"]["review"]["files"]=[copy.deepcopy(visual),copy.deepcopy(visual)]
    rename_file(kind_after["evidence"]["review"]["files"][1],"other.ppm");recount(kind_after)
    assert compare(kind_before,kind_after)["files"][0]["reasons"]==["review_kind_changed"]

    def changed_rule(row):
        fact=row["evidence"]["fact"]
        fact["supersedes"]=fact["sequence"];fact["sequence"]+=1
        fact["origin"]["rule_excerpt"]="Buttons must say Cancel.\n"
        for f in row["evidence"]["review"]["files"]:
            f["input"]["fact"]=copy.deepcopy(fact)
            f["input"]["rule_excerpt"]=fact["origin"]["rule_excerpt"]
            if "fact" in f["answer"]:
                f["answer"]["fact"]=copy.deepcopy(fact)
                f["answer"]["input"]["rule_excerpt"]=fact["origin"]["rule_excerpt"]

    def files(row): return row["evidence"]["review"]["files"]
    changes=[
        ("rule_changed",None,changed_rule),
        ("model_changed",0,lambda r:files(r)[0]["answer"]["execution"].update(weights_sha256="a"*64)),
        ("model_changed",1,lambda r:files(r)[1]["answer"].update(tokenizer_sha256="b"*64)),
        ("model_changed",1,lambda r:files(r)[1]["answer"]["comparison"]["after"]["origin"]["observation"].update(vision_weights_sha256="c"*64)),
        ("policy_changed",0,lambda r:files(r)[0]["answer"]["execution"]["file_view"].update(policy="html-next/1")),
        ("policy_changed",0,lambda r:files(r)[0]["answer"]["execution"].update(readout_sha256="d"*64)),
        ("policy_changed",1,lambda r:files(r)[1]["answer"].update(choice_a="CLEAN",choice_b="CONCERN")),
        ("policy_changed",1,lambda r:files(r)[1]["answer"]["comparison"]["after"]["origin"]["observation"].update(question="Which color is visible?")),
        ("policy_changed",1,lambda r:files(r)[1]["answer"]["comparison"]["after"]["origin"]["observation"]["image"].update(max_pixels=65536)),
        ("rule_changed",1,lambda r:files(r)[1]["answer"]["comparison"]["rule"].update(quote="Buttons must say Cancel.\n")),
    ]
    for reason,target,change in changes:
        altered=copy.deepcopy(after);change(altered)
        r=compare(before,altered)
        for i,f in enumerate(r["files"]):
            if target is None or target==i:
                assert f["transition"]=="not_comparable" and reason in f["reasons"],(reason,target,f)
            else: assert f["transition"]=="concern_to_clean"
    altered=copy.deepcopy(after);changed_rule(altered)
    files(altered)[0]["answer"]["execution"].update(weights_sha256="a"*64,readout_sha256="b"*64)
    assert compare(before,altered)["files"][0]["reasons"]==["rule_changed","model_changed","policy_changed"]

    # Valid AML container and fresh evidence digest: semantic/shape gates must still reject.
    malformed=[
        lambda r:r["evidence"]["review"]["summary"].update(reviewed_files=99),
        lambda r:files(r).append(copy.deepcopy(files(r)[0])),
        lambda r:files(r)[0]["answer"]["choice"].update(verdict="UNKNOWN"),
        lambda r:files(r)[0]["answer"]["execution"].pop("weights_sha256"),
        lambda r:files(r)[0]["input"].update(file="foreign.html"),
        lambda r:files(r)[1]["answer"]["comparison"]["after"]["origin"]["source"].update(pull_request=8),
    ]
    for damage in malformed:
        broken=copy.deepcopy(after);damage(broken);pair=store([before,broken])
        query(memory,ok=False);query(memory,ids=pair,ok=False)
    # Disjoint maximum-size manifests exercise all 128 aligned output slots.
    maximum=[]
    for row,prefix in [(before,"old"),(after,"new")]:
        expanded=copy.deepcopy(row);text_file,visual_file=files(expanded)
        expanded["evidence"]["review"]["files"]=[]
        for i in range(63):
            f=copy.deepcopy(text_file);rename_file(f,f"{prefix}-{i}.c");files(expanded).append(f)
        rename_file(visual_file,f"{prefix}-image.ppm");files(expanded).append(visual_file);recount(expanded)
        maximum.append(expanded)
    r=compare(*maximum)
    assert len(r["files"])==128 and r["summary"]["first_review"]==r["summary"]["not_reviewed_after"]==64
    too_many=copy.deepcopy(maximum[1]);f=copy.deepcopy(files(too_many)[0]);rename_file(f,"extra.c")
    files(too_many).append(f);recount(too_many);pair=store([maximum[0],too_many])
    query(memory,ok=False);query(memory,ids=pair,ok=False)
    pair=store([before,after]);raw=journal.read_bytes()
    model=files(before)[0]["answer"]["execution"]["weights_sha256"].encode()
    for old,new in [(b'"verdict":"CONCERN"',b'"verdict":"CLEAN  "'),(model,b"e"*64),(b'"review":',b'"hidden":')]:
        altered=bytearray(raw.replace(old,new,1));assert altered!=raw
        struct.pack_into("<I",altered,28,zlib.crc32(altered[:28]+altered[32:]))
        journal.write_bytes(altered)
        query(memory,ok=False);query(memory,ids=pair,ok=False)
    data="".join(encode(row)+"\n" for row in [before,after]).encode()
    for scope,pr in [("fixture/west",7),("fixture/east",8)]:
        foreign=memory/("pr-"+hashlib.sha256(scope.encode()).hexdigest()+f"-{pr}.checkpoint")
        foreign_ids=command([fixture,foreign,scope,pr],data).decode().splitlines()
        query(memory,scope,pr,ok=False);query(memory,scope,pr,foreign_ids,ok=False)
    assert {p.name:p.read_bytes() for p in original_memory.iterdir() if p.is_file()}==original
    print("PASS: four vote transitions, immutable IDs, offline/legacy history, scope/order isolation, absent/renamed files, rule/model/policy changes, semantic/digest rejection")
