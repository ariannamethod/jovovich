# jq accepts +47, 047, 47., and NaN as numbers. Check the raw literals before
# its JSON parser normalizes them. Quoted text is consumed in one match.
all(inputs; all(scan("\"(?:[^\"\\\\]|\\\\.)*\"|[^][{}:,\" \\t\\r\\n]+");
    startswith("\"") or . == "true" or . == "false" or . == "null" or
    test("\\A-?(0|[1-9][0-9]*)(\\.[0-9]+)?([eE][+-]?[0-9]+)?\\z")))
