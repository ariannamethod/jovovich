CC ?= cc
CFLAGS ?= -O2 -std=c11 -Wall -Wextra -Wpedantic -Werror
NOTORCH_ROOT ?= deps/notorch
AML_ROOT ?= deps/aml
BLAS_FLAGS ?=
BLAS_LIBS ?=

.PHONY: all check clean native-deps
all: build/check-receipts build/jovovich-replay build/review-demo build/jovovich build/jovovich-pack build/jovovich-report

build:
	mkdir -p build

build/review-demo: src/review.c src/review.h src/trace_gate.h src/json.h examples/review_demo.c examples/review_fixtures.h | build
	$(CC) $(CFLAGS) -Isrc src/review.c examples/review_demo.c -lm -o $@

build/check-receipts: tools/check_receipts.c src/report_json.h $(NOTORCH_ROOT)/tools/narrow_json.h | build
	$(CC) $(CFLAGS) -Isrc -I$(NOTORCH_ROOT) $< -o $@

build/check-review: src/review.c src/review.h src/trace_gate.h src/json.h tests/check_review.c | build
	$(CC) $(CFLAGS) -Isrc src/review.c tests/check_review.c -lm -o $@

native-deps:
	$(MAKE) -C $(NOTORCH_ROOT) lib lib_harness BLAS_FLAGS="$(BLAS_FLAGS)" BLAS_LIBS="$(BLAS_LIBS)"
	$(MAKE) -C $(AML_ROOT) libaml.a

build/jovovich: src/visual.c src/visual.h src/git_context.h src/prompt_text.h src/model_bytes.h src/model_manifest.h src/facts.c src/facts.h src/trace_gate.c src/trace_gate.h src/run_selection.c src/run_selection.h src/boundary.c src/boundary.h src/live.c src/readout.c src/readout.h src/report_json.h src/review.c src/review.h src/json.h src/hash.h native-deps | build
	$(CC) $(CFLAGS) -Isrc -I$(NOTORCH_ROOT) -I$(AML_ROOT)/core src/live.c src/visual.c src/run_selection.c src/trace_gate.c src/boundary.c src/review.c src/readout.c src/facts.c $(AML_ROOT)/libaml.a $(NOTORCH_ROOT)/libnotorch_harness.a $(NOTORCH_ROOT)/libnotorch.a -lm -pthread $(BLAS_LIBS) -o $@

build/voice-pilot: tools/voice_pilot.c src/model_bytes.h src/hash.h src/report_json.h src/json.h native-deps | build
	$(CC) $(CFLAGS) -Isrc -I$(NOTORCH_ROOT) -I$(AML_ROOT)/core $< $(AML_ROOT)/libaml.a $(NOTORCH_ROOT)/libnotorch_harness.a $(NOTORCH_ROOT)/libnotorch.a -lm -pthread $(BLAS_LIBS) -o $@

build/check-prompt-tokens: tests/check_prompt_tokens.c src/prompt_text.h native-deps | build
	$(CC) $(CFLAGS) -Isrc -I$(NOTORCH_ROOT) -I$(AML_ROOT)/core $< $(AML_ROOT)/libaml.a $(NOTORCH_ROOT)/libnotorch_harness.a $(NOTORCH_ROOT)/libnotorch.a -lm -pthread $(BLAS_LIBS) -o $@

build/check-voice: tests/check_voice.c tools/voice_pilot.c src/prompt_text.h src/model_bytes.h src/hash.h src/report_json.h src/json.h native-deps | build
	$(CC) $(CFLAGS) -Isrc -I$(NOTORCH_ROOT) -I$(AML_ROOT)/core $< $(AML_ROOT)/libaml.a $(NOTORCH_ROOT)/libnotorch_harness.a $(NOTORCH_ROOT)/libnotorch.a -lm -pthread $(BLAS_LIBS) -o $@

build/check-model-cancel: tests/check_model_cancel.c src/model_bytes.h src/hash.h native-deps | build
	$(CC) $(CFLAGS) -Isrc -I$(NOTORCH_ROOT) $< $(NOTORCH_ROOT)/sha256.c -lm -o $@

build/check-model-bytes: tests/check_model_bytes.c src/model_bytes.h src/hash.h native-deps | build
	$(CC) $(CFLAGS) -Isrc -I$(NOTORCH_ROOT) $< $(NOTORCH_ROOT)/libnotorch_harness.a $(NOTORCH_ROOT)/libnotorch.a -lm -pthread $(BLAS_LIBS) -o $@

build/bench-review: tools/bench_review.c src/hash.h src/json.h src/report_json.h $(NOTORCH_ROOT)/tools/narrow_json.h $(NOTORCH_ROOT)/sha256.c $(NOTORCH_ROOT)/sha256.h | build
	$(CC) $(CFLAGS) -Isrc -I$(NOTORCH_ROOT) $< $(NOTORCH_ROOT)/sha256.c -lm -o $@

