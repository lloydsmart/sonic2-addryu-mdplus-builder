PYTHON ?= python3
MANIFEST ?= config/tracks.json
INPUT_DIR ?= inputs/audio

.PHONY: help doctor bootstrap source rom audio package all test clean

help:
	@$(PYTHON) -m tools.mdplus_builder --help

doctor:
	@$(PYTHON) -m tools.mdplus_builder doctor

bootstrap:
	@$(PYTHON) -m tools.mdplus_builder bootstrap

source:
	@$(PYTHON) -m tools.mdplus_builder prepare-source

rom:
	@$(PYTHON) -m tools.mdplus_builder build-rom

audio:
	@$(PYTHON) -m tools.mdplus_builder prepare-audio --manifest $(MANIFEST) --input-dir "$(INPUT_DIR)"

package:
	@$(PYTHON) -m tools.mdplus_builder package --manifest $(MANIFEST)

all:
	@$(PYTHON) -m tools.mdplus_builder all --manifest $(MANIFEST) --input-dir "$(INPUT_DIR)"

test:
	@$(PYTHON) -m unittest discover -s tests -v

clean:
	@$(PYTHON) -m tools.mdplus_builder clean
