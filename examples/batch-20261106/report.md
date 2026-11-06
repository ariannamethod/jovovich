**JOVOVICH · CONCERN**

Reviewed files: 2 · CONCERN: 1 · CLEAN: 1

Batch: `3bc5d827eb873c8d3ee9bb94b6e6a7a09ed52b273e58f2f8ec9f29c74042aea1`

---

**JOVOVICH · CLEAN**

**Reviewed file:** math\.c

**Git scope:** `022baf3856c49d8e4712370a703c1e4dc4596545` → `cf0b0eef5ca77a39f328c01bbc92502e8e34284c`

**Rules source:** RULES\.md (lines 1–2)

**Rule supplied for review**

> This C project uses only the standard C library\. Network dependencies are forbidden\.
> Functions named square must return x \* x\.
>

**Change under review**

```text
diff --git a/math.c b/math.c
index 90382d2..cb5bc66 100644
--- a/math.c
+++ b/math.c
@@ -1 +1 @@
-int square(int x) { return x * x; }
+int square(int x) { const int result = x * x; return result; }
```

**Choice probabilities:** CONCERN 22.4% · CLEAN 77.6%

---

**JOVOVICH · CONCERN**

**Reviewed file:** status\.c

**Git scope:** `022baf3856c49d8e4712370a703c1e4dc4596545` → `cf0b0eef5ca77a39f328c01bbc92502e8e34284c`

**Rules source:** RULES\.md (lines 1–2)

**Rule supplied for review**

> This C project uses only the standard C library\. Network dependencies are forbidden\.
> Functions named square must return x \* x\.
>

**Change under review**

```text
diff --git a/status.c b/status.c
index 69679a1..fb6bc09 100644
--- a/status.c
+++ b/status.c
@@ -1 +1,2 @@
-int status(void) { return 0; }
+#include <curl/curl.h>
+int status(void) { CURL *h = curl_easy_init(); return h != 0; }
```

**Choice probabilities:** CONCERN 84.5% · CLEAN 15.5%
