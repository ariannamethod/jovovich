CC ?= cc
CFLAGS ?= -O2 -std=c11 -Wall -Wextra -Wpedantic -Werror
NOTORCH_ROOT ?= deps/notorch
AML_ROOT ?= deps/aml
BLAS_FLAGS ?=
BLAS_LIBS ?=

.PHONY: all check clean native-deps
all: build/review-demo build/jovovich build/jovovich-pack build/jovovich-report

build:
	mkdir -p build

build/review-demo: src/review.c src/review.h src/json.h examples/review_demo.c examples/review_fixtures.h | build
	$(CC) $(CFLAGS) -Isrc src/review.c examples/review_demo.c -lm -o $@

build/check-review: src/review.c src/review.h src/json.h tests/check_review.c | build
	$(CC) $(CFLAGS) -Isrc src/review.c tests/check_review.c -lm -o $@

native-deps:
	$(MAKE) -C $(NOTORCH_ROOT) lib lib_harness BLAS_FLAGS="$(BLAS_FLAGS)" BLAS_LIBS="$(BLAS_LIBS)"
	$(MAKE) -C $(AML_ROOT) libaml.a

build/jovovich: src/live.c src/readout.c src/readout.h src/report_json.h src/review.c src/review.h src/json.h src/hash.h native-deps | build
	$(CC) $(CFLAGS) -Isrc -I$(NOTORCH_ROOT) -I$(AML_ROOT)/core src/live.c src/review.c src/readout.c $(AML_ROOT)/libaml.a $(NOTORCH_ROOT)/libnotorch_harness.a $(NOTORCH_ROOT)/libnotorch.a -lm -pthread $(BLAS_LIBS) -o $@

build/jovovich-pack: src/pack.c src/batch.c src/batch.h src/review.c src/review.h src/json.h src/hash.h native-deps | build
	$(CC) $(CFLAGS) -Isrc -I$(NOTORCH_ROOT) -I$(AML_ROOT)/core src/pack.c src/batch.c src/review.c $(AML_ROOT)/libaml.a $(NOTORCH_ROOT)/sha256.c -lm -pthread -o $@

build/jovovich-report: src/report.c src/report_json.h src/batch.c src/batch.h src/review.c src/review.h src/json.h src/hash.h native-deps | build
	$(CC) $(CFLAGS) -Isrc -I$(NOTORCH_ROOT) -I$(AML_ROOT)/core src/report.c src/batch.c src/review.c $(AML_ROOT)/libaml.a $(NOTORCH_ROOT)/sha256.c -lm -pthread -o $@

build/check-pipeline: tests/check_pipeline.c native-deps | build
	$(CC) $(CFLAGS) -I$(NOTORCH_ROOT) -I$(AML_ROOT)/core $< $(AML_ROOT)/libaml.a $(NOTORCH_ROOT)/sha256.c -lm -pthread -o $@

build/check-git: tests/check_git.c src/hash.h native-deps | build
	$(CC) $(CFLAGS) -Isrc -I$(NOTORCH_ROOT) tests/check_git.c $(NOTORCH_ROOT)/sha256.c -lm -o $@

build/batch-fixture: tests/batch_fixture.c src/review.c src/review.h src/json.h src/hash.h native-deps | build
	$(CC) $(CFLAGS) -Isrc -I$(NOTORCH_ROOT) -I$(AML_ROOT)/core tests/batch_fixture.c src/review.c $(AML_ROOT)/libaml.a $(NOTORCH_ROOT)/sha256.c -lm -pthread -o $@

build/score-quality: tests/score_quality.c src/report_json.h src/review.c src/review.h src/json.h src/hash.h native-deps | build
	$(CC) $(CFLAGS) -Isrc -I$(NOTORCH_ROOT) -I$(AML_ROOT)/core tests/score_quality.c src/review.c $(AML_ROOT)/libaml.a $(NOTORCH_ROOT)/sha256.c -lm -pthread -o $@

build/semantic-corpus: tools/semantic_corpus.c src/report_json.h src/json.h src/hash.h native-deps | build
	$(CC) $(CFLAGS) -Isrc -I$(NOTORCH_ROOT) -I$(AML_ROOT)/core tools/semantic_corpus.c $(AML_ROOT)/libaml.a $(NOTORCH_ROOT)/sha256.c -lm -pthread -o $@

build/jovovich-readout: tools/semantic_readout.c src/readout.c src/readout.h src/report_json.h src/hash.h src/json.h native-deps | build
	$(CC) $(CFLAGS) -Isrc -I$(NOTORCH_ROOT) tools/semantic_readout.c src/readout.c $(NOTORCH_ROOT)/libnotorch_harness.a $(NOTORCH_ROOT)/libnotorch.a -lm -pthread $(BLAS_LIBS) -o $@

build/check-corpus: tests/check_corpus.c src/report_json.h src/hash.h native-deps | build
	$(CC) $(CFLAGS) -Isrc -I$(NOTORCH_ROOT) tests/check_corpus.c $(NOTORCH_ROOT)/sha256.c -lm -o $@

check: build/jovovich-readout build/review-demo build/check-review build/check-pipeline build/jovovich-pack build/check-git build/jovovich-report build/batch-fixture build/score-quality build/semantic-corpus build/check-corpus
	./build/check-review
	./build/review-demo --json all > build/reviews.jsonl
	./build/check-pipeline
	sh tests/check_git.sh
	sh tests/check_batch.sh
	sh tests/check_submodules.sh
	sh tests/check_quality.sh
	sh tests/check_corpus.sh
	sh tests/check_readout.sh

clean:
	rm -rf build
