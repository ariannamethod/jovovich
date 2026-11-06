CC ?= cc
CFLAGS ?= -O2 -std=c11 -Wall -Wextra -Wpedantic -Werror

.PHONY: all check clean
all: build/review-demo

build:
	mkdir -p build

build/review-demo: src/review.c src/review.h examples/review_demo.c examples/review_fixtures.h | build
	$(CC) $(CFLAGS) -Isrc src/review.c examples/review_demo.c -lm -o $@

build/check-review: src/review.c src/review.h tests/check_review.c | build
	$(CC) $(CFLAGS) -Isrc src/review.c tests/check_review.c -lm -o $@

check: build/review-demo build/check-review
	./build/check-review
	./build/review-demo --json all > build/reviews.jsonl
	python3 tests/check_saved_results.py build/reviews.jsonl

clean:
	rm -rf build