build/jovovich-pack: src/git_snapshot.h src/git_command.h src/git_context.h src/process.h src/facts.c src/facts.h src/pack.c src/batch.c src/batch.h src/review.c src/review.h src/trace_gate.h src/json.h src/hash.h native-deps | build
	$(CC) $(CFLAGS) -Isrc -I$(NOTORCH_ROOT) -I$(AML_ROOT)/core src/pack.c src/batch.c src/review.c src/facts.c $(AML_ROOT)/libaml.a $(NOTORCH_ROOT)/sha256.c -lm -pthread -o $@

build/jovovich-replay: src/snapshot_history.h src/snapshot_recall.h src/snapshot_compare.h src/snapshot_routes.h src/pr_history.c src/pr_history.h src/hunk_trial.h src/git_snapshot.h src/git_command.h src/git_context.h src/replay.c src/batch.c src/process.h src/facts.c src/facts.h src/trace_gate.c src/trace_gate.h src/review.c src/review.h src/json.h src/report_json.h src/hash.h src/batch.h build/jovovich-pack | build
	$(CC) $(CFLAGS) -Isrc -I$(NOTORCH_ROOT) -I$(AML_ROOT)/core src/replay.c src/pr_history.c src/batch.c src/facts.c src/trace_gate.c src/review.c $(AML_ROOT)/libaml.a $(NOTORCH_ROOT)/sha256.c -lm -pthread -o $@

build/jovovich-report: src/pr_history.h src/pr_history.c src/snapshot_history.h src/snapshot_recall.h src/snapshot_compare.h src/git_command.h src/report_findings.h src/process.h src/git_context.h src/model_manifest.h src/facts.c src/facts.h src/trace_gate.c src/trace_gate.h src/boundary_view.h src/boundary.h src/boundary.c src/report.c src/report_json.h src/batch.c src/batch.h src/review.c src/review.h src/json.h src/hash.h native-deps | build build/jovovich-replay
	$(CC) $(CFLAGS) -Isrc -I$(NOTORCH_ROOT) -I$(AML_ROOT)/core src/trace_gate.c src/boundary.c src/report.c src/pr_history.c src/batch.c src/review.c src/facts.c $(AML_ROOT)/libaml.a $(NOTORCH_ROOT)/sha256.c -lm -pthread -o $@

build/check-pipeline: tests/check_pipeline.c src/git_context.h src/report_json.h src/hash.h native-deps | build
	$(CC) $(CFLAGS) -I$(NOTORCH_ROOT) -I$(AML_ROOT)/core $< $(AML_ROOT)/libaml.a $(NOTORCH_ROOT)/sha256.c -lm -pthread -o $@

build/check-git: tests/check_git.c src/hash.h native-deps | build
	$(CC) $(CFLAGS) -Isrc -I$(NOTORCH_ROOT) tests/check_git.c $(NOTORCH_ROOT)/sha256.c -lm -o $@

build/batch-fixture: src/facts.c src/facts.h tests/batch_fixture.c src/review.c src/review.h src/trace_gate.c src/trace_gate.h src/json.h src/hash.h native-deps | build
	$(CC) $(CFLAGS) -Isrc -I$(NOTORCH_ROOT) -I$(AML_ROOT)/core tests/batch_fixture.c src/review.c src/facts.c src/trace_gate.c $(AML_ROOT)/libaml.a $(NOTORCH_ROOT)/sha256.c -lm -pthread -o $@

build/score-quality: src/model_manifest.h src/trace_gate.c src/trace_gate.h src/boundary_view.h src/boundary.h src/trace_gate.c src/boundary.c tests/score_quality.c src/report_json.h src/review.c src/review.h src/json.h src/hash.h native-deps | build
	$(CC) $(CFLAGS) -Isrc -I$(NOTORCH_ROOT) -I$(AML_ROOT)/core src/trace_gate.c src/boundary.c tests/score_quality.c src/review.c $(AML_ROOT)/libaml.a $(NOTORCH_ROOT)/sha256.c -lm -pthread -o $@

build/semantic-corpus: src/boundary.h src/boundary.c tools/semantic_corpus.c src/report_json.h src/json.h src/hash.h native-deps | build
	$(CC) $(CFLAGS) -Isrc -I$(NOTORCH_ROOT) -I$(AML_ROOT)/core tools/semantic_corpus.c src/boundary.c $(AML_ROOT)/libaml.a $(NOTORCH_ROOT)/sha256.c -lm -pthread -o $@

build/jovovich-readout: tools/semantic_readout.c src/readout.c src/readout.h src/report_json.h src/hash.h src/json.h native-deps | build
	$(CC) $(CFLAGS) -Isrc -I$(NOTORCH_ROOT) tools/semantic_readout.c src/readout.c $(NOTORCH_ROOT)/libnotorch_harness.a $(NOTORCH_ROOT)/libnotorch.a -lm -pthread $(BLAS_LIBS) -o $@

build/boundary-observations: tools/boundary_observations.c src/boundary.c src/boundary.h src/report_json.h src/hash.h src/json.h native-deps | build
	$(CC) $(CFLAGS) -Isrc -I$(NOTORCH_ROOT) -I$(AML_ROOT)/core tools/boundary_observations.c src/boundary.c $(AML_ROOT)/libaml.a $(NOTORCH_ROOT)/sha256.c -lm -pthread -o $@

