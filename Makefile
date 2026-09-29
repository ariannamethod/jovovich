CC ?= cc
NOTORCH ?= deps/notorch
CFLAGS ?= -O2 -Wall -Wextra -std=gnu11
NATIVE ?= $(shell $(CC) -march=native -E -x c /dev/null >/dev/null 2>&1 && echo -march=native)
CPPFLAGS += -I$(NOTORCH)
LDLIBS += -lm -pthread
# The in-tree float32 SIMD shim speeds the low-rank training projections.
# Override TRAIN_SIMD= for scalar or cross builds; no external BLAS is needed.
TRAIN_SIMD ?= $(shell $(CC) $(NATIVE) -dM -E -x c /dev/null 2>/dev/null | grep -q __AVX2__ && echo -DUSE_SIMD)

SUBSTRATE = $(NOTORCH)/notorch.c $(NOTORCH)/gguf.c \
            $(NOTORCH)/harness/runtime.c $(NOTORCH)/harness/arch_llama.c \
            $(NOTORCH)/examples/bpe.c
HEADERS = $(NOTORCH)/notorch.h $(NOTORCH)/gguf.h \
          $(NOTORCH)/harness/arch.h $(NOTORCH)/harness/arch_models.h \
          $(NOTORCH)/harness/runtime.h $(NOTORCH)/examples/bpe.h \
          $(NOTORCH)/examples/unicode_numbers.h

.PHONY: all harness train train-mlp probe-mlp probe-tokenization merge-head merge-mlp export-adapter test clean
all: harness
harness: build/jovovich-infer
merge-head: build/jovovich-merge-head
train: build/jovovich-train-head
train-mlp: build/jovovich-train-mlp
probe-mlp: build/jovovich-probe-mlp
probe-tokenization: build/jovovich-probe-tokenization
merge-mlp: build/jovovich-merge-mlp
export-adapter: build/jovovich-export-adapter

build/jovovich-infer: src/infer.c $(SUBSTRATE) $(HEADERS) Makefile
	@mkdir -p build
	$(CC) $(CPPFLAGS) $(CFLAGS) $(NATIVE) -o $@ src/infer.c $(SUBSTRATE) $(LDFLAGS) $(LDLIBS)

build/jovovich-merge-head: training/merge_head.c $(NOTORCH)/gguf.c $(NOTORCH)/gguf.h Makefile
	@mkdir -p build
	$(CC) $(CPPFLAGS) $(CFLAGS) -o $@ training/merge_head.c $(NOTORCH)/gguf.c $(LDFLAGS) $(LDLIBS)

build/jovovich-train-head: training/train_head.c $(SUBSTRATE) $(HEADERS) $(NOTORCH)/notorch_simd.h Makefile
	@mkdir -p build
	$(CC) $(CPPFLAGS) $(CFLAGS) $(NATIVE) $(TRAIN_SIMD) -o $@ training/train_head.c $(SUBSTRATE) $(LDFLAGS) $(LDLIBS)

build/jovovich-train-mlp: training/train_mlp.c $(SUBSTRATE) $(HEADERS) $(NOTORCH)/notorch_simd.h Makefile
	@mkdir -p build
	$(CC) $(CPPFLAGS) $(CFLAGS) $(NATIVE) $(TRAIN_SIMD) -o $@ training/train_mlp.c $(SUBSTRATE) $(LDFLAGS) $(LDLIBS)

build/jovovich-probe-mlp: training/probe_mlp.c training/train_mlp.c $(SUBSTRATE) $(HEADERS) $(NOTORCH)/notorch_simd.h Makefile
	@mkdir -p build
	$(CC) $(CPPFLAGS) $(CFLAGS) $(NATIVE) $(TRAIN_SIMD) -o $@ training/probe_mlp.c $(SUBSTRATE) $(LDFLAGS) $(LDLIBS)

build/jovovich-probe-tokenization: training/probe_tokenization.c training/train_mlp.c src/infer.c $(SUBSTRATE) $(HEADERS) $(NOTORCH)/notorch_simd.h Makefile
	@mkdir -p build
	$(CC) $(CPPFLAGS) $(CFLAGS) $(NATIVE) $(TRAIN_SIMD) -o $@ training/probe_tokenization.c $(SUBSTRATE) $(LDFLAGS) $(LDLIBS)

build/jovovich-merge-mlp: training/merge_mlp.c $(NOTORCH)/gguf.c $(NOTORCH)/gguf.h Makefile
	@mkdir -p build
	$(CC) $(CPPFLAGS) $(CFLAGS) -o $@ training/merge_mlp.c $(NOTORCH)/gguf.c $(LDFLAGS) $(LDLIBS)

build/jovovich-export-adapter: training/export_adapter.c $(SUBSTRATE) $(HEADERS) Makefile
	@mkdir -p build
	$(CC) $(CPPFLAGS) $(CFLAGS) $(NATIVE) -o $@ training/export_adapter.c $(SUBSTRATE) $(LDFLAGS) $(LDLIBS)

build/test-head: test/head.c training/train_head.c $(SUBSTRATE) $(HEADERS) Makefile
	@mkdir -p build
	$(CC) $(CPPFLAGS) $(CFLAGS) $(NATIVE) $(TRAIN_SIMD) -o $@ test/head.c $(SUBSTRATE) $(LDFLAGS) $(LDLIBS)

build/test-mlp: test/mlp.c training/train_mlp.c $(SUBSTRATE) $(HEADERS) $(NOTORCH)/notorch_simd.h Makefile
	@mkdir -p build
	$(CC) $(CPPFLAGS) $(CFLAGS) $(NATIVE) $(TRAIN_SIMD) -o $@ test/mlp.c $(SUBSTRATE) $(LDFLAGS) $(LDLIBS)

build/test-optimizer: test/optimizer.c training/train_mlp.c $(SUBSTRATE) $(HEADERS) $(NOTORCH)/notorch_simd.h Makefile
	@mkdir -p build
	$(CC) $(CPPFLAGS) $(CFLAGS) $(NATIVE) $(TRAIN_SIMD) -o $@ test/optimizer.c $(SUBSTRATE) $(LDFLAGS) $(LDLIBS)

build/test-weighting: test/weighting.c training/train_mlp.c $(SUBSTRATE) $(HEADERS) $(NOTORCH)/notorch_simd.h Makefile
	@mkdir -p build
	$(CC) $(CPPFLAGS) $(CFLAGS) $(NATIVE) $(TRAIN_SIMD) -o $@ test/weighting.c $(SUBSTRATE) $(LDFLAGS) $(LDLIBS)

test: harness merge-mlp build/test-head build/test-mlp build/test-optimizer build/test-weighting
	./build/test-head
	./build/test-mlp
	./build/test-optimizer
	./build/test-weighting
	node --test test/*.test.mjs

clean:
	rm -rf build
