CC ?= cc
CFLAGS ?= -O2 -std=c11 -Wall -Wextra -Wpedantic -Werror
NOTORCH_ROOT ?= deps/notorch
AML_ROOT ?= deps/aml
BLAS_FLAGS ?=
BLAS_LIBS ?=

.PHONY: all check clean native-deps
all: build/review-demo build/jovovich

build:
	mkdir -p build

build/review-demo: src/review.c src/review.h examples/review_demo.c examples/review_fixtures.h | build
	$(CC) $(CFLAGS) -Isrc src/review.c examples/review_demo.c -lm -o $@

build/check-review: src/review.c src/review.h tests/check_review.c | build
	$(CC) $(CFLAGS) -Isrc src/review.c tests/check_review.c -lm -o $@

native-deps:
	$(MAKE) -C $(NOTORCH_ROOT) lib lib_harness BLAS_FLAGS="$(BLAS_FLAGS)" BLAS_LIBS="$(BLAS_LIBS)"
	$(MAKE) -C $(AML_ROOT) libaml.a

build/jovovich: src/live.c src/review.c src/review.h native-deps | build
	$(CC) $(CFLAGS) -Isrc -I$(NOTORCH_ROOT) -I$(AML_ROOT)/core src/live.c src/review.c $(AML_ROOT)/libaml.a $(NOTORCH_ROOT)/libnotorch_harness.a $(NOTORCH_ROOT)/libnotorch.a -lm -pthread $(BLAS_LIBS) -o $@

build/check-pipeline: tests/check_pipeline.c native-deps | build
	$(CC) $(CFLAGS) -I$(NOTORCH_ROOT) -I$(AML_ROOT)/core $< $(AML_ROOT)/libaml.a $(NOTORCH_ROOT)/sha256.c -lm -pthread -o $@

check: build/review-demo build/check-review build/check-pipeline
	./build/check-review
	./build/review-demo --json all > build/reviews.jsonl
	./build/check-pipeline

clean:
	rm -rf build