build/compare-comment-pairs: tools/compare_comment_pairs.c src/report_json.h native-deps | build
	$(CC) $(CFLAGS) -Isrc -I$(NOTORCH_ROOT) tools/compare_comment_pairs.c -lm -o $@

build/score-run-selection: tools/score_run_selection.c src/run_selection.c src/run_selection.h src/report_json.h src/hash.h native-deps | build
	$(CC) $(CFLAGS) -Isrc -I$(NOTORCH_ROOT) -I$(AML_ROOT)/core tools/score_run_selection.c src/run_selection.c $(AML_ROOT)/libaml.a $(NOTORCH_ROOT)/sha256.c -lm -pthread -o $@

build/score-traces: tools/score_traces.c src/report_json.h native-deps | build
	$(CC) $(CFLAGS) -Isrc -I$(NOTORCH_ROOT) tools/score_traces.c -lm -o $@

build/trace-corpus: tools/trace_corpus.c tools/trace_bodies.inc src/json.h src/hash.h native-deps | build
	$(CC) $(CFLAGS) -Isrc -I$(NOTORCH_ROOT) -I$(AML_ROOT)/core tools/trace_corpus.c $(AML_ROOT)/libaml.a $(NOTORCH_ROOT)/sha256.c -lm -pthread -o $@

build/check-trace-gate: tests/check_trace_gate.c src/trace_gate.c src/trace_gate.h src/report_json.h src/hash.h native-deps | build
	$(CC) $(CFLAGS) -Isrc -I$(NOTORCH_ROOT) -I$(AML_ROOT)/core tests/check_trace_gate.c src/trace_gate.c $(AML_ROOT)/libaml.a $(NOTORCH_ROOT)/sha256.c -lm -pthread -o $@

build/check-boundary: tests/check_boundary.c src/boundary.c src/boundary.h | build
	$(CC) $(CFLAGS) -Isrc tests/check_boundary.c src/boundary.c -o $@

build/check-corpus: tests/check_corpus.c src/report_json.h src/hash.h native-deps | build
	$(CC) $(CFLAGS) -Isrc -I$(NOTORCH_ROOT) tests/check_corpus.c $(NOTORCH_ROOT)/sha256.c -lm -o $@

check: build/check-receipts build/check-prompt-tokens build/check-model-cancel build/check-model-bytes build/check-voice build/compare-comment-pairs build/jovovich-replay build/bench-review build/check-trace-gate build/score-run-selection build/score-traces build/trace-corpus build/check-boundary build/boundary-observations build/jovovich-readout build/review-demo build/check-review build/check-pipeline build/jovovich-pack build/check-git build/jovovich-report build/batch-fixture build/score-quality build/semantic-corpus build/check-corpus
	./build/check-model-cancel
	./build/check-model-bytes
	./build/check-voice
	./build/check-boundary
	./build/check-trace-gate
	./build/check-review
	./build/review-demo --json all > build/reviews.jsonl
	./build/check-pipeline
	sh tests/check_git.sh
	sh tests/check_batch.sh
	sh tests/check_rule_memory.sh
	python3 tests/check_fact_sleep.py
	sh tests/check_counterexamples.sh
	sh tests/check_findings.sh
	sh tests/check_snapshot_history.sh
	sh tests/check_squash_history.sh
	sh tests/check_driver_sources.sh
	sh tests/check_onejev16.sh
	sh tests/check_submodules.sh
	sh tests/check_quality.sh
	sh tests/check_quality_publication.sh
	sh tests/check_corpus.sh
	sh tests/check_readout.sh
	sh tests/check_boundary_observations.sh
	sh tests/check_execution_traces.sh
	sh tests/check_run_selection.sh
	sh tests/check_bench_review.sh
	sh tests/check_voice.sh
	sh tests/check_paired_voice.sh

clean:
	rm -rf build

.PHONY: check-fact-sleep
check-fact-sleep: build/jovovich build/jovovich-pack build/jovovich-report build/jovovich-replay
	@test -n "$(MODEL)" || { echo 'Set MODEL to the original OneJev GGUF with tokenizer.gguf beside it.' >&2; exit 1; }
	$(MAKE) -C $(NOTORCH_ROOT) notorch qwen35_tokenize BLAS_FLAGS="$(BLAS_FLAGS)" BLAS_LIBS="$(BLAS_LIBS)"
	$(MAKE) -C $(AML_ROOT) harness NOTORCH_ROOT="$(abspath $(NOTORCH_ROOT))" NOTORCH_LDFLAGS="$(BLAS_LIBS)"
	python3 tests/check_fact_sleep.py --model "$(MODEL)" --aml "$(AML_ROOT)/runner/aml-harness" --notorch "$(NOTORCH_ROOT)/notorch"

.PHONY: check-visual
check-visual: build/jovovich
	@test -n "$(MODEL)" -a -n "$(VISION)" || { echo 'Set MODEL and VISION to the pinned original OneJev text and vision GGUFs.' >&2; exit 1; }
	python3 tests/check_visual.py --model "$(MODEL)" --tokenizer "$(dir $(MODEL))tokenizer.gguf" --vision "$(VISION)"
